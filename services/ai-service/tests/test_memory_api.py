from __future__ import annotations

import shutil
from pathlib import Path
from typing import AsyncIterator

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class InspectProvider:
    display_name = "inspect"

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def stream_chat(self, messages: list[dict[str, str]], **kwargs) -> AsyncIterator[str]:
        self.messages = messages
        yield "已记录项目进展。"


def prepare_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QILING_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "system_prompt.md").write_text("你是 栖灵。", encoding="utf-8")
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        """
id: default
name: 千问
kind: assistant
description: 项目伙伴
personality: [简洁]
backstory: 住在桌面上。
language: zh-CN
reply_style: 简洁
avatar: ""
voice: {}
activation: {}
""".strip(),
        encoding="utf-8",
    )


def test_memory_doc_crud_and_search(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    with TestClient(create_app(load_settings())) as client:
        settings = client.get("/api/settings").json()
        assert settings["memory"]["mode"] == "standalone"
        overview = client.get("/api/memories/overview").json()["items"]
        assert any(item["layer"] == "L3" and item["key"] == "progress" for item in overview)

        created = client.post(
            "/api/memories/docs/L3/progress/entries",
            json={"section": "项目进度", "text": "Step 5 正在实现最小项目记忆", "refs": []},
        ).json()
        entry_id = created["entry_id"]
        assert entry_id.startswith("m_")
        assert "Step 5" in client.get("/api/memories/docs/L3/progress").json()["raw_markdown"]

        hits = client.get("/api/memories/search", params={"q": "项目记忆"}).json()["items"]
        assert hits and hits[0]["entry_id"] == entry_id

        deleted = client.delete(f"/api/memories/entries/{entry_id}").json()
        assert deleted["deleted"] is True

        bundle = client.get("/api/memories/export").json()
        assert bundle["mode"] == "standalone"
        assert bundle["docs"]


def test_chat_records_and_injects_memory(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    provider = InspectProvider()
    settings = load_settings()
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        client.post(
            "/api/memories/docs/L3/progress/entries",
            json={"section": "项目进度", "text": "栖灵 当前进入 Step 5", "refs": []},
        )
        resp = client.post("/api/chat/stream", json={"message": "项目现在做到哪一步？"})
        assert resp.status_code == 200
        system = provider.messages[0]["content"]
        assert "项目记忆" in system
        assert "栖灵 当前进入 Step 5" in system

    assert list((tmp_path / "data" / "memory" / "trace" / "conversation").glob("*.jsonl"))
    assert list((tmp_path / "data" / "memory" / "session").glob("*.md"))


def test_obsidian_search_is_read_only(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("栖灵 项目方向：本地优先。", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))

    with TestClient(create_app(load_settings())) as client:
        settings = client.put("/api/settings", json={"memory_mode": "obsidian_linked", "obsidian_vault_path": str(vault)}).json()
        assert settings["memory"]["mode"] == "obsidian_linked"
        data = client.get("/api/memories/obsidian/search", params={"q": "本地优先"}).json()
        assert data["available"] is True
        assert data["items"][0]["path"] == "note.md"


def test_unset_vault_path_is_never_treated_as_linked(tmp_path: Path, monkeypatch) -> None:
    """库路径未配置时不能把进程 cwd 当成库：Path("") 退化成 "." 且 is_dir() 恒真。"""
    prepare_home(tmp_path, monkeypatch)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    with TestClient(create_app(load_settings())) as client:
        memory = client.get("/api/settings").json()["memory"]
        assert memory["obsidian_default_path"] == ""
        assert memory["obsidian_configured"] is False

        assert client.put("/api/settings", json={"memory_mode": "obsidian_linked"}).status_code == 200

        assert client.get("/api/health").json()["memory_stats"]["obsidian_linked"] is False
        assert client.get("/api/settings").json()["memory"]["obsidian_configured"] is False
        search = client.get("/api/memories/obsidian/search", params={"q": "本地优先"}).json()
        assert search["available"] is False
        assert search["items"] == []


def test_obsidian_check_is_read_only_and_does_not_create_mirror(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("本地优先。", encoding="utf-8")

    with TestClient(create_app(load_settings())) as client:
        checked = client.get("/api/memories/obsidian/check", params={"path": str(vault)}).json()
        assert checked == {"available": True, "path": str(vault), "note_count": 1}
        assert not (vault / "栖灵").exists()

        missing = client.get("/api/memories/obsidian/check", params={"path": str(tmp_path / "missing")}).json()
        assert missing == {"available": False, "path": str(tmp_path / "missing"), "note_count": 0}
