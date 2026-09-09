"""Step 10 后端验收：dashboard 信息字段 / 性能模式 / 录制 stub。"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PERSONA_YAML = """\
id: default
name: 千问
kind: assistant
description: 默认角色
personality: [自然]
backstory: ""
language: zh-CN
reply_style: 简洁
avatar: ""
"""


def _make_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    # app.main 模块级导入会把仓库根 .env 的真实 key 灌进进程环境，
    # 这里显式清除，确保用例在无供应商 key 的隔离环境下运行。
    for key in (
        "DASHSCOPE_API_KEY",
        "MINIMAX_API_KEY",
        "OPENAI_API_KEY",
        "VOLC_APP_ID",
        "VOLC_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(
        PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml"
    )
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        _PERSONA_YAML.strip(),
        encoding="utf-8",
    )
    return TestClient(create_app(load_settings()))


def test_health_returns_dashboard_fields(tmp_path: Path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()

        assert body["performance_mode"] in ("quality", "balanced", "lite")
        vp = body["voice_pipeline"]
        assert set(vp) == {"stt_ready", "tts_ready", "vad_working", "degradation_reason"}
        assert isinstance(vp["stt_ready"], bool)
        assert isinstance(vp["tts_ready"], bool)
        assert isinstance(vp["vad_working"], bool)
        assert vp["degradation_reason"] is None or isinstance(vp["degradation_reason"], str)

        activity = body["recent_activity"]
        assert isinstance(activity, list) and len(activity) <= 5
        for item in activity:
            assert {"event_type", "timestamp", "summary"} == set(item)

        stats = body["memory_stats"]
        assert set(stats) == {"total_entries", "obsidian_linked", "last_compile"}
        assert isinstance(stats["total_entries"], int)
        assert isinstance(stats["obsidian_linked"], bool)
        assert stats["last_compile"] is None or isinstance(stats["last_compile"], str)


def test_lite_mode_disables_voice_and_persists(tmp_path: Path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch) as client:
        updated = client.put("/api/settings", json={"performance_mode": "lite"})
        assert updated.status_code == 200
        assert updated.json()["performance_mode"] == "lite"

        assert client.get("/api/settings").json()["performance_mode"] == "lite"
        settings_file = tmp_path / "data" / "settings.local.json"
        assert settings_file.is_file()
        assert json.loads(settings_file.read_text(encoding="utf-8"))["performance_mode"] == "lite"

        health = client.get("/api/health").json()
        assert health["performance_mode"] == "lite"
        vp = health["voice_pipeline"]
        assert vp["stt_ready"] is False
        assert vp["tts_ready"] is False
        assert vp["vad_working"] is False
        assert vp["degradation_reason"]

        status = client.get("/api/voice/status").json()
        assert status["enabled"] is False
        assert status["stt"]["available"] is False
        assert status["tts"]["available"] is False
        assert status["activation"]["enabled"] is False

        recognize = client.post("/api/voice/recognize", content=b"not-wav")
        assert recognize.status_code == 503
        assert "轻量模式" in recognize.json()["detail"]
        synth = client.post(
            "/api/voice/synthesize",
            json={"text": "你好"},
        )
        assert synth.status_code == 503
        assert "轻量模式" in synth.json()["detail"]


def test_balanced_mode_voice_not_force_disabled(tmp_path: Path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch) as client:
        client.put("/api/settings", json={"performance_mode": "quality"})
        health = client.get("/api/health").json()
        assert health["performance_mode"] == "quality"
        # 无 key 环境下仍应由供应商可用性决定，而不是被 lite 强制禁用
        vp = health["voice_pipeline"]
        assert isinstance(vp["degradation_reason"], str)


def test_recording_stub_endpoints(tmp_path: Path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch) as client:
        status = client.get("/api/recording/status")
        assert status.status_code == 200
        assert status.json()["active_session"] is None

        start = client.post("/api/recording/start", json={})
        assert start.status_code == 200
        assert start.json() == {"status": "not_implemented", "message": "录制功能待实现"}

        stop = client.post("/api/recording/stop")
        assert stop.status_code == 200
        assert stop.json() == {"status": "not_implemented", "message": "录制功能待实现"}
