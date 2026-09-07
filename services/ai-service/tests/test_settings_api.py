from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_settings_and_persona_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        """
id: default
name: 千问
kind: assistant
description: 默认角色
personality: [自然, 可靠]
backstory: ""
language: zh-CN
reply_style: 简洁
avatar: ""
voice:
  provider: minimax
  model: speech-2.8-hd
  voice: "Chinese (Mandarin)_Soft_Girl"
  speed: 1.05
  pitch: 1.0
activation:
  persona_name: 千问
  wake_prefixes: ["你好", "嗨"]
  sleep_phrases: ["暂时静默"]
""".strip(),
        encoding="utf-8",
    )
    with TestClient(create_app(load_settings())) as client:
        settings = client.get("/api/settings").json()
        assert settings["active_persona_id"] == "default"
        assert settings["voice"]["tts_voice"] == "Chinese (Mandarin)_Soft_Girl"

        created = client.post(
            "/api/personas",
            json={
                "id": "cat",
                "name": "小猫",
                "kind": "cat",
                "description": "猫型伙伴",
                "personality": ["活泼"],
                "backstory": "",
                "language": "zh-CN",
                "reply_style": "短句",
                "avatar": "",
                "voice": {"voice": "cat_voice", "speed": 1.2, "pitch": 1.1},
                "activation": {"persona_name": "小猫", "wake_prefixes": ["你好"]},
            },
        )
        assert created.status_code == 200

        updated = client.put("/api/settings", json={"active_persona_id": "cat"}).json()
        assert updated["active_persona_id"] == "cat"
        assert client.get("/api/voice/status").json()["activation"]["persona_name"] == "小猫"

    assert (tmp_path / "data" / "settings.local.json").is_file()


def test_existing_environment_is_not_leaked() -> None:
    assert "OPENAI_API_KEY" not in os.environ or os.environ["OPENAI_API_KEY"] != ""
