"""技能（Skill）与 MCP 扩展契约。

Skill 描述"怎么做"（按需加载的指令包），MCP 描述"能做什么"（标准协议工具）。
本文件只定义数据结构；行为接入见 docs/EXTENSION-SKELETON-PLAN.md。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ExtensionSource = Literal["builtin", "user"]


class SkillInfo(BaseModel):
    """技能摘要：模型据此选择技能，不含正文。"""

    id: str
    name: str
    description: str
    source: ExtensionSource
    enabled: bool = True
    triggers: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    has_scripts: bool = False

    model_config = {"extra": "forbid"}


class SkillDetail(BaseModel):
    """技能详情：摘要字段 + SKILL.md 正文。"""

    id: str
    name: str
    description: str
    source: ExtensionSource
    enabled: bool = True
    triggers: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    has_scripts: bool = False
    body: str = ""

    model_config = {"extra": "forbid"}


McpTransport = Literal["stdio", "streamablehttp"]
McpServerStatus = Literal["not_started", "ready", "error", "disabled"]
McpToolAccess = Literal["read", "write"]


class McpToolInfo(BaseModel):
    """MCP 工具：名称、说明与读写属性。"""

    name: str
    description: str
    access: McpToolAccess

    model_config = {"extra": "forbid"}


class McpServerInfo(BaseModel):
    """MCP 服务器配置与运行状态；env 密钥不随本结构返回。"""

    id: str
    source: ExtensionSource
    enabled: bool
    transport: McpTransport
    status: McpServerStatus
    access: McpToolAccess
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    tool_count: int = 0
    detail: str = ""

    model_config = {"extra": "forbid"}
