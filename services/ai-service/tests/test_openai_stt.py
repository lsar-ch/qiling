"""通用 OpenAI 兼容语音识别适配器：请求形状与错误路径（不联网）。"""

from __future__ import annotations

import asyncio
import wave

import pytest

from app.speech import openai_stt
from app.speech.base import SpeechProviderError, SpeechUnavailable
from app.speech.openai_stt import OpenAICompatibleRecognizer

BASE = "https://asr.example.com/v1"
ENDPOINT = f"{BASE}/audio/transcriptions"


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b""
        self.text = "" if payload is None else str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeAsyncClient:
    routes: dict = {}
    calls: list = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, data=None, files=None, headers=None):
        type(self).calls.append((url, data, files, headers))
        return type(self).routes.get(url) or _FakeResponse(404)


@pytest.fixture
def fake_http(monkeypatch):
    _FakeAsyncClient.routes = {}
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(openai_stt.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _wav(tmp_path) -> str:
    path = tmp_path / "in.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 800)
    return str(path)


def test_recognize_posts_multipart_with_bearer_key(fake_http, tmp_path):
    fake_http.routes[ENDPOINT] = _FakeResponse(payload={"text": "你好"})
    recognizer = OpenAICompatibleRecognizer(BASE, api_key="k", model="whisper-large-v3-turbo")

    assert asyncio.run(recognizer.recognize(_wav(tmp_path))) == "你好"

    url, data, files, headers = fake_http.calls[0]
    assert url == ENDPOINT
    assert data == {"model": "whisper-large-v3-turbo", "language": "zh"}
    assert files["file"][2] == "audio/wav"
    assert headers["Authorization"] == "Bearer k"
    # multipart 的 Content-Type 由 httpx 带 boundary，适配器不能写死
    assert "Content-Type" not in headers


def test_recognize_surfaces_http_error(fake_http, tmp_path):
    fake_http.routes[ENDPOINT] = _FakeResponse(401, {"error": "bad key"})
    recognizer = OpenAICompatibleRecognizer(BASE, api_key="k", model="whisper-large-v3-turbo")
    with pytest.raises(SpeechProviderError, match="401"):
        asyncio.run(recognizer.recognize(_wav(tmp_path)))


def test_recognize_requires_base_url_then_model(tmp_path):
    no_base = OpenAICompatibleRecognizer("", api_key="k", model="m")
    with pytest.raises(SpeechUnavailable):
        asyncio.run(no_base.recognize(_wav(tmp_path)))

    no_model = OpenAICompatibleRecognizer(BASE, api_key="k", model="")
    with pytest.raises(SpeechProviderError):
        asyncio.run(no_model.recognize(_wav(tmp_path)))


def test_available_only_needs_base_url():
    assert OpenAICompatibleRecognizer(BASE).available is True
    assert OpenAICompatibleRecognizer("  ").available is False
