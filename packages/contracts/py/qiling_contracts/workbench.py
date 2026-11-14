"""本地工作台配置契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


class WorkbenchItem(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["link", "iframe", "builtin"]
    title: str = Field(min_length=1, max_length=100)
    group: str | None = Field(default=None, max_length=80)
    url: HttpUrl | None = None
    feature_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    visible: bool = True
    order: int = Field(default=0, ge=0, le=10000)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_target(self) -> WorkbenchItem:
        if self.kind in ("link", "iframe") and self.url is None:
            raise ValueError(f"{self.kind} 条目必须提供 HTTP(S) URL")
        if self.kind == "builtin" and self.feature_id is None:
            raise ValueError("builtin 条目必须提供 feature_id")
        if self.kind == "builtin" and self.url is not None:
            raise ValueError("builtin 条目不能提供 URL")
        if self.kind != "builtin" and self.feature_id is not None:
            raise ValueError(f"{self.kind} 条目不能提供 feature_id")
        return self


class WorkbenchSettings(BaseModel):
    items: list[WorkbenchItem] = Field(default_factory=list, max_length=100)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_unique_ids(self) -> WorkbenchSettings:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("workbench 条目 id 必须唯一")
        return self


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkbenchNote(BaseModel):
    note_id: str = Field(default_factory=lambda: f"note_{uuid4().hex[:12]}", pattern=r"^note_[a-f0-9]{12}$")
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(default="", max_length=10000)
    project_path: str | None = Field(default=None, max_length=2000)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    model_config = {"extra": "forbid"}


class WorkbenchTodo(BaseModel):
    todo_id: str = Field(default_factory=lambda: f"todo_{uuid4().hex[:12]}", pattern=r"^todo_[a-f0-9]{12}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    project_path: str | None = Field(default=None, max_length=2000)
    status: Literal["pending", "completed"] = "pending"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    model_config = {"extra": "forbid"}
