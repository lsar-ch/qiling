"""Breeze TTS 2（BreezeBlue 托管 API）语音合成适配器。

协议（https://docs.breezeblue.ai/）：
- 合成：`POST {base_url}/text-to-speech/{voice_id}`，JSON body，返回二进制音频。
- 音色：`GET {base_url}/voices`，分页返回 `{voices: [{voice_id, name, origin, ...}]}`。
- 鉴权走 `xi-api-key` 头，不是 Authorization Bearer。

参数映射：`instruction` → `instructions`；`speed` / `volume` 与契约范围一致；
契约里的 `pitch` 该协议没有对应字段（风格由 instructions 表达），忽略。
"""

from __future__ import annotations

import httpx

from qiling_contracts.voice import VoiceParams

from app.speech.base import (
    AudioResult,
    SpeechProviderError,
    SpeechSynthesizer,
    VoiceOption,
)

DEFAULT_BASE_URL = "https://api.breeze.blue/v1"
DEFAULT_MODEL = "breeze-tts-2"
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
_PASSTHROUGH_FORMATS = {"mp3", "wav", "flac", "pcm", "aac", "opus"}


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:180]
    if isinstance(payload, dict):
        detail = str(payload.get("detail") or payload.get("error") or "").strip()
        if detail:
            return detail[:180]
    return response.text[:180]


class BreezeSynthesizer(SpeechSynthesizer):
    name = "breeze"

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model: str = "",
        voice: str = "",
        fmt: str = "mp3",
        sample_rate: int = 24000,
        defaults: VoiceParams | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).strip()
        self._model = model
        self._voice = voice
        self._fmt = fmt if fmt in _PASSTHROUGH_FORMATS else "mp3"
        self._sample_rate = sample_rate
        self._defaults = defaults or VoiceParams()

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    def _url(self, path: str) -> str:
        return f"{self._base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["xi-api-key"] = self._api_key
        return headers

    async def synthesize(self, text: str, params: VoiceParams | None = None) -> AudioResult:
        if not self._base_url:
            raise SpeechProviderError("未配置 Breeze 服务地址")
        merged = params or self._defaults
        voice = (merged.voice or self._voice).strip()
        if not voice:
            raise SpeechProviderError("未选择 Breeze 音色（voice_id）")

        payload: dict = {"text": text}
        if self._model:
            payload["model_id"] = self._model
        if len(merged.language or "") == 2:
            payload["language_code"] = merged.language
        instructions = (merged.instruction or "").strip()
        if instructions:
            payload["instructions"] = instructions
        # 官方建议带 instructions 时 guidance_scale 取 4，不带则用协议默认 1。
        voice_settings: dict = {
            "speed": max(0.5, min(2.0, merged.speed)),
            "volume": max(0.01, min(2.0, merged.volume)),
        }
        if instructions:
            voice_settings["guidance_scale"] = 4.0
        payload["voice_settings"] = voice_settings

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    self._url(f"text-to-speech/{voice}"),
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"Breeze 语音合成网络错误：{exc}") from exc

        if response.status_code >= 400:
            raise SpeechProviderError(
                f"Breeze 语音合成失败：HTTP {response.status_code} {_error_detail(response)}"
            )
        if not response.content:
            raise SpeechProviderError("Breeze 语音合成返回空音频")
        return AudioResult(
            data=response.content,
            format=self._fmt,
            sample_rate=self._sample_rate,
        )

    async def list_voices(self) -> list[VoiceOption]:
        if not self._base_url:
            raise SpeechProviderError("未配置 Breeze 服务地址")
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["xi-api-key"] = self._api_key
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                response = await client.get(self._url("voices"), headers=headers)
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"获取 Breeze 音色列表网络错误：{exc}") from exc
        if response.status_code >= 400:
            raise SpeechProviderError(
                f"获取 Breeze 音色列表失败：HTTP {response.status_code} {_error_detail(response)}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise SpeechProviderError(f"获取 Breeze 音色列表响应异常：{exc}") from exc

        raw = data.get("voices") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return []
        voices: list[VoiceOption] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("voice_id") or item.get("id") or "").strip()
            if not voice_id:
                continue
            origin = str(item.get("origin") or "").strip().lower()
            voices.append(
                VoiceOption(
                    id=voice_id,
                    name=str(item.get("name") or "").strip() or voice_id,
                    kind="cloned" if origin == "cloned" else "system",
                )
            )
        return voices
