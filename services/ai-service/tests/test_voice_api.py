"""Step 4：语音 API（状态/识别/合成）与挂件状态联动。

测试全部使用 mock provider，不打真实云网络。
"""

from __future__ import annotations

import wave

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.speech.base import (
    AudioResult,
    SpeechRecognizer,
    SpeechStack,
    SpeechSynthesizer,
    SpeechUnavailable,
)
from deskmate_contracts.voice import VoiceParams


class FakeRecognizer(SpeechRecognizer):
    name = "fake-stt"

    def __init__(self, text: str = "今天天气怎么样") -> None:
        self._text = text

    async def recognize(self, wav_path: str, language: str = "zh") -> str:
        with wave.open(wav_path, "rb") as f:  # 校验传入的是可读 wav
            assert f.getnframes() > 0
        return self._text


class FakeSynthesizer(SpeechSynthesizer):
    name = "fake-tts"

    async def synthesize(self, text: str, params: VoiceParams | None = None) -> AudioResult:
        return AudioResult(data=f"FAKE-AUDIO:{text}".encode(), format="wav", sample_rate=24000)


class BrokenRecognizer(SpeechRecognizer):
    name = "broken-stt"

    async def recognize(self, wav_path: str, language: str = "zh") -> str:
        raise SpeechUnavailable("供应商余额不足（测试）")


def _wav_bytes(text: str = "x") -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes((text * 4000).encode())
    return buf.getvalue()


def _client(recognizer: SpeechRecognizer | None = None, synthesizer: SpeechSynthesizer | None = None):
    if recognizer is None:
        recognizer = FakeRecognizer()
    if synthesizer is None:
        synthesizer = FakeSynthesizer()
    stack = SpeechStack(
        recognizer=recognizer,
        synthesizer=synthesizer,
        stt_model="paraformer-realtime-v2",
        tts_model="cosyvoice-v2",
        tts_voice="longxiaochun_v2",
        tts_format="wav",
        tts_sample_rate=24000,
        params=VoiceParams(),
    )
    client = TestClient(create_app(load_settings(), speech=stack))
    client.post("/api/voice/lease", headers={"X-Voice-Client": "widget"})
    return client


def test_status_reports_providers() -> None:
    with _client() as client:
        body = client.get("/api/voice/status").json()
        assert body["enabled"] is True
        assert body["stt"]["provider"] == "fake-stt"
        assert body["tts"]["provider"] == "fake-tts"
        assert body["tts"]["voice"] == "longxiaochun_v2"


def test_recognize_returns_text() -> None:
    with _client() as client:
        resp = client.post(
            "/api/voice/recognize?language=zh",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav", "X-Voice-Client": "widget"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "今天天气怎么样"
        # 识别开始 → 挂件进入 listening
        state = client.get("/api/widget/state").json()["widget_state"]
        assert state["state"] == "listening"


def test_recognize_rejects_non_wav() -> None:
    with _client() as client:
        resp = client.post(
            "/api/voice/recognize",
            content=b"not-a-riff-file-xxxx",
            headers={"Content-Type": "audio/wav", "X-Voice-Client": "widget"},
        )
        assert resp.status_code == 422


def test_synthesize_returns_audio_and_drives_widget() -> None:
    with _client() as client:
        resp = client.post(
            "/api/voice/synthesize",
            json={"text": "你好呀，我是 DeskMate", "params": {"voice": "longxiaoxia_v2"}},
            headers={"X-Voice-Client": "widget"},
        )
        assert resp.status_code == 200
        assert resp.content == ("FAKE-AUDIO:" + "你好呀，我是 DeskMate").encode("utf-8")
        assert resp.headers["content-type"].startswith("audio/wav")
        assert resp.headers["x-speech-format"] == "wav"
        # 合成（播报）期间 → speaking
        state = client.get("/api/widget/state").json()["widget_state"]
        assert state["state"] == "speaking"

        # 播报结束 → 空闲
        publish = client.post(
            "/api/events/publish",
            json={"event_type": "speech.stopped", "source": "speech", "payload": {}},
        )
        assert publish.status_code == 200
        state = client.get("/api/widget/state").json()["widget_state"]
        assert state["state"] == "idle"


def test_disabled_without_cloud_key() -> None:
    # 显式清空 key：模拟“未配置云语音”场景（本地 .env 可能已配）
    settings = load_settings()
    settings.dashscope_api_key = None
    settings.minimax_api_key = None
    settings.volc_app_id = None
    settings.volc_token = None
    with TestClient(create_app(settings)) as client:
        client.post("/api/voice/lease", headers={"X-Voice-Client": "widget"})
        status = client.get("/api/voice/status").json()
        assert status["enabled"] is False

        resp = client.post(
            "/api/voice/recognize",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav", "X-Voice-Client": "widget"},
        )
        assert resp.status_code == 503

        resp = client.post("/api/voice/synthesize", json={"text": "你好"}, headers={"X-Voice-Client": "widget"})
        assert resp.status_code == 503
        assert "语音" in resp.json()["detail"]


def test_provider_error_surfaces_cleanly() -> None:
    with _client(recognizer=BrokenRecognizer()) as client:
        resp = client.post(
            "/api/voice/recognize",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav", "X-Voice-Client": "widget"},
        )
        assert resp.status_code == 503
        assert "供应商余额不足" in resp.json()["detail"]


def test_voice_lease_prefers_web_and_allows_widget_after_release() -> None:
    with _client() as client:
        web = {"X-Voice-Client": "web"}
        widget = {"X-Voice-Client": "widget"}
        assert client.post("/api/voice/lease", headers=web).json()["acquired"] is True
        assert client.post("/api/voice/lease", headers=widget).json()["acquired"] is False
        assert client.post("/api/voice/lease/heartbeat", headers=web).json()["renewed"] is True
        assert client.delete("/api/voice/lease", headers=web).json()["released"] is True
        assert client.post("/api/voice/lease", headers=widget).json()["acquired"] is True
