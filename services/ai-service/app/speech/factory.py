"""根据配置构建语音识别/合成器；未配置时返回 disabled（带原因）。"""

from __future__ import annotations

from app.config import Settings, resolve_stt_provider, resolve_tts_provider
from app.speech.base import (
    DisabledRecognizer,
    DisabledSynthesizer,
    SpeechStack,
)
from app.speech.dashscope import DashScopeRecognizer, DashScopeSynthesizer
from app.speech.minimax import MiniMaxSynthesizer
from deskmate_contracts.voice import VoiceParams


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
        synthesizer = DashScopeSynthesizer(
            api_key=settings.dashscope_api_key or "",
            model=settings.tts_model,
            voice=settings.tts_voice,
            fmt=settings.tts_format,
            sample_rate=settings.tts_sample_rate,
            defaults=params,
        )
    elif tts_provider == "minimax":
        synthesizer = MiniMaxSynthesizer(
            api_key=settings.minimax_api_key or "",
            model=settings.tts_model,
            voice=settings.tts_voice,
            fmt=settings.tts_format,
            sample_rate=settings.tts_sample_rate,
            defaults=params,
        )
    else:
        synthesizer = DisabledSynthesizer(tts_reason or "语音合成不可用")
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
