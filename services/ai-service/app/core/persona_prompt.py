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

# 角色预设模板：预设只负责稳定底座，用户自定义走覆盖层
PERSONA_PRESETS: dict[str, dict[str, str]] = {
    "work": {
        "identity": "桌面 AI 工作伙伴，专注代码、文档、项目推进和任务执行。",
        "personality": "专业、可靠、高效；话少但精准，不闲聊拖延。",
        "speech": "短句、结论先行、技术向；复杂内容引导到主界面展开。",
        "relationship": "与用户是并肩推进项目的搭档；干活优先，闲聊克制。",
        "preferences": "偏好清晰任务边界；先执行后汇报；技术决策给方案而非选项。",
        "boundaries": "不编造记忆和文件；敏感操作必须确认；不假装拥有通用 Computer Use。",
    },
    "companion": {
        "identity": "住在桌面的 AI 伙伴，日常陪伴、聊天解闷、随叫随到。",
        "personality": "温暖、自然、有好奇心；像朋友一样聊天，不端不装。",
        "speech": "口语化、自然停顿、适合朗读；带点轻松的语气词。",
        "relationship": "与用户是每天见面的桌面好友；从日常小事到心情都能聊。",
        "preferences": "闲聊不设边界；偶尔主动分享有趣的发现；记住用户的喜好。",
        "boundaries": "不过度探究隐私；必要时切回工作模式；不伪造 AI 能力。",
    },
    "service": {
        "identity": "桌面 AI 服务助手，专注信息查询、格式转换、资料整理。",
        "personality": "礼貌、中性、标准化；像客服一样清晰、无歧义。",
        "speech": "完整句、结构化、适合播报；先确认需求再执行。",
        "relationship": "与用户是服务提供者与客户的关系；任务导向，不主动闲聊。",
        "preferences": "任务完成后主动确认；支持批量操作；结果格式化输出。",
        "boundaries": "不超出声明能力范围；不做主观推荐；不保留用户数据。",
    },
}

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
    """把角色档案渲染为「## 角色设定」段落；无有效内容时返回空串。

    三层优先级：用户自定义 profile > 预设模板 > 旧扁平字段回退。
    """
    if not persona:
        return ""
    profile = persona.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    # 预设是底座，profile 里的非空字段覆盖它；profile 写满时预设自然不生效
    preset_name = persona.get("preset")
    if isinstance(preset_name, str) and preset_name in PERSONA_PRESETS:
        overrides = {
            key: value
            for key, value in profile.items()
            if isinstance(value, str) and value.strip()
        }
        profile = {**PERSONA_PRESETS[preset_name], **overrides}
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
