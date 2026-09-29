from __future__ import annotations

import json
import shutil
from typing import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class CaptureProvider:
    display_name = "capture"

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        yield "已收到"


def _prepare_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "DASHSCOPE_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        "id: default\nname: 默认\nvoice: {}\nactivation: {}\n",
        encoding="utf-8",
    )


def test_model_profile_crud_defaults_and_key_redaction(tmp_path: Path, monkeypatch) -> None:
    _prepare_home(tmp_path, monkeypatch)

    with TestClient(create_app(load_settings())) as client:
        initial = client.get("/api/model-profiles")
        assert initial.status_code == 200
        assert initial.json()["items"] == []
        assert {item["label"] for item in initial.json()["categories"]} == {
            "通用文字模型",
            "多模态模型",
            "语音识别模型",
            "语音合成模型",
        }

        first = client.post(
            "/api/model-profiles",
            json={
                "id": "text_a",
                "name": "千问 Plus",
                "category": "text",
                "provider": "openai_compatible",
                "base_url": "https://example.invalid/v1",
                "model": "qwen-plus",
                "api_key": "secret-text-key",
                "enabled": True,
                "is_default": False,
            },
        )
        assert first.status_code == 200
        assert first.json()["is_default"] is True
        assert first.json()["api_key_configured"] is True
        assert "secret-text-key" not in first.text

        second = client.post(
            "/api/model-profiles",
            json={
                "id": "text_b",
                "name": "备用文字模型",
                "category": "text",
                "provider": "openai_compatible",
                "base_url": "https://example.invalid/v1",
                "model": "qwen-max",
                "api_key": "secret-text-key-2",
                "enabled": True,
                "is_default": True,
            },
        )
        assert second.status_code == 200
        items = {item["id"]: item for item in client.get("/api/model-profiles").json()["items"]}
        assert items["text_a"]["is_default"] is False
        assert items["text_b"]["is_default"] is True
        assert client.get("/api/settings").json()["llm"]["model"] == "qwen-max"

        updated = client.put(
            "/api/model-profiles/text_b",
            json={
                "id": "text_b",
                "name": "备用文字模型",
                "category": "text",
                "provider": "openai_compatible",
                "base_url": "https://example.invalid/v1",
                "model": "qwen-max-latest",
                "enabled": True,
                "is_default": True,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["api_key_configured"] is True

        stt = client.post(
            "/api/model-profiles",
            json={
                "id": "stt_default",
                "name": "语音识别",
                "category": "stt",
                "provider": "dashscope",
                "model": "paraformer-realtime-v2",
                "api_key": "secret-stt-key",
                "enabled": True,
                "is_default": True,
            },
        )
        assert stt.status_code == 200
        settings = client.get("/api/settings").json()
        assert settings["voice"]["dashscope_configured"] is True
        assert settings["voice"]["stt_model"] == "paraformer-realtime-v2"

        tts = client.post(
            "/api/model-profiles",
            json={
                "id": "tts_default",
                "name": "默认音色",
                "category": "tts",
                "provider": "minimax",
                "model": "speech-2.8-hd",
                "voice": "Chinese (Mandarin)_Soft_Girl",
                "api_key": "secret-tts-key",
                "enabled": True,
                "is_default": True,
            },
        )
        assert tts.status_code == 200
        settings = client.get("/api/settings").json()
        assert settings["voice"]["minimax_configured"] is True
        assert settings["voice"]["tts_model"] == "speech-2.8-hd"
        assert settings["voice"]["tts_voice"] == "Chinese (Mandarin)_Soft_Girl"

    stored = json.loads((tmp_path / "data" / "settings.local.json").read_text(encoding="utf-8"))
    assert stored["model_profiles"][0]["api_key"]


def test_profile_selection_can_bind_to_persona(tmp_path: Path, monkeypatch) -> None:
    _prepare_home(tmp_path, monkeypatch)

    with TestClient(create_app(load_settings())) as client:
        created = client.post(
            "/api/model-profiles",
            json={
                "id": "text_persona",
                "name": "角色专用模型",
                "category": "text",
                "provider": "openai_compatible",
                "base_url": "https://example.invalid/v1",
                "model": "qwen-plus",
                "api_key": "secret",
                "enabled": True,
                "is_default": True,
            },
        )
        assert created.status_code == 200
        persona = client.get("/api/personas").json()["items"][0]
        persona["llm"] = {"profile_id": "text_persona"}
        saved = client.put("/api/personas/default", json=persona)
        assert saved.status_code == 200
        assert saved.json()["llm"]["profile_id"] == "text_persona"

        blocked = client.delete("/api/model-profiles/text_persona")
        assert blocked.status_code == 409


def test_chat_uses_persona_model_binding(tmp_path: Path, monkeypatch) -> None:
    _prepare_home(tmp_path, monkeypatch)

    with TestClient(create_app(load_settings())) as client:
        for profile_id, model in (("text_global", "qwen-plus"), ("text_persona", "qwen-max")):
            response = client.post(
                "/api/model-profiles",
                json={
                    "id": profile_id,
                    "name": profile_id,
                    "category": "text",
                    "provider": "openai_compatible",
                    "base_url": "https://example.invalid/v1",
                    "model": model,
                    "api_key": "secret",
                    "enabled": True,
                    "is_default": profile_id == "text_global",
                },
            )
            assert response.status_code == 200

        persona = client.get("/api/personas").json()["items"][0]
        persona["llm"] = {"profile_id": "text_persona"}
        assert client.put("/api/personas/default", json=persona).status_code == 200

        captured_models: list[str] = []

        def capture_provider(settings):
            captured_models.append(settings.llm_model)
            return CaptureProvider()

        monkeypatch.setattr("app.api.chat.create_provider", capture_provider)
        response = client.post("/api/chat/stream", json={"message": "你好"})
        assert response.status_code == 200
        assert captured_models[-1] == "qwen-max"
        assert '"model_profile_id": "text_persona"' in response.text


def test_persona_voice_wins_over_default_tts_profile() -> None:
    """角色卡显式绑定音色后，语音合成模型档案不再覆盖它。"""
    from app.config import Settings
    from app.model_profiles import apply_default_profiles

    overrides = {
        "model_profiles": [
            {
                "id": "tts_default",
                "name": "speech-2.8-hd",
                "category": "tts",
                "provider": "minimax",
                "model": "speech-2.8-hd",
                "voice": "male-qn-qingse",
                "enabled": True,
                "is_default": True,
            }
        ]
    }
    settings = Settings(repo_root=PROJECT_ROOT)
    settings.persona_voice = "Chinese (Mandarin)_Soft_Girl"
    settings.tts_voice = "Chinese (Mandarin)_Soft_Girl"
    apply_default_profiles(settings, overrides)
    assert settings.tts_voice == "Chinese (Mandarin)_Soft_Girl"


def test_default_tts_profile_voice_applies_without_persona_binding() -> None:
    from app.config import Settings
    from app.model_profiles import apply_default_profiles

    overrides = {
        "model_profiles": [
            {
                "id": "tts_default",
                "name": "speech-2.8-hd",
                "category": "tts",
                "provider": "minimax",
                "model": "speech-2.8-hd",
                "voice": "male-qn-qingse",
                "enabled": True,
                "is_default": True,
            }
        ]
    }
    settings = Settings(repo_root=PROJECT_ROOT)
    apply_default_profiles(settings, overrides)
    assert settings.tts_voice == "male-qn-qingse"


class _FakeModelsResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeModelsClient:
    """只替掉 httpx.AsyncClient，不打真实网络。"""

    def __init__(self, response: "_FakeModelsResponse") -> None:
        self._response = response
        self.requested_url = ""

    async def __aenter__(self) -> "_FakeModelsClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get(self, url: str, headers: dict | None = None) -> "_FakeModelsResponse":
        self.requested_url = url
        return self._response


def test_provider_model_list_endpoint(tmp_path: Path, monkeypatch) -> None:
    _prepare_home(tmp_path, monkeypatch)

    import app.model_profiles as mp

    client_holder: dict[str, _FakeModelsClient] = {}

    def fake_async_client(*args: object, **kwargs: object) -> _FakeModelsClient:
        client = _FakeModelsClient(
            _FakeModelsResponse(200, {"data": [{"id": "qwen-max"}, {"id": "qwen-flash"}, {"id": "qwen-flash"}]})
        )
        client_holder["client"] = client
        return client

    monkeypatch.setattr(mp.httpx, "AsyncClient", fake_async_client)

    with TestClient(create_app(load_settings())) as client:
        body = client.get(
            "/api/model-profiles/models",
            params={"base_url": "https://example.invalid/v1", "api_key": "k"},
        ).json()
        assert body["available"] is True
        assert body["models"] == ["qwen-flash", "qwen-max"]  # 去重且排序
        assert client_holder["client"].requested_url == "https://example.invalid/v1/models"

        # 缺 Key 时不发请求，返回可读原因
        missing = client.get(
            "/api/model-profiles/models",
            params={"base_url": "https://example.invalid/v1"},
        ).json()
        assert missing["available"] is False
        assert missing["models"] == []
        assert missing["reason"]

        # profile_id 不存在 -> 404
        assert client.get("/api/model-profiles/models", params={"profile_id": "nope"}).status_code == 404
