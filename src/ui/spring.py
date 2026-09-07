"""
Spring 物理效果：精灵被拖动后松开会弹性回弹到目标位置。
参考 morettt/my-neuro 的拖拽交互设计。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SpringConfig:
    stiffness: float = 0.08    # 弹性系数（越大越硬）
    damping: float = 0.85      # 阻尼系数（越小衰减越快）
    max_velocity: float = 50.0 # 最大速度
    settle_threshold: float = 0.5  # 认为已静止的阈值


class Spring:
    """单轴弹簧物理模拟。"""

    def __init__(self, config: SpringConfig | None = None):
        self.config = config or SpringConfig()
        self.position = 0.0
        self.velocity = 0.0
        self.target = 0.0

    def set_target(self, target: float) -> None:
        self.target = target

    def update(self) -> float:
        displacement = self.position - self.target
        force = -self.config.stiffness * displacement
        self.velocity = (self.velocity + force) * self.config.damping
        self.velocity = max(
            -self.config.max_velocity,
            min(self.config.max_velocity, self.velocity),
        )
        self.position += self.velocity
        return self.position

    def is_settled(self) -> bool:
        return (
            abs(self.position - self.target) < self.config.settle_threshold
            and abs(self.velocity) < self.config.settle_threshold
        )


class PositionSpring:
    """二维弹簧，用于控制精灵位置。"""

    def __init__(self, config: SpringConfig | None = None):
        self.x = Spring(config)
        self.y = Spring(config)
        self.config = config or SpringConfig()

    def set_target(self, x: float, y: float) -> None:
        self.x.set_target(x)
        self.y.set_target(y)

    def update(self) -> tuple[float, float]:
        return self.x.update(), self.y.update()

    def is_settled(self) -> bool:
        return self.x.is_settled() and self.y.is_settled()
