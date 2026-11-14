from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.workbench import WorkbenchDataStore
from qiling_contracts.workbench import WorkbenchNote

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _prepare_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QILING_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        "id: default\nname: 默认\navatar: ''\n", encoding="utf-8"
    )


def test_workbench_item_crud_and_validation(tmp_path: Path, monkeypatch) -> None:
    _prepare_home(tmp_path, monkeypatch)
    with TestClient(create_app(load_settings())) as client:
        item = {
            "id": "docs",
            "kind": "link",
            "title": "文档",
            "group": "开发",
            "url": "https://example.com/docs",
            "visible": True,
            "order": 2,
        }
        created = client.post("/api/workbench/items", json=item)
        assert created.status_code == 200
        assert client.post("/api/workbench/items", json=item).status_code == 409
        assert client.get("/api/workbench/items/docs").json()["item"] == created.json()["item"]
        assert client.get("/api/workbench/items/missing").status_code == 404
        assert client.get("/api/workbench/items").json()["items"] == [created.json()["item"]]
        assert client.patch("/api/workbench/items/docs", json={}).status_code == 422
        assert client.patch("/api/workbench/items/docs", json={"kind": "builtin"}).status_code == 422
        updated = client.patch("/api/workbench/items/docs", json={"visible": False}).json()["item"]
        assert updated["visible"] is False
        assert client.delete("/api/workbench/items/docs").status_code == 200
        assert client.delete("/api/workbench/items/docs").status_code == 404
        assert client.get("/api/settings").json()["workbench"]["items"] == []


def test_notes_and_todos_crud_persist_independently(tmp_path: Path, monkeypatch) -> None:
    _prepare_home(tmp_path, monkeypatch)
    with TestClient(create_app(load_settings())) as client:
        note = client.post("/api/workbench/notes", json={"title": "记录", "content": "正文", "project_path": "/tmp/project-a"}).json()["note"]
        todo = client.post("/api/workbench/todos", json={"title": "完成第一步", "project_path": "/tmp/project-a"}).json()["todo"]
        assert note["note_id"].startswith("note_")
        assert note["project_path"] == "/tmp/project-a"
        assert todo["status"] == "pending"
        assert todo["project_path"] == "/tmp/project-a"
        assert client.get(f"/api/workbench/notes/{note['note_id']}").json()["note"]["title"] == "记录"
        assert client.get(f"/api/workbench/todos/{todo['todo_id']}").json()["todo"]["title"] == "完成第一步"
        assert client.patch(f"/api/workbench/notes/{note['note_id']}", json={}).status_code == 422
        assert client.patch(f"/api/workbench/todos/{todo['todo_id']}", json={"status": "completed"}).json()["todo"]["status"] == "completed"
        assert client.patch("/api/workbench/todos/not-a-todo", json={"title": "x"}).status_code == 404

    with TestClient(create_app(load_settings())) as restarted:
        assert restarted.get("/api/workbench/notes").json()["items"][0]["note_id"] == note["note_id"]
        assert restarted.get("/api/workbench/todos").json()["items"][0]["status"] == "completed"
        assert restarted.delete(f"/api/workbench/notes/{note['note_id']}").status_code == 200
        assert restarted.delete(f"/api/workbench/todos/{todo['todo_id']}").status_code == 200


def test_workbench_store_limit_does_not_evict_existing_data(tmp_path: Path) -> None:
    store = WorkbenchDataStore(tmp_path, WorkbenchNote, "note_id", max_items=1)
    saved = store.put(WorkbenchNote(title="保留"))
    with pytest.raises(ValueError, match="数量已达上限"):
        store.put(WorkbenchNote(title="拒绝"))
    assert store.get(saved.note_id).title == "保留"
