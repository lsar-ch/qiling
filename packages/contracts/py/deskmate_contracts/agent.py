"""Agent 探测与可用性契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentIntegrationStatus = Literal["ready", "pending", "auth_required", "not_installed", "error"]


class AgentInfo(BaseModel):
    """统一 Agent 对外状态；探测只描述安装/接入状态，不代表真实任务已执行。"""

    name: str
    label: str
    adapter: str
    integration_status: AgentIntegrationStatus
    available: bool
    enabled: bool = True
    # 是否允许作为兜底默认执行器：需可真实执行且非窄场景。
    default_eligible: bool = True
    version: str | None = None
    command: str | None = None
    protocol: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    detail: str = ""

    model_config = {"extra": "forbid"}
