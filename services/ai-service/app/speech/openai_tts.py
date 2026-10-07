"""通用 OpenAI 兼容 TTS 适配器（覆盖「其他供应商 / 语音大模型」接入）。

约定：
- 合成：`POST {base_url}/audio/speech`（OpenAI 官方规范，多数自建/聚合网关兼容）。
- 音色列表：`GET {base_url}/audio/voices`，失败再退 `GET {base_url}/models`。
  该列表端点不是 OpenAI 官方规范，但在 Kokoro-FastAPI / openedai-speech / LocalAI
  一类自建服务上是事实约定；两者都拿不到时返回空列表，由前端回退手填。

供应商没有统一列表接口是常态，所以这里的原则是「能自动拿就自动拿，拿不到说清楚」。
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

_PASSTHROUGH_FORMATS = {"mp3", "wav", "opus", "aac", "flac", "pcm"}
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


class OpenAICompatibleSynthesizer(SpeechSynthesizer):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "",
        voice: str = "",
        fmt: str = "mp3",
        sample_rate: int = 24000,
        defaults: VoiceParams | None = None,
    ) -> None:
        self._base_url = (base_url or "").strip()
        self._api_key = api_key
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
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def synthesize(self, text: str, params: VoiceParams | None = None) -> AudioResult:
        if not self._base_url:
            raise SpeechProviderError("未配置语音合成服务地址（Base URL）")
        merged = params or self._defaults
        payload: dict = {
            "model": self._model,
            "input": text,
            "voice": merged.voice or self._voice,
            "response_format": self._fmt,
            "speed": max(0.25, min(4.0, merged.speed)),
        }
        if not payload["voice"]:
            payload.pop("voice")
        if not payload["model"]:
            payload.pop("model")

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    self._url("audio/speech"),
                    json=payload,
                    headers=self._headers(),
                )
            if resp.status_code >= 400:
                raise SpeechProviderError(
                    f"语音合成失败：HTTP {resp.status_code} {resp.text[:180]}"
                )
            data = resp.content
        except SpeechProviderError:
            raise
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"语音合成网络错误：{exc}") from exc
        if not data:
            raise SpeechProviderError("语音合成返回空音频")
        return AudioResult(data=data, format=self._fmt, sample_rate=self._sample_rate)

    async def list_voices(self) -> list[VoiceOption]:
        """先试 /audio/voices，再退 /models；都失败返回空列表。"""
        if not self._base_url:
            raise SpeechProviderError("未配置语音合成服务地址（Base URL）")

        headers = self._headers()
        headers.pop("Content-Type", None)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                voices = await self._try_audio_voices(client, headers)
                if voices:
                    return voices
                return await self._try_models(client, headers)
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"获取音色列表网络错误：{exc}") from exc

    async def _try_audio_voices(
        self, client: httpx.AsyncClient, headers: dict[str, str]
    ) -> list[VoiceOption]:
        resp = await client.get(self._url("audio/voices"), headers=headers)
        if resp.status_code >= 400:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []

        raw = data.get("voices") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return []
        voices: list[VoiceOption] = []
        for item in raw:
            if isinstance(item, str):
                voice_id, name = item.strip(), ""
            elif isinstance(item, dict):
                voice_id = str(
                    item.get("id") or item.get("voice_id") or item.get("name") or ""
                ).strip()
                name = str(item.get("name") or item.get("voice_name") or "").strip()
            else:
                continue
            if voice_id:
                voices.append(VoiceOption(id=voice_id, name=name or voice_id, kind="system"))
        return voices

    async def _try_models(
        self, client: httpx.AsyncClient, headers: dict[str, str]
    ) -> list[VoiceOption]:
        resp = await client.get(self._url("models"), headers=headers)
        if resp.status_code >= 400:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        raw = data.get("data") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return []
        voices: list[VoiceOption] = []
        for item in raw:
            voice_id = ""
            if isinstance(item, dict):
                voice_id = str(item.get("id") or "").strip()
            elif isinstance(item, str):
                voice_id = item.strip()
            if voice_id:
                voices.append(VoiceOption(id=voice_id, kind="system"))
        return voices
