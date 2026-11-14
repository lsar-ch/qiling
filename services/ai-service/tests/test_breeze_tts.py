"""Breeze TTS 2 适配器：请求形状、参数映射、音色列表解析（不联网）。"""

from __future__ import annotations

import asyncio

import pytest

from qiling_contracts.voice import VoiceParams

from app.speech import breeze
from app.speech.base import SpeechProviderError
from app.speech.breeze import BreezeSynthesizer

BASE = "https://api.breeze.blue/v1"
VOICE = "voc_abc123"
SYNTH = f"{BASE}/text-to-speech/{VOICE}"


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, content: bytes = b"\x01\x02") -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
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

    async def post(self, url, json=None, headers=None):
        type(self).calls.append(("POST", url, json, headers))
        return type(self).routes.get(url) or _FakeResponse(404)

    async def get(self, url, headers=None):
        type(self).calls.append(("GET", url, None, headers))
        return type(self).routes.get(url) or _FakeResponse(404)


@pytest.fixture
def fake_http(monkeypatch):
    _FakeAsyncClient.routes = {}
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(breeze.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def test_synthesize_maps_contract_params(fake_http):
    fake_http.routes[SYNTH] = _FakeResponse(content=b"\xff\xfb")
    synthesizer = BreezeSynthesizer(
        api_key="brz_key",
        base_url=BASE,
        model="breeze-tts-2",
        voice=VOICE,
        fmt="mp3",
        defaults=VoiceParams(speed=1.2, volume=0.8, instruction="语气温柔", language="zh"),
    )

    audio = asyncio.run(synthesizer.synthesize("你好"))
    assert audio.data == b"\xff\xfb"
    assert audio.format == "mp3"

    method, url, payload, headers = fake_http.calls[0]
    assert (method, url) == ("POST", SYNTH)
    # Breeze 用 xi-api-key 头鉴权，不是 Authorization Bearer
    assert headers["xi-api-key"] == "brz_key"
    assert "Authorization" not in headers
    assert payload["text"] == "你好"
    assert payload["model_id"] == "breeze-tts-2"
    assert payload["language_code"] == "zh"
    assert payload["instructions"] == "语气温柔"
    assert payload["voice_settings"] == {"speed": 1.2, "volume": 0.8, "guidance_scale": 4.0}


def test_synthesize_omits_guidance_scale_without_instruction(fake_http):
    fake_http.routes[SYNTH] = _FakeResponse()
    synthesizer = BreezeSynthesizer(
        api_key="k", base_url=BASE, voice=VOICE, defaults=VoiceParams()
    )
    asyncio.run(synthesizer.synthesize("你好"))

    payload = fake_http.calls[0][2]
    assert "instructions" not in payload
    assert payload["voice_settings"] == {"speed": 1.0, "volume": 1.0}


def test_synthesize_requires_voice_id(fake_http):
    synthesizer = BreezeSynthesizer(api_key="k", base_url=BASE, voice="")
    with pytest.raises(SpeechProviderError):
        asyncio.run(synthesizer.synthesize("你好"))


def test_blank_base_url_falls_back_to_official_endpoint(fake_http):
    fallback = f"{breeze.DEFAULT_BASE_URL}/text-to-speech/{VOICE}"
    fake_http.routes[fallback] = _FakeResponse()
    synthesizer = BreezeSynthesizer(api_key="k", base_url="", voice=VOICE)
    asyncio.run(synthesizer.synthesize("你好"))
    assert fake_http.calls[0][1] == fallback


def test_synthesize_surfaces_error_detail(fake_http):
    fake_http.routes[SYNTH] = _FakeResponse(401, {"code": "unauthorized", "detail": "invalid key"})
    synthesizer = BreezeSynthesizer(api_key="k", base_url=BASE, voice=VOICE)
    with pytest.raises(SpeechProviderError, match="invalid key"):
        asyncio.run(synthesizer.synthesize("你好"))


def test_list_voices_parses_voice_id_and_origin(fake_http):
    fake_http.routes[f"{BASE}/voices"] = _FakeResponse(
        payload={
            "voices": [
                {"voice_id": "voc_a", "name": "小岚", "origin": "designed"},
                {"voice_id": "voc_b", "name": "", "origin": "cloned"},
                {"name": "没有 id"},
            ],
            "total": 3,
        }
    )
    voices = asyncio.run(BreezeSynthesizer(api_key="k", base_url=BASE).list_voices())
    assert [(voice.id, voice.name, voice.kind) for voice in voices] == [
        ("voc_a", "小岚", "system"),
        ("voc_b", "voc_b", "cloned"),
    ]


def test_list_voices_surfaces_http_error(fake_http):
    fake_http.routes[f"{BASE}/voices"] = _FakeResponse(401, {"detail": "bad key"})
    with pytest.raises(SpeechProviderError, match="401"):
        asyncio.run(BreezeSynthesizer(api_key="k", base_url=BASE).list_voices())
