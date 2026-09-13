"""Step 9.5 P1：六段式 profile → 系统提示词生成（借鉴 here）。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import AsyncIterator

import yaml
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.core.persona_prompt import (
    build_system_prompt,
    compose_system_prompt,
    load_persona,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]

FULL_PROFILE_PERSONA = {
    "id": "hero",
    "name": "小助手",
    "kind": "assistant",
    "description": "旧版描述，不应出现在 profile 渲染中",
    "personality": ["旧标签"],
    "backstory": "旧背景",
    "reply_style": "旧风格",
    "language": "zh-CN",
    "voice": {},
    "activation": {},
    "profile": {
        "identity": "桌面上的 AI 工作伙伴",
        "personality": "自然、亲切（ISFJ）",
        "speech": "中文短句，适合朗读",
        "relationship": "并肩推进项目的搭档",
        "preferences": "喜欢清晰的任务边界",
        "boundaries": "敏感操作必须确认",
    },
}


def test_full_profile_renders_all_six_sections() -> None:
    text = build_system_prompt(FULL_PROFILE_PERSONA)
    assert text.startswith("## 角色设定\n")
    for label in ("身份", "性格", "说话风格", "与用户的关系", "偏好", "边界"):
        assert f"### {label}" in text
    assert "桌面上的 AI 工作伙伴" in text
    assert "敏感操作必须确认" in text
    # profile 优先，旧扁平字段不参与
    assert "旧版描述" not in text
    assert "旧标签" not in text


def test_empty_persona_returns_empty_prompt() -> None:
    assert build_system_prompt(None) == ""
    assert build_system_prompt({}) == ""
    assert build_system_prompt({"id": "x", "profile": None}) == ""


def test_legacy_flat_fields_fallback() -> None:
    legacy = {
        "description": "默认角色",
        "personality": ["自然", "亲切"],
        "backstory": "住在桌面上",
        "reply_style": "简洁",
    }
    text = build_system_prompt(legacy)
    assert text.startswith("## 角色设定\n")
    assert "默认角色" in text
    assert "自然、亲切" in text
    assert "住在桌面上" in text
    assert "简洁" in text


def test_partial_profile_mixes_with_legacy() -> None:
    persona = {"description": "默认角色", "profile": {"identity": "新身份"}}
    text = build_system_prompt(persona)
    assert "新身份" in text
    assert "默认角色" not in text  # 同段 priority profile；其他段无内容则跳过
    assert "### 说话风格" not in text


def test_compose_system_prompt() -> None:
    base = "你是 DeskMate。"
    assert compose_system_prompt(base, None) == base
    assert compose_system_prompt(base, {}) == base
    out = compose_system_prompt(base, FULL_PROFILE_PERSONA)
    assert out.startswith("你是 DeskMate。\n\n## 角色设定")
    assert "敏感操作必须确认" in out


def test_load_persona(tmp_path: Path) -> None:
    (tmp_path / "hero.yaml").write_text(
        yaml.safe_dump(FULL_PROFILE_PERSONA, allow_unicode=True),
        encoding="utf-8",
    )
    assert load_persona(tmp_path, "hero")["id"] == "hero"
    assert load_persona(tmp_path, "missing") is None
    assert load_persona(tmp_path, None) is None
    assert load_persona(tmp_path, "") is None
    (tmp_path / "bad.yaml").write_text("{: bad", encoding="utf-8")
    assert load_persona(tmp_path, "bad") is None


class CaptureProvider:
    display_name = "capture"

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        self.messages = messages
        yield "好的"


def test_chat_system_prompt_includes_persona_profile(tmp_path: Path) -> None:
    previous = os.environ.get("DESKMATE_HOME")
    os.environ["DESKMATE_HOME"] = str(tmp_path)
    (tmp_path / "config" / "personas").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "system_prompt.md").write_text(
        "你是 DeskMate。", encoding="utf-8"
    )
    shutil.copyfile(
        PROJECT_ROOT / "config" / "agents.yaml",
        tmp_path / "config" / "agents.yaml",
    )
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        # 角色卡文件内 id 必须与文件名一致，否则 _apply_persona 会改 active_persona_id
        yaml.safe_dump({**FULL_PROFILE_PERSONA, "id": "default"}, allow_unicode=True),
        encoding="utf-8",
    )
    provider = CaptureProvider()
    try:
        with TestClient(create_app(load_settings(), llm_provider=provider)) as client:
            client.post("/api/chat/stream", json={"message": "在吗"})
    finally:
        if previous is None:
            os.environ.pop("DESKMATE_HOME", None)
        else:
            os.environ["DESKMATE_HOME"] = previous

    system = provider.messages[0]["content"]
    assert "你是 DeskMate。" in system
    assert "## 角色设定" in system
    assert "敏感操作必须确认" in system
