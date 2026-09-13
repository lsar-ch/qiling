"""对话结构契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MessageRole = Literal["user", "assistant", "system", "tool"]

_ROLE_LABELS_ZH: dict[str, str] = {
    "user": "用户",
    "assistant": "助理",
    "system": "系统",
    "tool": "工具",
}


def role_label_zh(role: MessageRole) -> str:
    return _ROLE_LABELS_ZH.get(role, role)


class ConversationMessage(BaseModel):
    id: str = Field(default_factory=lambda: f"msg_{uuid4().hex[:10]}")
    role: MessageRole
    content: str
    modality: Literal["text", "voice"] = "text"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}


class Conversation(BaseModel):
    conversation_id: str = Field(default_factory=lambda: f"conv_{uuid4().hex[:10]}")
    title: str = "新对话"
    model_profile_id: str | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}
