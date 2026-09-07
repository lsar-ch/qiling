"""
UI 控制器：管理精灵窗口的创建、位置、交互。
基于 PyQt6，支持透明 Always-on-Top 窗口。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, QSize
from PyQt6.QtGui import QPainter, QColor, QMovie
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)


class FloatController(QWidget):
    """浮动精灵主窗口。

    初始版本使用圆形/椭圆形透明窗口，后续可替换为 Live2D 渲染器。
    """

    # 自定义信号
    clicked = ...
    double_clicked = ...

    def __init__(
        self,
        size: QSize = QSize(120, 120),
        position: str = "center",
        always_on_top: bool = True,
        opacity: float = 0.95,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._position = position
        self._opacity = opacity
        self._state = "idle"  # idle | listening | speaking | thinking

        # ── 窗口设置 ──────────────────────────────────────────────
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | (Qt.WindowType.WindowStaysOnTopHint if always_on_top else 0)
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.resize(size)

        # ── 状态动画计时器 ────────────────────────────────────────
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)  # ~30fps
        self._anim_timer.timeout.connect(self._tick_animation)
        self._anim_timer.start()
        self._anim_frame = 0

        # ── 初始位置 ──────────────────────────────────────────────
        self._move_to_position(position)

        logger.info(f"FloatController created: {size} @ {position}")

    # ── 状态管理 ─────────────────────────────────────────────────
    def set_state(self, state: str) -> None:
        """切换精灵状态：idle / listening / speaking / thinking"""
        old = self._state
        self._state = state
        logger.debug(f"State: {old} → {state}")
        self.update()

    # ── 位置 ─────────────────────────────────────────────────────
    def _move_to_position(self, position: str) -> None:
        screen = QApplication.primaryScreen().geometry()
        margin = 20
        if position == "center":
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
        elif position == "bottom-right":
            x = screen.right() - self.width() - margin
            y = screen.bottom() - self.height() - margin
        elif position == "top-right":
            x = screen.right() - self.width() - margin
            y = screen.top() + margin
        elif position == "bottom-left":
            x = screen.left() + margin
            y = screen.bottom() - self.height() - margin
        else:
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
        self.move(x, y)

    # ── 动画循环 ─────────────────────────────────────────────────
    def _tick_animation(self) -> None:
        self._anim_frame += 1
        self.update()

    # ── 绘制 ─────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        cx, cy = self.width() // 2, self.height() // 2
        r = min(cx, cy) - 2

        # 状态颜色
        colors = {
            "idle": QColor(80, 140, 255),       # 蓝色
            "listening": QColor(255, 140, 60),  # 橙色
            "speaking": QColor(80, 220, 140),   # 绿色
            "thinking": QColor(160, 120, 255),  # 紫色
        }
        base_color = colors.get(self._state, colors["idle"])

        # 呼吸效果（idle 状态）
        breathe = 1.0 + 0.03 * self._anim_frame % 60 / 60 * (
            1 if (self._anim_frame // 60) % 2 == 0 else -1
        )

        # 涟漪效果（listening 状态）
        if self._state == "listening":
            ripple_phase = (self._anim_frame * 2) % 60
            for i in range(3):
                ring_r = r + 8 + ripple_phase + i * 12
                alpha = max(0, 60 - i * 20 - ripple_phase // 3)
                ring_color = QColor(base_color)
                ring_color.setAlpha(alpha)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(ring_color, 2))
                painter.drawEllipse(
                    cx - int(ring_r), cy - int(ring_r),
                    int(ring_r * 2), int(ring_r * 2)
                )

        # 主圆
        painter.setBrush(base_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            cx - int(r * breathe), cy - int(r * breathe),
            int(r * breathe * 2), int(r * breathe * 2)
        )

        # 表情（idle 状态画眼睛）
        if self._state == "idle":
            eye_color = QColor(255, 255, 255)
            eye_r = 6
            left_eye_x = cx - int(r * 0.35 * breathe)
            right_eye_x = cx + int(r * 0.35 * breathe)
            painter.setBrush(eye_color)
            painter.drawEllipse(left_eye_x - eye_r, cy - 6 - eye_r, eye_r * 2, eye_r * 2)
            painter.drawEllipse(right_eye_x - eye_r, cy - 6 - eye_r, eye_r * 2, eye_r * 2)

        painter.end()

    # ── 鼠标事件 ─────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self._last_click_time = getattr(self, "_last_click_time", 0)
            import time
            now = time.time()
            if now - self._last_click_time < 0.3:
                self.double_clicked.emit()
            self._last_click_time = now
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        # 拖动
        if event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition() - event.previousGlobalPosition()
            self.move(self.x() + int(delta.x()), self.y() + int(delta.y()))
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        # 右键弹出菜单
        from PyQt6.QtWidgets import QMenu, QAction
        menu = QMenu(self)
        menu.addAction(QAction("语音对话", self, triggered=lambda: self.set_state("listening")))
        menu.addAction(QAction("休眠", self))
        menu.exec(event.globalPos())

    # ── 拖拽区域限制（不离开屏幕） ──────────────────────────────
    def move(self, x: int, y: int) -> bool:
        screen = QApplication.primaryScreen().geometry()
        x = max(screen.left(), min(x, screen.right() - self.width()))
        y = max(screen.top(), min(y, screen.bottom() - self.height()))
        return super().move(x, y)
