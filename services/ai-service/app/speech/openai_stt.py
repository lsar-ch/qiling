"""通用 OpenAI 兼容语音识别适配器（Whisper 类自建 / 聚合服务）。

约定：
- 识别：`POST {base_url}/audio/transcriptions`，multipart/form-data，
  字段 `file`（wav 字节）+ `model`，可选 `language`。这是 OpenAI 官方规范，
  Groq Whisper 与各家 Whisper 网关都兼容。
- 音色列表：识别器没有音色概念，沿用基类默认返回空列表。
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.speech.base import SpeechProviderError, SpeechRecognizer, SpeechUnavailable

_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


class OpenAICompatibleRecognizer(SpeechRecognizer):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "",
        sample_rate: int = 16000,
    ) -> None:
        self._base_url = (base_url or "").strip()
        self._api_key = api_key
        self._model = model
        self._sample_rate = sample_rate

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    def _url(self, path: str) -> str:
        return f"{self._base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        # multipart 的 Content-Type 由 httpx 带 boundary，这里只能补鉴权头。
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def recognize(self, wav_path: str, language: str = "zh") -> str:
        if not self._base_url:
            raise SpeechUnavailable("未配置语音识别服务地址（Base URL）")
        if not self._model:
            raise SpeechProviderError("未填写语音识别模型名称")
        try:
            audio = Path(wav_path).read_bytes()
        except OSError as exc:
            raise SpeechProviderError(f"语音识别读取音频失败：{exc}") from exc

        data: dict[str, str] = {"model": self._model}
        if language:
            data["language"] = language
        files = {"file": (Path(wav_path).name, audio, "audio/wav")}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    self._url("audio/transcriptions"),
                    data=data,
                    files=files,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise SpeechProviderError(f"语音识别网络错误：{exc}") from exc

        if response.status_code >= 400:
            raise SpeechProviderError(
                f"语音识别失败：HTTP {response.status_code} {response.text[:180]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpeechProviderError(f"语音识别响应异常：{exc}") from exc
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("text") or "").strip()
