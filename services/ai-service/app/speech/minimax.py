"""MiniMax 语音适配器（TTS，speech-2.8-hd）。

- 主声：系统预置音色（默认 `Chinese (Mandarin)_Soft_Girl`，用户 2026-09-04 拍板）。
- 克隆音：直接传 `voice_id`（经 voice_clone 注册，实测与预置音链路一致）。
- emotion：MiniMax 枚举参数；克隆音实测支持（happy 验证通过）。
- 不依赖官方 SDK，直接走 HTTP API（httpx，已在 requirements 中）。

key 来源：环境变量 MINIMAX_API_KEY（优先）或 config/settings.yaml voice.minimax.api_key，
由 app.config.load_settings() 统一读取；本模块不硬编码任何 key。
"""

from __future__ import annotations

import binascii

import httpx

from deskmate_contracts.voice import VoiceParams

from app.speech.base import (
    AudioResult,
    SpeechProviderError,
    SpeechSynthesizer,
)

API_BASE = "https://api.minimaxi.com/v1"

# MiniMax speech-2.8-hd 支持的 emotion 枚举
_EMOTIONS = {
    "happy",
    "sad",
    "angry",
    "fearful",
    "disgusted",
    "surprised",
    "calm",
    "fluent",
    "whisper",
}

# 情绪目录（config/voice_tone/catalog.yaml）标签 → MiniMax emotion 近似映射
_EMOTION_ALIAS = {
    "neutral": None,
    "playful": "happy",
    "gentle": "calm",
    "excited": "happy",
    "apologetic": "sad",
    "confirming": "calm",
}


def _resolve_emotion(emotion: str | None) -> str | None:
    if not emotion:
        return None
    value = emotion.strip().lower()
    if value in _EMOTIONS:
        return value
    return _EMOTION_ALIAS.get(value)


class MiniMaxSynthesizer(SpeechSynthesizer):
    name = "minimax"

    def __init__(
        self,
        api_key: str,
        model: str = "speech-2.8-hd",
        voice: str = "Chinese (Mandarin)_Soft_Girl",
        fmt: str = "mp3",
        sample_rate: int = 32000,
        defaults: VoiceParams | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._fmt = fmt
        self._sample_rate = sample_rate
        self._defaults = defaults or VoiceParams()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def synthesize(self, text: str, params: VoiceParams | None = None) -> AudioResult:
        if not self._api_key:
            raise SpeechProviderError("未配置 MINIMAX_API_KEY")
        if self._fmt != "mp3":
            raise SpeechProviderError(
                f"MiniMax 适配器当前仅支持 mp3 输出（收到 {self._fmt}）；请用 wav/pcm 时另选供应商"
            )

        merged = params or self._defaults
        voice = merged.voice or self._voice
        emotion = _resolve_emotion(merged.emotion)
        voice_setting = {
            "voice_id": voice,
            "speed": max(0.5, min(2.0, merged.speed)),
            # MiniMax vol 范围 0~10（默认 1.0）；归一化 volume 1.0 → 1.0，待听感校准
            "vol": max(0.0, min(10.0, merged.volume)),
            # MiniMax pitch 为半音偏移（默认 0）；归一化 pitch 1.0 → 0
            "pitch": int(max(-12, min(12, round((merged.pitch - 1.0) * 12)))),
        }
        if emotion:
            voice_setting["emotion"] = emotion

        body = {
            "model": self._model,
            "text": text,
            "voice_setting": voice_setting,
            "audio_setting": {
                "format": "mp3",
                "sample_rate": self._sample_rate,
                "bitrate": 128000,
                "channel": 1,
            },
            "output_format": "hex",
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{API_BASE}/t2a_v2", json=body, headers=headers)
            data = resp.json()
            base = data.get("base_resp", {}) or {}
            if base.get("status_code") not in (0, None):
                raise SpeechProviderError(
                    f"MiniMax 语音合成失败：{base.get('status_code')} {base.get('status_msg')}"
                )
            audio_hex = (data.get("data") or {}).get("audio", "")
            if not audio_hex:
                raise SpeechProviderError("MiniMax 语音合成返回空音频")
        except SpeechProviderError:
            raise
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"MiniMax 语音合成网络错误：{exc}") from exc
        except ValueError as exc:
            raise SpeechProviderError(f"MiniMax 语音合成响应异常：{exc}") from exc

        return AudioResult(
            data=binascii.unhexlify(audio_hex),
            format="mp3",
            sample_rate=self._sample_rate,
        )
