"""项目节点契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ProjectNodeKind = Literal[
    "project",
    "phase",
    "node",
    "task",
    "artifact",
    "decision",
    "blocker",
    "next_step",
]

ProjectNodeStatus = Literal[
    "planned",
    "in_progress",
    "completed",
    "blocked",
    "pending_confirmation",
    "cancelled",
]


def create_project_node_id() -> str:
    return f"node_{uuid4().hex[:10]}"


class ProjectNode(BaseModel):
    node_id: str = Field(default_factory=create_project_node_id)
    project: str
    title: str = Field(min_length=1, max_length=200)
    kind: ProjectNodeKind = "node"
    status: ProjectNodeStatus = "planned"
    parent_id: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    decision: str | None = None
    blocker: str | None = None
    next_step: str | None = None
    source: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}
