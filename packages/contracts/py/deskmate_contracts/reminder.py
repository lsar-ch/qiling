"""主动提醒契约（久坐 / 长工作 / 任务 / 备忘录）。

这是挂件主动提醒的持久化模型，与任务系统解耦：
- kind=memo：用户口头或手动创建的备忘录提醒
- kind=task：与具体任务/待办相关的到点提醒
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ReminderKind = Literal["memo", "task"]
ReminderRepeat = Literal["none", "daily", "weekly", "monthly"]
ReminderStatus = Literal["pending", "done", "cancelled"]


def create_reminder_id() -> str:
    return f"rem_{uuid4().hex[:10]}"


class Reminder(BaseModel):
    reminder_id: str = Field(default_factory=create_reminder_id)
    kind: ReminderKind = "memo"
    text: str = Field(min_length=1, max_length=500)
    remind_at: str = Field(min_length=1, description="ISO 8601 时间，到点触发")
    repeat: ReminderRepeat = "none"
    status: ReminderStatus = "pending"
    task_id: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}
