"""P0-5：项目节点模型、持久化和 API。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    monkeypatch.setenv("QILING_HOME", str(home))
    (home / "config" / "personas").mkdir(parents=True, exist_ok=True)
    (home / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (home / "config" / "system_prompt.md").write_text("你是 栖灵。", encoding="utf-8")
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", home / "config" / "agents.yaml")
    (home / "config" / "personas" / "default.yaml").write_text(
        "id: default\nname: 栖灵\nkind: assistant\nlanguage: zh-CN\n",
        encoding="utf-8",
    )
    (home / "data").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(load_settings()))


def test_project_nodes_crud_and_persistence(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with make_client(tmp_path, monkeypatch) as client:
        create = client.post(
            "/api/projects/nodes",
            json={
                "project": str(project),
                "title": "V2-P0",
                "kind": "phase",
                "status": "in_progress",
                "next_step": "完成项目节点 API",
            },
        )
        assert create.status_code == 200
        node = create.json()
        assert node["project"] == str(project.resolve())
        node_id = node["node_id"]

        listed = client.get("/api/projects/nodes", params={"project": str(project)})
        assert listed.status_code == 200
        assert listed.json()["items"][0]["node_id"] == node_id

        updated = client.put(
            f"/api/projects/nodes/{node_id}",
            json={
                "project": str(project),
                "title": "V2-P0 已完成",
                "kind": "phase",
                "status": "completed",
                "task_ids": ["task_demo"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "completed"

        restarted = make_client(tmp_path, monkeypatch)
        with restarted:
            assert restarted.get(
                "/api/projects/nodes", params={"project": str(project)}
            ).json()["items"][0]["task_ids"] == ["task_demo"]

        deleted = client.delete(f"/api/projects/nodes/{node_id}")
        assert deleted.status_code == 200
        assert client.get(
            "/api/projects/nodes", params={"project": str(project)}
        ).json()["items"] == []
