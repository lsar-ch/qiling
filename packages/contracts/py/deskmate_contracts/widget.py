"""挂件状态契约（对应 docs/V1-INTERFACES.md §7）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
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
