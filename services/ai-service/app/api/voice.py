"""语音接口：状态查询 / 识别 / 合成。

- 识别：整句 WAV（16k 单声道）→ 文本；文本走现有 /api/chat/stream。
- 合成：文本 → 音频字节；前端负责播放与按钮打断（barge-in 升级位）。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
import asyncio
import json
from pydantic import BaseModel, Field

from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.voice import VoiceParams

from app.config import is_lite_mode, resolve_tts_provider
from app.speech.base import (
    SpeechProviderError,
    SpeechStack,
    SpeechUnavailable,
)
from app.speech.activation import build_wake_texts, classify_intent
from app.speech.factory import build_tts_synthesizer, stack_status
from app.model_profiles import find_model_profile, load_model_profiles

router = APIRouter(prefix="/api/voice", tags=["voice"])
_VOICE_CLIENTS = {"web", "widget"}


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    params: VoiceParams | None = None
    conversation_id: str | None = None

    model_config = {"extra": "forbid"}


class PreviewRequest(BaseModel):
    """试听请求：字段缺省时按「指定档案 → 当前生效配置」兜底。"""

    profile_id: str | None = None
    provider: str | None = None
    base_url: str = ""
    model: str = ""
    voice: str = ""
    api_key: str | None = None      # 前端只在新填未保存时提交
    text: str | None = None

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


@router.get("/voices")
async def list_tts_voices(request: Request, profile_id: str | None = None) -> dict:
    """列出语音合成供应商的可用音色，供设置页与角色卡绑定选择。

    - 不传 `profile_id`：按当前生效的语音合成配置取列表。
    - 传 `profile_id`：按该「模型档案」取列表，便于设置页保存后立即试听选音色。

    只读查询，不占用语音租约；供应商不支持自动获取时返回空列表 + reason，
    由前端回退为手填音色 ID。
    """
    settings = request.app.state.settings
    stack = _stack(request)
    provider = stack.synthesizer.name
    model = stack.tts_model
    current = stack.tts_voice
    synthesizer = stack.synthesizer

    if profile_id:
        profile = find_model_profile(load_model_profiles(settings.repo_root), profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="模型档案不存在")
        if profile.category != "tts":
            raise HTTPException(status_code=400, detail="该模型档案不是语音合成模型")
        provider = profile.provider
        model = profile.model
        current = profile.voice
        synthesizer = build_tts_synthesizer(
            profile.provider,
            api_key=profile.api_key or "",
            base_url=profile.base_url,
            model=profile.model,
            voice=profile.voice,
            fmt=settings.tts_format,
            sample_rate=settings.tts_sample_rate,
            reason=f"{profile.provider} 语音合成未配置",
        )

    payload: dict = {
        "provider": provider,
        "model": model,
        "current": current,
        "available": synthesizer.available,
        "voices": [],
        "reason": None,
    }
    if is_lite_mode(settings):
        payload["available"] = False
        payload["reason"] = "轻量模式已禁用语音合成"
        return payload
    if not synthesizer.available:
        payload["reason"] = "语音合成未配置：请先在设置页配置语音合成模型"
        return payload
    try:
        voices = await synthesizer.list_voices()
    except SpeechUnavailable as exc:
        payload["reason"] = str(exc)
        return payload
    except SpeechProviderError as exc:
        payload["reason"] = str(exc)
        return payload

    payload["voices"] = [voice.as_dict() for voice in voices]
    if not voices:
        payload["reason"] = "该供应商未提供音色列表接口，请手动填写音色 ID"
    return payload


_PREVIEW_TEXT = "你好，我是你的桌面助理，很高兴见到你。"
_KEY_REQUIRED = {"minimax", "dashscope"}
_SETTINGS_KEYS = {
    "minimax": lambda settings: settings.minimax_api_key or "",
    "dashscope": lambda settings: settings.dashscope_api_key or "",
    "openai_compatible": lambda settings: settings.tts_api_key or "",
}


def _settings_key(settings, provider: str) -> str:
    lookup = _SETTINGS_KEYS.get(provider)
    return lookup(settings) if lookup else ""


@router.post("/preview")
async def preview_voice(request: Request, body: PreviewRequest) -> Response:
    """用指定音色合成一句样音，供设置页/角色卡试听。

    只读试听：不占语音租约、不推送挂件状态，失败直接把原因给前端。
    供应商与密钥的取值顺序：请求显式传入 → 指定模型档案 → 当前生效配置。
    """
    settings = request.app.state.settings
    if is_lite_mode(settings):
        raise HTTPException(status_code=503, detail="轻量模式已禁用语音合成")

    profile = None
    if body.profile_id:
        profile = find_model_profile(load_model_profiles(settings.repo_root), body.profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="模型档案不存在")
        if profile.category != "tts":
            raise HTTPException(status_code=400, detail="该模型档案不是语音合成模型")

    fallback_provider, _reason = resolve_tts_provider(settings)
    provider = (body.provider or (profile.provider if profile else "") or fallback_provider).strip()
    base_url = body.base_url or (profile.base_url if profile else "") or settings.tts_base_url
    model = body.model or (profile.model if profile else "") or settings.tts_model
    voice = body.voice or (profile.voice if profile else "") or settings.tts_voice
    api_key = (
        (body.api_key or "").strip()
        or ((profile.api_key or "") if profile else "")
        or _settings_key(settings, provider)
    )

    if provider == "disabled":
        raise HTTPException(status_code=503, detail="语音合成未配置：请先配置语音供应商")
    if provider == "openai_compatible" and not base_url:
        raise HTTPException(status_code=400, detail="请先填写语音合成服务地址（Base URL）")
    # 自建/本地 OpenAI 兼容服务常常不需要鉴权，只有云供应商强制要求密钥。
    if not api_key and provider in _KEY_REQUIRED:
        raise HTTPException(status_code=400, detail=f"未配置 {provider} 的 API Key，请先填写并保存")

    synthesizer = build_tts_synthesizer(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        voice=voice,
        fmt=settings.tts_format,
        sample_rate=settings.tts_sample_rate,
    )
    if not synthesizer.available:
        raise HTTPException(status_code=503, detail="语音合成未配置：请先配置语音供应商")

    try:
        audio = await synthesizer.synthesize((body.text or "").strip() or _PREVIEW_TEXT)
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

@router.post("/synthesize/stream")
async def synthesize_stream(request: Request, body: SynthesizeRequest):
    """流式合成：SSE 逐句推送音频 chunk（每行一个完整块 JSON+base64）。

    barge-in 时前端关闭 fetch 即中断后续推送。
    """
    await _require_lease(request)
    settings = request.app.state.settings
    if is_lite_mode(settings):
        raise HTTPException(status_code=503, detail="轻量模式已禁用语音合成")
    stack = _stack(request)
    if not stack.synthesizer.available:
        raise HTTPException(status_code=503, detail="语音合成未配置：请先配置语音供应商")

    await _publish(request, "conversation.response", {"message": body.text})

    import base64 as _b64

    async def _chunks():
        idx = 0
        try:
            async for audio in stack.synthesizer.synthesize_stream(body.text, body.params):
                yield (
                    "data: "
                    + json.dumps({
                        "index": idx,
                        "format": audio.format,
                        "sample_rate": audio.sample_rate,
                        "audio": _b64.b64encode(audio.data).decode("ascii"),
                    })
                    + "\n\n"
                )
                idx += 1
            yield "data: " + json.dumps({"done": True, "total_chunks": idx}) + "\n\n"
        except SpeechUnavailable as exc:
            yield "data: " + json.dumps({"error": str(exc), "status": 503}) + "\n\n"
        except SpeechProviderError as exc:
            yield "data: " + json.dumps({"error": str(exc), "status": 502}) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"error": str(exc), "status": 500}) + "\n\n"

    return StreamingResponse(
        _chunks(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )

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
