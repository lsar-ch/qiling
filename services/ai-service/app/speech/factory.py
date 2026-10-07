"""根据配置构建语音识别/合成器；未配置时返回 disabled（带原因）。"""

from __future__ import annotations

from app.config import Settings, resolve_stt_provider, resolve_tts_provider
from app.speech.base import (
    DisabledRecognizer,
    DisabledSynthesizer,
    SpeechStack,
)
from app.speech.base import SpeechSynthesizer
from app.speech.dashscope import DashScopeRecognizer, DashScopeSynthesizer
from app.speech.minimax import MiniMaxSynthesizer
from app.speech.openai_tts import OpenAICompatibleSynthesizer
from qiling_contracts.voice import VoiceParams


def build_tts_synthesizer(
    provider: str,
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    voice: str = "",
    fmt: str = "wav",
    sample_rate: int = 24000,
    defaults: VoiceParams | None = None,
    reason: str | None = None,
) -> SpeechSynthesizer:
    """按供应商构造合成器；未知/未配置时返回 disabled。

    设置页按「模型档案」试听音色、运行时按生效配置合成，都走这一个入口，
    避免两处各自判断供应商。
    """
    if provider == "dashscope":
        return DashScopeSynthesizer(
            api_key=api_key,
            model=model or "cosyvoice-v2",
            voice=voice,
            fmt=fmt,
            sample_rate=sample_rate,
            defaults=defaults,
        )
    if provider == "minimax":
        return MiniMaxSynthesizer(
            api_key=api_key,
            model=model or "speech-2.8-hd",
            voice=voice,
            fmt=fmt,
            sample_rate=sample_rate,
            defaults=defaults,
        )
    if provider == "openai_compatible":
        return OpenAICompatibleSynthesizer(
            base_url=base_url,
            api_key=api_key,
            model=model,
            voice=voice,
            fmt=fmt,
            sample_rate=sample_rate,
            defaults=defaults,
        )
    return DisabledSynthesizer(reason or "语音合成不可用")


def build_speech_stack(settings: Settings) -> SpeechStack:
    stt_provider, stt_reason = resolve_stt_provider(settings)
    tts_provider, tts_reason = resolve_tts_provider(settings)

    if stt_provider == "dashscope":
        recognizer = DashScopeRecognizer(
            api_key=settings.dashscope_api_key or "",
            model=settings.stt_model,
            sample_rate=settings.stt_sample_rate,
        )
    else:
        recognizer = DisabledRecognizer(stt_reason or "语音识别不可用")

    params = VoiceParams(
        speed=settings.voice_speed,
        pitch=settings.voice_pitch,
        volume=settings.voice_volume,
        emotion=settings.voice_emotion,
        instruction=settings.voice_instruction,
        language=settings.stt_language,
    )
    if tts_provider == "dashscope":
        api_key, base_url = settings.dashscope_api_key or "", ""
    elif tts_provider == "minimax":
        api_key, base_url = settings.minimax_api_key or "", ""
    elif tts_provider == "openai_compatible":
        api_key, base_url = settings.tts_api_key, settings.tts_base_url
    else:
        api_key, base_url = "", ""

    synthesizer = build_tts_synthesizer(
        tts_provider,
        api_key=api_key,
        base_url=base_url,
        model=settings.tts_model,
        voice=settings.tts_voice,
        fmt=settings.tts_format,
        sample_rate=settings.tts_sample_rate,
        defaults=params,
        reason=tts_reason,
    )
    if not synthesizer.available:
        params = None

    return SpeechStack(
        recognizer=recognizer,
        synthesizer=synthesizer,
        stt_model=settings.stt_model,
        tts_model=settings.tts_model,
        tts_voice=settings.tts_voice,
        tts_format=settings.tts_format,
        tts_sample_rate=settings.tts_sample_rate,
        params=params,
    )


def stack_status(stack: SpeechStack) -> dict:
    """供 GET /api/voice/status 使用的结构化描述。"""
    return {
        "enabled": stack.voice_enabled,
        "stt": {
            "provider": stack.recognizer.name,
            "model": stack.stt_model,
            "available": stack.recognizer.available,
        },
        "tts": {
            "provider": stack.synthesizer.name,
            "model": stack.tts_model,
            "voice": stack.tts_voice,
            "format": stack.tts_format,
            "sample_rate": stack.tts_sample_rate,
            "available": stack.synthesizer.available,
        },
        "params": stack.params.model_dump() if stack.params else None,
        "interruption_enabled": True,  # 默认支持按钮打断，后续接设置项
    }
