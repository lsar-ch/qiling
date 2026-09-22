"""技能扩展只读 API（P1）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import shutil
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


BUILTIN_SKILL = """---
name: demo-builtin
description: 内置测试技能
triggers: ["测试"]
enabled: true
---
内置技能正文。
"""

USER_SKILL = """---
name: demo-user
description: 用户测试技能
enabled: false
---
用户技能正文。
"""


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    home = tmp_path / "deskmate-home"
    monkeypatch.setenv("DESKMATE_HOME", str(home))
    (home / "config").mkdir(parents=True)
    (home / "config" / "system_prompt.md").write_text("你是 DeskMate。", encoding="utf-8")
    shutil.copyfile(
        Path(__file__).resolve().parents[3] / "config" / "agents.yaml",
        home / "config" / "agents.yaml",
    )
    builtin = home / "skills" / "builtin" / "demo-builtin"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text(BUILTIN_SKILL, encoding="utf-8")
    user = home / "data" / "skills" / "demo-user"
    user.mkdir(parents=True)
    (user / "SKILL.md").write_text(USER_SKILL, encoding="utf-8")
    with TestClient(create_app(load_settings())) as test_client:
        yield test_client


def test_list_skills(client: TestClient) -> None:
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()["skills"]
    assert [item["id"] for item in skills] == ["demo-builtin", "demo-user"]
    builtin = skills[0]
    assert builtin["source"] == "builtin"
    assert builtin["enabled"] is True
    assert builtin["triggers"] == ["测试"]
    assert skills[1]["source"] == "user"
    assert skills[1]["enabled"] is False


def test_get_skill_detail(client: TestClient) -> None:
    resp = client.get("/api/skills/demo-builtin")
    assert resp.status_code == 200
    data = resp.json()
    assert data["body"] == "内置技能正文。"
    assert data["description"] == "内置测试技能"


def test_get_missing_skill(client: TestClient) -> None:
    resp = client.get("/api/skills/nope")
    assert resp.status_code == 404
