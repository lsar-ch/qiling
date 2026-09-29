"""角色呈现桥接：角色切换时广播 PersonaPresentation。

Step 9.5: 统一表现事件流 —— 角色级载荷下发。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.widget import PersonaPresentation

logger = logging.getLogger(__name__)

# 默认主题色（当角色卡未配置 presentation 时回退）
_DEFAULT_THEME = {"primary": "#6366F1", "aura": "#818CF8", "accent": "#C4B5FD"}
_DEFAULT_ANIMATIONS = {
    "breath_rate": 1.0,
    "blink_interval_ms": 4000,
    "idle_action_interval_ms": 8000,
    "transition_ms": 300,
}
_DEFAULT_FX = {
    "thinking_bubble": True,
    "music_note": False,
    "success_sparkle": True,
}


class PresentationBridge:
    """角色切换时广播 PersonaPresentation 到事件总线。"""

    def __init__(self, personas_dir: Path) -> None:
        self._personas_dir = personas_dir
        self._active_persona_id: str | None = None

    def _read_persona(self, persona_id: str) -> dict[str, Any] | None:
        path = self._personas_dir / f"{persona_id}.yaml"
        if not path.is_file():
            logger.warning("persona file not found: %s", path)
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            logger.exception("failed to read persona: %s", path)
            return None

    def _build_presentation(
        self, persona_id: str, raw: dict[str, Any]
    ) -> PersonaPresentation:
        """从角色卡 YAML 构建 PersonaPresentation。

        presentation 块可选；缺失时使用默认值。
        """
        pres = raw.get("presentation", {}) if isinstance(raw, dict) else {}
        theme = {**_DEFAULT_THEME, **pres.get("theme", {})}
        animations = {**_DEFAULT_ANIMATIONS, **pres.get("animations", {})}
        fx = {**_DEFAULT_FX, **pres.get("fx", {})}
        actions = pres.get("actions")
        vrm_motion_config = pres.get("vrm")
        avatar = str(raw.get("avatar") or "")
        vrm_path = str(raw.get("vrm") or "")  # VRM 模型相对 persona 资产目录的路径
        style = pres.get("style")
        if style not in {"human", "animal", "anime"}:
            style = raw.get("motion_family")
        if style not in {"human", "animal", "anime"}:
            style = "animal" if str(raw.get("kind", "")).lower() in {"cat", "dog", "bird", "rabbit", "animal"} else "human"
        motion_family = raw.get("motion_family")
        if motion_family not in {"human", "animal", "anime"}:
            motion_family = style
        art_style = raw.get("art_style")
        if art_style not in {"realistic", "anime", "chibi", "pixel"}:
            art_style = None

        asset: dict[str, Any] = {}
        if avatar:
            asset["avatar_url"] = avatar
        if vrm_path:
            asset["vrm_path"] = vrm_path

        return PersonaPresentation(
            persona_id=persona_id,
            persona_name=raw.get("name", persona_id),
            style=style,
            motion_family=motion_family,
            art_style=art_style,
            theme=theme,
            animations=animations,
            fx=fx,
            actions=actions if isinstance(actions, dict) else None,
            vrm=vrm_motion_config if isinstance(vrm_motion_config, dict) else None,
            asset=asset or None,
        )

    async def broadcast(self, persona_id: str, hub) -> None:
        """读取角色卡配置并通过 EventHub 广播 persona.presentation 事件。"""
        raw = self._read_persona(persona_id)
        if raw is None:
            return

        presentation = self._build_presentation(persona_id, raw)
        envelope = EventEnvelope(
            event_type="persona.presentation",  # type: ignore[arg-type]
            source="system",
            presentation=presentation.model_dump(mode="json"),
        )
        await hub.publish(envelope)
        self._active_persona_id = persona_id
        logger.info(
            "broadcast persona.presentation for %s (%s)",
            persona_id,
            presentation.persona_name,
        )
