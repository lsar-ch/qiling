"""授权请求契约（对应 docs/V1-INTERFACES.md §11）。

高风险操作必须获得授权才能执行；授权对象是一次具体动作，而不是整个任务。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]
ApprovalDecision = Literal["approved", "rejected"]


def _default_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()


class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: f"approval_{uuid4().hex[:10]}")
    task_id: str | None = None
    action: str                      # 如 delete_files / open_browser / click_desktop
    description: str                 # 用自然语言描述将被执行的操作
    risk_level: Literal["medium", "high"] = "high"
    expires_at: str = Field(default_factory=_default_expiry)
    status: ApprovalStatus = "pending"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    model_config = {"extra": "forbid"}

    @property
    def is_expired(self) -> bool:
        try:
            return datetime.fromisoformat(self.expires_at) < datetime.now(timezone.utc)
        except ValueError:
            return False
