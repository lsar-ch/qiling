from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_persona_asset_task_create_and_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QILING_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")

    with TestClient(create_app(load_settings())) as client:
        missing = client.post(
            "/api/persona-tasks",
            json={"kind": "voice_clone", "params": {"reference_audio": "a.wav"}},
        )
        assert missing.status_code == 422

        created = client.post(
            "/api/persona-tasks",
            json={
                "kind": "voice_clone",
                "params": {
                    "reference_audio": "a.wav",
                    "transcript": "你好",
                    "voice_name": "moli",
                },
            },
        )
        assert created.status_code == 200
        run_id = created.json()["run"]["run_id"]
        assert created.json()["run"]["status"] == "pending"
        assert created.json()["run"]["executor"] == "persona_asset"

        listed = client.get("/api/persona-tasks").json()["items"]
        assert [item["run_id"] for item in listed] == [run_id]
        assert client.get(f"/api/persona-tasks/{run_id}").json()["run"]["task_id"] == run_id
