from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.memory.service import MemoryService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATUS_KEYS = {"available", "path", "mirror_dir_exists", "last_sync", "doc_files"}


def prepare_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "system_prompt.md").write_text("你是 DeskMate。", encoding="utf-8")
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


def enable_linked(client: TestClient, vault: Path) -> None:
    resp = client.put(
        "/api/settings",
        json={"memory_mode": "obsidian_linked", "obsidian_vault_path": str(vault)},
    )
    assert resp.status_code == 200


def test_enable_linked_builds_mirror_and_status(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    (vault / "inbox").mkdir(parents=True)
    (vault / "inbox" / "keep.md").write_text("# 已有笔记\n\nDeskMate 不应改动我。", encoding="utf-8")

    with TestClient(create_app(load_settings())) as client:
        enable_linked(client, vault)

        status = client.get("/api/memories/vault/status").json()
        assert set(status) == STATUS_KEYS
        assert status == {
            "available": True,
            "path": str(vault),
            "mirror_dir_exists": True,
            "last_sync": status["last_sync"],
            "doc_files": 10,  # L2(5) + L3(4) + 快照(1)；README 不计
        }
        assert isinstance(status["last_sync"], str) and status["last_sync"]

        mirror = vault / "DeskMate" / "记忆"
        assert (mirror / "README.md").is_file()
        local_progress = (tmp_path / "data" / "memory" / "L3" / "progress.md").read_text(encoding="utf-8")
        assert (mirror / "档案" / "L3-progress.md").read_text(encoding="utf-8").rstrip("\n") == local_progress.rstrip("\n")
        snapshot = (mirror / "快照" / "记忆快照.md").read_text(encoding="utf-8")
        assert "生成时间" in snapshot
        assert "# DeskMate 记忆镜像" in (mirror / "README.md").read_text(encoding="utf-8")

        # 不删除、不改写 vault 其它内容，也不留 .tmp
        assert (vault / "inbox" / "keep.md").read_text(encoding="utf-8") == "# 已有笔记\n\nDeskMate 不应改动我。"
        assert not list(vault.rglob("*.tmp"))


def test_disable_linked_stops_mirror_updates(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()

    with TestClient(create_app(load_settings())) as client:
        enable_linked(client, vault)
        archive = vault / "DeskMate" / "记忆" / "档案" / "L3-progress.md"
        readme = vault / "DeskMate" / "记忆" / "README.md"
        frozen_readme = readme.read_text(encoding="utf-8")

        client.post(
            "/api/memories/docs/L3/progress/entries",
            json={"section": "项目进度", "text": "镜像同步验证条目", "refs": []},
        )
        assert "镜像同步验证条目" in archive.read_text(encoding="utf-8")
        assert readme.read_text(encoding="utf-8") != frozen_readme

        disable = client.put("/api/settings", json={"memory_mode": "standalone"})
        assert disable.status_code == 200
        status = client.get("/api/memories/vault/status").json()
        assert status == {"available": False, "path": None, "mirror_dir_exists": False, "last_sync": None, "doc_files": 0}

        frozen_archive = archive.read_text(encoding="utf-8")
        client.post(
            "/api/memories/docs/L3/progress/entries",
            json={"section": "项目进度", "text": "禁用后不再写入", "refs": []},
        )
        assert archive.read_text(encoding="utf-8") == frozen_archive
        local = client.get("/api/memories/docs/L3/progress").json()["raw_markdown"]
        assert "禁用后不再写入" in local


def test_obsidian_search_skips_mirror_tree(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()

    with TestClient(create_app(load_settings())) as client:
        enable_linked(client, vault)
        client.post(
            "/api/memories/docs/L3/progress/entries",
            json={"section": "项目进度", "text": "只进镜像不进检索", "refs": []},
        )
        (vault / "note.md").write_text("只进镜像不进检索 的普通笔记。", encoding="utf-8")
        (vault / "DeskMate" / "记忆" / "档案" / "secret.md").write_text(
            "镜像独有短语不应被 Obsidian 检索到。", encoding="utf-8"
        )

        shared = client.get("/api/memories/obsidian/search", params={"q": "只进镜像不进检索"}).json()
        assert shared["available"] is True
        assert [item["path"] for item in shared["items"]] == ["note.md"]

        hidden = client.get("/api/memories/obsidian/search", params={"q": "镜像独有短语"}).json()
        assert hidden["items"] == []


def test_unwritable_vault_fails_quietly(tmp_path: Path, monkeypatch) -> None:
    prepare_home(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    vault.chmod(0o500)
    try:
        with TestClient(create_app(load_settings())) as client:
            enable_linked(client, vault)
            status = client.get("/api/memories/vault/status")
            assert status.status_code == 200
            body = status.json()
            assert body["available"] is True
            assert body["mirror_dir_exists"] is False
            assert body["doc_files"] == 0
            upsert = client.post(
                "/api/memories/docs/L3/progress/entries",
                json={"section": "项目进度", "text": "不可写时静默跳过", "refs": []},
            )
            assert upsert.status_code == 200
            assert client.get("/api/memories/vault/status").status_code == 200
            assert not (vault / "DeskMate").exists()
    finally:
        vault.chmod(0o700)


def test_record_event_only_touches_snapshot_timestamp(tmp_path: Path) -> None:
    memory_root = tmp_path / "mem"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = MemoryService(memory_root, persona_dir=tmp_path / "persona")
    service.set_vault_mirror(vault)

    mirror = vault / "DeskMate" / "记忆"
    archive = mirror / "档案" / "L2-conversation.md"
    readme = mirror / "README.md"
    assert archive.is_file() and readme.is_file()

    service.record_event("conversation", "user_turn", {"text": "第一轮"})
    archive_text = archive.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")

    service.record_event("conversation", "user_turn", {"text": "第二轮"})
    assert archive.read_text(encoding="utf-8") == archive_text
    assert readme.read_text(encoding="utf-8") != readme_text
