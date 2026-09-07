"""
渲染器抽象层：统一精灵的视觉表现。

目前实现：SpriteRenderer（简易精灵渲染）
扩展点：后续可添加 Live2DRenderer、VRMRenderer
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BaseRenderer(ABC):
    """渲染器基类，所有视觉实现必须继承。"""

    @abstractmethod
    def render(self, state: str, frame: int, extras: dict[str, Any] | None = None) -> None:
        ...

    @abstractmethod
    def dispose(self) -> None:
        ...


class SpriteRenderer(BaseRenderer):
    """当前使用的简单精灵渲染器。

    使用 PyQt6 QPainter 绘制圆形/椭圆形精灵，
    根据状态切换颜色和简单动画。
    """

    def __init__(self, widget) -> None:
        self._widget = widget
        logger.info("SpriteRenderer initialized")

    def render(self, state: str, frame: int, extras: dict[str, Any] | None = None) -> None:
        extras = extras or {}
        self._widget.set_state(state)
        # 可扩展：根据 extras 中的参数调整渲染（表情、姿势等）

    def dispose(self) -> None:
        pass


# ── 渲染器工厂 ──────────────────────────────────────────────────
def create_renderer(widget, mode: str = "sprite") -> BaseRenderer:
    """根据 mode 创建对应的渲染器。"""
    if mode == "sprite":
        return SpriteRenderer(widget)
    elif mode == "live2d":
        logger.warning("Live2D renderer not yet implemented")
        return SpriteRenderer(widget)  # fallback
    else:
        raise ValueError(f"Unknown renderer mode: {mode}")
