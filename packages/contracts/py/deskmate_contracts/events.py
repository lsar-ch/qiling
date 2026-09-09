"""统一事件信封（EventEnvelope v0.1）。

对应 docs/V1-INTERFACES.md §3；广播经 WS /api/events。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
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
    # 记忆
    "memory.created",
    "memory.updated",
    "memory.entry.deleted",
    # 系统
    "system.health",
    "system.error",
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
    "memory.created",
    "memory.updated",
    "memory.entry.deleted",
    "system.health",
    "system.error",
)


def new_event_id() -> str:
    """生成形如 evt_<uuid4-hex12> 的事件 id。"""
    return f"evt_{uuid4().hex[:12]}"


class EventEnvelope(BaseModel):
    """所有模块之间传递事件的统一结构。"""

    event_id: str = Field(default_factory=new_event_id)
    event_type: EventType
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    conversation_id: str | None = None
    task_id: str | None = None
    source: EventSource
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    def to_ws_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
