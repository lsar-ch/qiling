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


class ChatAttachment(BaseModel):
    """对话附件元数据；文件已由上传接口落盘到 DeskMate 数据目录。"""

    name: str
    path: str
    size: int = 0
    mime: str = "application/octet-stream"

    model_config = {"extra": "forbid"}


class ConversationMessage(BaseModel):
    id: str = Field(default_factory=lambda: f"msg_{uuid4().hex[:10]}")
    role: MessageRole
    content: str
    modality: Literal["text", "voice"] = "text"
    attachments: list[ChatAttachment] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}


class Conversation(BaseModel):
    conversation_id: str = Field(default_factory=lambda: f"conv_{uuid4().hex[:10]}")
    title: str = "新对话"
    model_profile_id: str | None = None
    # 绑定的项目目录（绝对路径）；为空即普通对话。
    project: str | None = None
    # 用户可见的项目名称；为空时前端可用 project 的目录名回填。
    project_name: str | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}
