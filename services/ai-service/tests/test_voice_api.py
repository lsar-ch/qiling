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
    DisabledSynthesizer,
    SpeechRecognizer,
    SpeechStack,
    SpeechSynthesizer,
    SpeechUnavailable,
    VoiceOption,
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


class ListedSynthesizer(FakeSynthesizer):
    name = "listed-tts"

    async def list_voices(self) -> list[VoiceOption]:
        return [
            VoiceOption(id="Chinese (Mandarin)_Soft_Girl", name="温柔女声", kind="system"),
            VoiceOption(id="deskmate_voice_01", name="我的克隆音", kind="cloned"),
        ]


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


def test_recognize_empty_result_is_not_an_error() -> None:
    """空识别结果（用户没说话 / 噪声误触）应是 200 + 空文本，不是 422。

    422 只保留给真正的坏请求（非 WAV）。否则前端只能靠匹配错误文案来区分
    「没听清」与「识别失败」，且 web 侧「没听清，再说一次？」分支永远不可达。
    """
    with _client(recognizer=FakeRecognizer("")) as client:
        resp = client.post(
            "/api/voice/recognize?language=zh",
            content=_wav_bytes(),
            headers={"Content-Type": "audio/wav", "X-Voice-Client": "widget"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == ""
        assert body["provider"] == "fake-stt"
        assert body["available"] is True


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


def test_voice_lease_is_exclusive_and_allows_next_client_after_release() -> None:
    with _client() as client:
        web = {"X-Voice-Client": "web"}
        widget = {"X-Voice-Client": "widget"}
        assert client.post("/api/voice/lease", headers=widget).json()["acquired"] is True
        assert client.post("/api/voice/lease", headers=web).json()["acquired"] is False
        assert client.post("/api/voice/lease/heartbeat", headers=widget).json()["renewed"] is True
        assert client.delete("/api/voice/lease", headers=widget).json()["released"] is True
        assert client.post("/api/voice/lease", headers=web).json()["acquired"] is True
        assert client.post("/api/voice/lease", headers=widget).json()["acquired"] is False


def test_synthesize_works_without_lease() -> None:
    """播报不看租约：未持租约的客户端也能合成音频。"""
    with _client() as client:
        resp = client.post(
            "/api/voice/synthesize",
            json={"text": "随时可以播报"},
            headers={"X-Voice-Client": "web"},
        )
        assert resp.status_code == 200
        assert resp.content == b"FAKE-AUDIO:" + "随时可以播报".encode()


def test_lease_owner_change_is_broadcast() -> None:
    """force 抢占与释放都会广播 voice.lease.changed（直接看事件总线历史）。"""
    with TestClient(create_app(load_settings(), speech=_stack_for_broadcast())) as client:
        hub = client.app.state.event_hub

        def latest_lease_owner():
            for item in hub.recent(limit=50):
                if item["event_type"] == "voice.lease.changed":
                    return item["payload"]["owner"]
            return "__missing__"

        assert client.post(
            "/api/voice/lease",
            headers={"X-Voice-Client": "widget"},
        ).json()["acquired"] is True
        assert latest_lease_owner() == "widget"

        assert client.post(
            "/api/voice/lease?force=true",
            headers={"X-Voice-Client": "web"},
        ).json()["acquired"] is True
        assert latest_lease_owner() == "web"

        client.delete("/api/voice/lease", headers={"X-Voice-Client": "web"})
        assert latest_lease_owner() is None


def _stack_for_broadcast() -> SpeechStack:
    return SpeechStack(
        recognizer=FakeRecognizer(),
        synthesizer=FakeSynthesizer(),
        stt_model="paraformer-realtime-v2",
        tts_model="cosyvoice-v2",
        tts_voice="longxiaochun_v2",
        tts_format="wav",
        tts_sample_rate=24000,
        params=VoiceParams(),
    )


def test_voices_lists_provider_options() -> None:
    with _client(synthesizer=ListedSynthesizer()) as client:
        body = client.get("/api/voice/voices").json()
        assert body["provider"] == "listed-tts"
        assert body["available"] is True
        assert body["reason"] is None
        assert [item["id"] for item in body["voices"]] == [
            "Chinese (Mandarin)_Soft_Girl",
            "deskmate_voice_01",
        ]
        assert body["voices"][1]["kind"] == "cloned"


def test_voices_degrades_when_provider_has_no_list() -> None:
    """供应商不支持列举音色时返回空列表 + 原因，前端回退手填。"""
    with _client() as client:
        body = client.get("/api/voice/voices").json()
        assert body["voices"] == []
        assert body["reason"]


def test_voices_reports_unconfigured_provider() -> None:
    with _client(synthesizer=DisabledSynthesizer("语音合成不可用（测试）")) as client:
        body = client.get("/api/voice/voices").json()
        assert body["available"] is False
        assert body["voices"] == []
        assert body["reason"]


def test_voices_rejects_unknown_profile() -> None:
    with _client() as client:
        assert client.get("/api/voice/voices?profile_id=missing").status_code == 404


def _prepare_tts_home(tmp_path, monkeypatch) -> None:
    """临时 DESKMATE_HOME：只有一个 openai_compatible 的 TTS 档案。"""
    import json
    import shutil
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    for key in ("DASHSCOPE_API_KEY", "MINIMAX_API_KEY", "VOICE_TTS_PROVIDER", "VOICE_TTS_VOICE"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(project_root / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        "id: default\nname: 默认\nvoice: {}\nactivation: {}\n", encoding="utf-8"
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings.local.json").write_text(
        json.dumps(
            {
                "model_profiles": [
                    {
                        "id": "tts_local",
                        "name": "本地 Kokoro",
                        "category": "tts",
                        "provider": "openai_compatible",
                        "base_url": "https://tts.example.com/v1",
                        "model": "kokoro",
                        "voice": "zf_xiaobei",
                        "enabled": True,
                        "is_default": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _fake_openai_tts(monkeypatch):
    """假 httpx：/audio/voices 返回两条音色，/audio/speech 返回假音频。"""
    from app.speech import openai_tts

    calls: list = []

    class _JsonResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"voices": ["zf_xiaobei", {"id": "zm_yunxi", "name": "云希"}]}

    class _AudioResponse:
        status_code = 200
        text = ""
        content = b"FAKE-PREVIEW-AUDIO"

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def get(self, url, headers=None):
            calls.append(("GET", url))
            assert url == "https://tts.example.com/v1/audio/voices"
            return _JsonResponse()

        async def post(self, url, json=None, headers=None):
            calls.append(("POST", url, json))
            assert url == "https://tts.example.com/v1/audio/speech"
            return _AudioResponse()

    monkeypatch.setattr(openai_tts.httpx, "AsyncClient", _Client)
    return calls


def test_voices_uses_profile_scoped_openai_compatible_provider(tmp_path, monkeypatch) -> None:
    """非 MiniMax 供应商：配置好档案后按 profile_id 自动拉取音色列表。"""
    _prepare_tts_home(tmp_path, monkeypatch)
    _fake_openai_tts(monkeypatch)

    with TestClient(create_app(load_settings())) as client:
        body = client.get("/api/voice/voices?profile_id=tts_local").json()
        assert body["provider"] == "openai_compatible"
        assert body["available"] is True
        assert [item["id"] for item in body["voices"]] == ["zf_xiaobei", "zm_yunxi"]
        assert body["voices"][1]["name"] == "云希"


def test_preview_synthesizes_with_selected_voice(tmp_path, monkeypatch) -> None:
    _prepare_tts_home(tmp_path, monkeypatch)
    calls = _fake_openai_tts(monkeypatch)

    with TestClient(create_app(load_settings())) as client:
        resp = client.post(
            "/api/voice/preview",
            json={"profile_id": "tts_local", "voice": "zm_yunxi", "text": "试听一句"},
        )
        assert resp.status_code == 200
        assert resp.content == b"FAKE-PREVIEW-AUDIO"
        assert resp.headers["content-type"].startswith("audio/")
        assert resp.headers["X-Speech-Format"] == "wav"
        method, _url, payload = calls[-1]
        assert method == "POST"
        assert payload["voice"] == "zm_yunxi"
        assert payload["input"] == "试听一句"


def test_preview_rejects_unknown_profile() -> None:
    with _client() as client:
        assert client.post("/api/voice/preview", json={"profile_id": "missing"}).status_code == 404


def test_preview_requires_key_for_cloud_provider(tmp_path, monkeypatch) -> None:
    """未配置密钥的云供应商：给出明确 400，而不是让它打到网络上。"""
    _prepare_tts_home(tmp_path, monkeypatch)
    with TestClient(create_app(load_settings())) as client:
        resp = client.post("/api/voice/preview", json={"provider": "minimax", "voice": "v"})
        assert resp.status_code == 400
        assert "API Key" in resp.json()["detail"]


def test_preview_allows_keyless_self_hosted_service(tmp_path, monkeypatch) -> None:
    """自建 OpenAI 兼容服务通常无鉴权：不填 Key 也能试听。"""
    _prepare_tts_home(tmp_path, monkeypatch)
    _fake_openai_tts(monkeypatch)

    with TestClient(create_app(load_settings())) as client:
        resp = client.post("/api/voice/preview", json={"profile_id": "tts_local"})
        assert resp.status_code == 200
        assert resp.content == b"FAKE-PREVIEW-AUDIO"
