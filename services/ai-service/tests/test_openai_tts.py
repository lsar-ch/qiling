"""通用 OpenAI 兼容 TTS 适配器：音色列表探测与合成（不联网）。"""

from __future__ import annotations

import asyncio

import pytest

from app.speech import openai_tts
from app.speech.openai_tts import OpenAICompatibleSynthesizer

BASE = "https://tts.example.com/v1"


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = "" if payload is None else str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeAsyncClient:
    """按 URL 返回预设响应，并记录请求。"""

    routes: dict = {}
    calls: list = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url, headers=None):
        type(self).calls.append(("GET", url))
        return type(self).routes.get(url) or _FakeResponse(404)

    async def post(self, url, json=None, headers=None):
        type(self).calls.append(("POST", url, json))
        return type(self).routes.get(url) or _FakeResponse(404)


@pytest.fixture
def fake_http(monkeypatch):
    _FakeAsyncClient.routes = {}
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(openai_tts.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _synth(base_url: str = BASE) -> OpenAICompatibleSynthesizer:
    return OpenAICompatibleSynthesizer(base_url=base_url, api_key="k", model="m", voice="v")


def test_list_voices_prefers_audio_voices_endpoint(fake_http) -> None:
    async def scenario() -> None:
        fake_http.routes[f"{BASE}/audio/voices"] = _FakeResponse(
            200, {"voices": ["alloy", {"id": "zh_female", "name": "中文女声"}]}
        )
        voices = await _synth().list_voices()
        assert [v.id for v in voices] == ["alloy", "zh_female"]
        assert voices[1].name == "中文女声"
        assert [call[1] for call in fake_http.calls] == [f"{BASE}/audio/voices"]

    asyncio.run(scenario())


def test_list_voices_falls_back_to_models(fake_http) -> None:
    async def scenario() -> None:
        fake_http.routes[f"{BASE}/audio/voices"] = _FakeResponse(404)
        fake_http.routes[f"{BASE}/models"] = _FakeResponse(
            200, {"data": [{"id": "tts-1"}, {"id": "kokoro"}]}
        )
        voices = await _synth().list_voices()
        assert [v.id for v in voices] == ["tts-1", "kokoro"]

    asyncio.run(scenario())


def test_list_voices_returns_empty_when_provider_has_no_listing(fake_http) -> None:
    async def scenario() -> None:
        fake_http.routes[f"{BASE}/audio/voices"] = _FakeResponse(404)
        fake_http.routes[f"{BASE}/models"] = _FakeResponse(404)
        assert await _synth().list_voices() == []

    asyncio.run(scenario())


def test_synthesize_posts_openai_speech_payload(fake_http) -> None:
    async def scenario() -> None:
        fake_http.routes[f"{BASE}/audio/speech"] = _FakeResponse(200, content=b"RIFFfake-audio")
        result = await _synth().synthesize("你好")
        assert result.data == b"RIFFfake-audio"
        method, url, payload = fake_http.calls[-1]
        assert method == "POST"
        assert url == f"{BASE}/audio/speech"
        assert payload["input"] == "你好"
        assert payload["voice"] == "v"

    asyncio.run(scenario())


def test_disabled_without_base_url() -> None:
    assert OpenAICompatibleSynthesizer(base_url="").available is False
