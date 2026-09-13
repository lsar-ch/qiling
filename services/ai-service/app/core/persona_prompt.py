"""PersonaPayload → 自然语言系统提示词。

借鉴 here 的 build_character_setting_from_profile()：把六段式档案
（identity / personality / speech / relationship / preferences / boundaries）
渲染为自然语言段落，拼接到基础系统提示词之后。

兼容旧角色卡：profile 缺失时回退到扁平字段
（description / personality / backstory / reply_style）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# 六段式小节：字段名 → 中文标题（顺序即渲染顺序）
PROFILE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("identity", "身份"),
    ("personality", "性格"),
    ("speech", "说话风格"),
    ("relationship", "与用户的关系"),
    ("preferences", "偏好"),
    ("boundaries", "边界"),
)

# profile 为空时回退到旧角色卡的扁平字段
_LEGACY_FALLBACK: dict[str, str] = {
    "identity": "description",
    "personality": "personality",
    "speech": "reply_style",
    "relationship": "backstory",
}


def load_persona(personas_dir: Path, persona_id: str | None) -> dict[str, Any] | None:
    """读取指定角色卡 YAML；不存在、非法或 id 为空时返回 None。"""
    if not persona_id:
        return None
    path = personas_dir / f"{persona_id}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _section_text(
    profile: dict[str, Any],
    persona: dict[str, Any],
    key: str,
    label: str,
) -> str | None:
    value = profile.get(key)
    if isinstance(value, str) and value.strip():
        return f"### {label}\n{value.strip()}"
    legacy_key = _LEGACY_FALLBACK.get(key)
    if legacy_key is not None:
        fallback = persona.get(legacy_key)
        if isinstance(fallback, list):
            fallback = "、".join(str(item) for item in fallback if str(item).strip())
        if isinstance(fallback, str) and fallback.strip():
            return f"### {label}\n{fallback.strip()}"
    return None


def build_system_prompt(persona: dict[str, Any] | None) -> str:
    """把角色档案渲染为「## 角色设定」段落；无有效内容时返回空串。"""
    if not persona:
        return ""
    profile = persona.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    sections: list[str] = []
    for key, label in PROFILE_SECTIONS:
        text = _section_text(profile, persona, key, label)
        if text is not None:
            sections.append(text)
    if not sections:
        return ""
    return "## 角色设定\n" + "\n\n".join(sections)


def compose_system_prompt(
    base_prompt: str,
    persona: dict[str, Any] | None,
) -> str:
    """基础提示词 + 角色设定段；角色段为空时原样返回基础提示词。"""
    persona_section = build_system_prompt(persona)
    if not persona_section:
        return base_prompt
    return f"{base_prompt}\n\n{persona_section}"
