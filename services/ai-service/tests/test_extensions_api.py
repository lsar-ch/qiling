"""技能扩展只读 API（P1）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import shutil
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.skills.registry import SkillRegistry, SkillRegistryError, load_skill_markdown


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

COMPATIBLE_SKILL = """---
name: demo-compatible
description: 兼容元数据测试技能
execution:
  modes: [inline, mcp]
requires: [web-search]
supported_agents: [codex]
license: MIT
source_url: https://example.com/skill
metadata:
  version: "1.2.3"
---
兼容技能正文。
"""


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    home = tmp_path / "qiling-home"
    monkeypatch.setenv("QILING_HOME", str(home))
    (home / "config").mkdir(parents=True)
    (home / "config" / "system_prompt.md").write_text("你是 栖灵。", encoding="utf-8")
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
    compatible = home / "skills" / "builtin" / "demo-compatible"
    compatible.mkdir(parents=True)
    (compatible / "SKILL.md").write_text(COMPATIBLE_SKILL, encoding="utf-8")
    with TestClient(create_app(load_settings())) as test_client:
        yield test_client


def test_list_skills(client: TestClient) -> None:
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()["skills"]
    assert [item["id"] for item in skills] == [
        "demo-builtin",
        "demo-compatible",
        "demo-user",
    ]
    builtin = skills[0]
    assert builtin["source"] == "builtin"
    assert builtin["enabled"] is True
    assert builtin["triggers"] == ["测试"]
    compatible = skills[1]
    assert compatible["execution_modes"] == ["inline", "mcp"]
    assert compatible["requires"] == ["web-search"]
    assert compatible["supported_agents"] == ["codex"]
    assert compatible["license"] == "MIT"
    assert compatible["source_url"] == "https://example.com/skill"
    assert compatible["version"] == "1.2.3"
    assert skills[2]["source"] == "user"
    assert skills[2]["enabled"] is False


def test_get_skill_detail(client: TestClient) -> None:
    resp = client.get("/api/skills/demo-builtin")
    assert resp.status_code == 200
    data = resp.json()
    assert data["body"] == "内置技能正文。"
    assert data["description"] == "内置测试技能"


def test_get_missing_skill(client: TestClient) -> None:
    resp = client.get("/api/skills/nope")
    assert resp.status_code == 404


def test_invalid_execution_mode_rejected(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\n"
        "name: invalid-mode\n"
        "description: invalid\n"
        "execution:\n"
        "  modes: [terminal]\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillRegistryError, match="未知模式"):
        load_skill_markdown(skill, "user")


def test_auto_skill_selection_skips_mode_incompatible_match(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    for skill_id, modes in (("a-inline", "[inline]"), ("b-mcp", "[mcp]")):
        directory = builtin / skill_id
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            "---\n"
            f"name: {skill_id}\n"
            "description: matching skill\n"
            "triggers: [research]\n"
            "execution:\n"
            f"  modes: {modes}\n"
            "---\n"
            "guidance\n",
            encoding="utf-8",
        )
    registry = SkillRegistry(builtin, user)
    selected = registry.resolve(None, "research this", mode="mcp")
    assert selected is not None
    assert selected.info.id == "b-mcp"
