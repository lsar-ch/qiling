"""挂件状态契约（对应 docs/V1-INTERFACES.md §7）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

WidgetState = Literal[
    "idle",               # 空闲
    "listening",          # 聆听中
    "thinking",           # 思考中
    "speaking",           # 说话中
    "executing",          # 任务执行中
    "awaiting_approval",  # 等待授权
    "completed",          # 完成（可带 message）
    "interrupted",        # 被打断
]
PersonaStyle = Literal["human", "animal"]

_STATE_LABELS_ZH: dict[str, str] = {
    "idle": "空闲",
    "listening": "聆听中",
    "thinking": "思考中",
    "speaking": "说话中",
    "executing": "执行中",
    "awaiting_approval": "等待确认",
    "completed": "已完成",
    "interrupted": "已打断",
}


def state_label_zh(state: WidgetState) -> str:
    return _STATE_LABELS_ZH.get(state, state)


class WidgetStatusReport(BaseModel):
    """挂件状态上报：状态变化必须来自系统事件，不能由模型自由发挥。"""

    report_id: str = Field(default_factory=lambda: f"wrep_{uuid4().hex[:10]}")
    state: WidgetState
    task_id: str | None = None
    message: str | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}

# ── Step 9.5: 统一表现事件流 ────────────────────────────────────────────

ExpressionEmotion = Literal[
    "neutral",    # 空闲/默认
    "attentive",  # 聆听中
    "thinking",   # 思考中
    "confused",   # 需要确认
    "success",    # 任务成功/对话完成
    "error",      # 任务失败/错误
]

BubbleStyle = Literal["info", "success", "warning", "error"]


class ExpressionBubble(BaseModel):
    """可选气泡载荷，由后端 runtime 生成。"""

    text: str = Field(max_length=240)
    duration_ms: int = Field(ge=500, default=3000)
    style: BubbleStyle = "info"

    model_config = {"extra": "forbid"}


class ExpressionEvent(BaseModel):
    """表现事件：每个程序事件发生时广播的动态载荷。

    与 WidgetStatusReport 的区别：
    - ExpressionEvent 增加了 emotion / bubble，面向挂件渲染
    - WidgetStatusReport 保留用于 /api/widget/state 等简单查询
    """

    state: WidgetState
    task_id: str | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    emotion: ExpressionEmotion = "neutral"
    bubble: ExpressionBubble | None = None

    model_config = {"extra": "forbid"}


class PersonaPresentation(BaseModel):
    """角色呈现：角色切换或首次连接时下发。

    载荷轻量（不含资产路径/锚点），高频下发；资产文件走 layers.json 单独加载。
    """

    persona_id: str = Field(min_length=1, max_length=64)
    persona_name: str = Field(min_length=1, max_length=40)
    style: PersonaStyle = "human"

    theme: dict[str, str] = Field(
        default_factory=lambda: {
            "primary": "#6366F1",
            "aura": "#818CF8",
            "accent": "#C4B5FD",
        }
    )

    animations: dict[str, float | int] = Field(
        default_factory=lambda: {
            "breath_rate": 1.0,
            "blink_interval_ms": 4000,
            "idle_action_interval_ms": 8000,
            "transition_ms": 300,
        }
    )

    fx: dict[str, bool] = Field(
        default_factory=lambda: {
            "thinking_bubble": True,
            "music_note": False,
            "success_sparkle": True,
        }
    )

    asset: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}
