"""语音接口：状态查询 / 识别 / 合成。

- 识别：整句 WAV（16k 单声道）→ 文本；文本走现有 /api/chat/stream。
- 合成：文本 → 音频字节；前端负责播放与按钮打断（barge-in 升级位）。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.voice import VoiceParams

from app.config import is_lite_mode
from app.speech.base import (
    SpeechProviderError,
    SpeechStack,
    SpeechUnavailable,
)
from app.speech.activation import build_wake_texts, classify_intent
from app.speech.factory import stack_status

router = APIRouter(prefix="/api/voice", tags=["voice"])
_VOICE_CLIENTS = {"web", "widget"}


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    params: VoiceParams | None = None
    conversation_id: str | None = None

    model_config = {"extra": "forbid"}


class IntentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    model_config = {"extra": "forbid"}


def _stack(request: Request) -> SpeechStack:
    return request.app.state.speech


def _client(request: Request) -> str:
    value = request.headers.get("X-Voice-Client", "")
    if value not in _VOICE_CLIENTS:
        raise HTTPException(status_code=400, detail="缺少有效的语音客户端标识")
    return value


async def _require_lease(request: Request) -> str:
    client = _client(request)
    if not await request.app.state.voice_lease.is_owner(client):
        raise HTTPException(status_code=409, detail="当前语音由另一个客户端占用")
    return client


@router.post("/lease")
async def acquire_voice_lease(request: Request) -> dict:
    client = _client(request)
    acquired = await request.app.state.voice_lease.acquire(client)
    return {"client": client, "acquired": acquired, "ttl_seconds": 12}


@router.post("/lease/heartbeat")
async def heartbeat_voice_lease(request: Request) -> dict:
    client = await _require_lease(request)
    return {"client": client, "renewed": await request.app.state.voice_lease.heartbeat(client)}


@router.delete("/lease")
async def release_voice_lease(request: Request) -> dict:
    client = _client(request)
    await request.app.state.voice_lease.release(client)
    return {"client": client, "released": True}


async def _publish(request: Request, event_type: str, payload: dict | None = None) -> None:
    await request.app.state.event_hub.publish(
        EventEnvelope(
            event_type=event_type,
            source="speech",
            payload=payload or {},
        )
    )


@router.get("/status")
async def voice_status(request: Request) -> dict:
    stack = _stack(request)
    settings = request.app.state.settings
    body = stack_status(stack)
    body["auto_speak"] = settings.voice_auto_speak
    if is_lite_mode(settings):
        # lite 模式：语音整体禁用，报告与 health.voice_pipeline 保持一致，
        # 避免前端继续开麦监听却反复收到 503。
        body["enabled"] = False
        body["auto_speak"] = False
        body["stt"]["available"] = False
        body["tts"]["available"] = False
        body["degradation_reason"] = "轻量模式已禁用语音"
    body["language"] = settings.stt_language
    body["interruption_enabled"] = settings.interruption_enabled
    body["activation"] = {
        "enabled": False if is_lite_mode(settings) else settings.activation_enabled,
        "default_state": settings.activation_default_state,
        "persona_name": settings.activation_persona_name,
    }
    return body


@router.post("/intent")
async def voice_intent(request: Request, body: IntentRequest) -> dict:
    """识别文本分流：wake（唤醒词）/ sleep（静默指令）/ chat（普通对话）。

    静默态下普通文本是否忽略由前端根据当前模式决定，本接口只做无状态分类。
    """
    await _require_lease(request)
    settings = request.app.state.settings
    persona_name = settings.activation_persona_name
    if not settings.activation_enabled:
        return {"intent": "chat", "persona_name": persona_name, "reply": None}
    intent = classify_intent(
        body.text,
        persona_name=persona_name,
        wake_prefixes=settings.activation_wake_prefixes,
        sleep_phrases=settings.activation_sleep_phrases,
    )
    reply = None
    if intent == "wake":
        reply = f"在呢～我是{persona_name}，有什么想让我帮忙的？"
    elif intent == "sleep":
        prefix = settings.activation_wake_prefixes[0] if settings.activation_wake_prefixes else "你好"
        reply = f"好，我先安静一会儿。想找我的时候说「{prefix}，{persona_name}」就好啦。"
    return {
        "intent": intent,
        "persona_name": persona_name,
        "reply": reply,
        "wake_texts": build_wake_texts(persona_name, settings.activation_wake_prefixes),
    }

@router.post("/recognize")
async def recognize(request: Request, language: str = "zh") -> dict:
    await _require_lease(request)
    settings = request.app.state.settings
    if is_lite_mode(settings):
        raise HTTPException(status_code=503, detail="轻量模式已禁用语音识别")
    stack = _stack(request)
    if not stack.recognizer.available:
        raise HTTPException(status_code=503, detail="语音识别未配置：请先配置语音供应商")
    audio = await request.body()
    if len(audio) < 44 or audio[:4] != b"RIFF":
        raise HTTPException(status_code=422, detail="仅支持 WAV 音频（RIFF 头）")

    await _publish(request, "speech.started", {"mode": "recognize"})
    tmp_dir = request.app.state.settings.data_dir / "run"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    wav_path = tmp_dir / f"voice_in_{uuid4().hex[:10]}.wav"
    wav_path.write_bytes(audio)
    try:
        text = await stack.recognizer.recognize(str(wav_path), language)
    except SpeechUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SpeechProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass

    if not text.strip():
        raise HTTPException(status_code=422, detail="未识别到有效语音内容")
    return {
        "text": text.strip(),
        "provider": stack.recognizer.name,
        "available": True,
    }


@router.post("/synthesize")
async def synthesize(request: Request, body: SynthesizeRequest) -> Response:
    await _require_lease(request)
    settings = request.app.state.settings
    if is_lite_mode(settings):
        raise HTTPException(status_code=503, detail="轻量模式已禁用语音合成")
    stack = _stack(request)
    if not stack.synthesizer.available:
        raise HTTPException(status_code=503, detail="语音合成未配置：请先配置语音供应商")

    # 进入说话状态：TTS 播放期间挂件为 speaking
    await _publish(request, "conversation.response", {"message": body.text})
    try:
        audio = await stack.synthesizer.synthesize(body.text, body.params)
    except SpeechUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SpeechProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    media_type = "audio/wav"
    if audio.format == "mp3":
        media_type = "audio/mpeg"
    elif audio.format == "pcm":
        media_type = "audio/pcm"
    return Response(
        content=audio.data,
        media_type=media_type,
        headers={
            "X-Speech-Format": audio.format,
            "X-Speech-Sample-Rate": str(audio.sample_rate),
            "Cache-Control": "no-store",
        },
    )
