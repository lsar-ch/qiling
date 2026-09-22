"""统一事件信封（EventEnvelope v0.1）。

对应 docs/V1-INTERFACES.md §3；广播经 WS /api/events。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

# 事件来源（发出方）
EventSource = Literal[
    "conversation",  # 对话链路
    "speech",        # STT / TTS / VAD / 打断
    "task",          # 任务编排
    "agent_router",  # Agent Router / 外部智能体
    "memory",        # 记忆模块
    "widget",        # 挂件
    "system",        # 系统级
]

EventType = Literal[
    # 对话
    "conversation.input",
    "conversation.transcript",
    "conversation.response",
    "conversation.completed",
    # 语音
    "speech.started",
    "speech.stopped",
    "speech.interrupted",
    # 任务
    "task.classified",
    "task.started",
    "task.progress",
    "task.approval_required",
    "task.completed",
    "task.failed",
    "task.cancelled",
    "task.approval_reminder",
    "task.timed_out",
    "task.stale",
    # 项目监督
    "project.blocked",
    "project.milestone",
    # 主动提醒
    "reminder.triggered",
    "widget.activity",
    # 记忆
    "memory.created",
    "memory.updated",
    "memory.entry.deleted",
    # 系统
    "system.health",
    "system.error",
    "voice.lease.changed",
    # 角色呈现
    "persona.presentation",
]

KNOWN_EVENT_TYPES: tuple[str, ...] = (
    "conversation.input",
    "conversation.transcript",
    "conversation.response",
    "conversation.completed",
    "speech.started",
    "speech.stopped",
    "speech.interrupted",
    "task.classified",
    "task.started",
    "task.progress",
    "task.approval_required",
    "task.completed",
    "task.failed",
    "task.cancelled",
    "task.approval_reminder",
    "task.timed_out",
    "task.stale",
    "project.blocked",
    "project.milestone",
    "reminder.triggered",
    "widget.activity",
    "memory.created",
    "memory.updated",
    "memory.entry.deleted",
    "system.health",
    "system.error",
    "persona.presentation",
)


def new_event_id() -> str:
    """生成形如 evt_<uuid4-hex12> 的事件 id。"""
    return f"evt_{uuid4().hex[:12]}"


class EventEnvelope(BaseModel):
    """所有模块之间传递事件的统一结构。

    Step 9.5: expression / presentation 为可选的扩展载荷；
    老客户端对多余 JSON 字段容错。
    """

    event_id: str = Field(default_factory=new_event_id)
    event_type: EventType
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    conversation_id: str | None = None
    task_id: str | None = None
    source: EventSource
    payload: dict[str, Any] = Field(default_factory=dict)
    expression: Optional[dict[str, Any]] = None
    presentation: Optional[dict[str, Any]] = None

    model_config = {"extra": "forbid"}

    def to_ws_dict(self) -> dict[str, Any]:
        result = self.model_dump(mode="json", exclude_none=True)
        return result
