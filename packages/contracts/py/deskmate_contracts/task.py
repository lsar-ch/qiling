"""任务结构契约（对应 docs/V1-INTERFACES.md §6）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

TaskCategory = Literal[
    "answer",              # 纯问答
    "execute_frontend",    # 前台可执行
    "delegate_backend",    # 交给后台智能体
    "request_approval",    # 需先授权
]

WorkKind = Literal[
    "general",
    "code",
    "browser",
    "word",
    "excel",
    "ppt",
    "pdf",
    "image",
    "email",
    "project",
]

InteractionKind = Literal["casual", "project", "work"]

RiskLevel = Literal["low", "medium", "high"]

TaskStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
]


def create_task_id() -> str:
    return f"task_{uuid4().hex[:10]}"


class Task(BaseModel):
    task_id: str = Field(default_factory=create_task_id)
    conversation_id: str | None = None
    project: str | None = None
    input: str
    category: TaskCategory = "answer"
    work_kind: WorkKind = "general"
    interaction_kind: InteractionKind = "casual"
    risk_level: RiskLevel = "low"
    complexity: Literal["simple", "medium", "complex"] = "simple"
    estimated_duration: Literal["short", "medium", "long"] = "short"
    required_approval: bool = False
    preferred_executor: str | None = None  # 如 codex / claude-code / deepseek-harness
    status: TaskStatus = "queued"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}
