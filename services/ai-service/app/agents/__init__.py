"""Agent 适配层：探测、注册、真实执行与未来执行器接入。"""

from app.agents.base import (
    AgentAdapter,
    AgentCancelled,
    AgentExecutionError,
    AgentExecutionUnsupported,
    AgentTaskRequest,
    AgentTaskResult,
)
from app.agents.catalog import AgentCatalog, AgentCatalogEntry, AgentCatalogError, load_agent_catalog
from app.agents.codex import CodexAdapter
from app.agents.factory import build_agent_registry
from app.agents.registry import AgentRegistry
from app.agents.reserved import PendingAgentAdapter
from app.agents.runtime import AgentRun, AgentRunManager, AgentRunStore
from app.agents.workbuddy import WorkBuddyAdapter

__all__ = [
    "AgentAdapter",
    "AgentCatalog",
    "AgentCatalogEntry",
    "AgentCatalogError",
    "AgentCancelled",
    "AgentExecutionError",
    "AgentRun",
    "AgentRunManager",
    "AgentRunStore",
    "AgentTaskRequest",
    "AgentTaskResult",
    "AgentExecutionUnsupported",
    "AgentRegistry",
    "CodexAdapter",
    "PendingAgentAdapter",
    "WorkBuddyAdapter",
    "build_agent_registry",
    "load_agent_catalog",
]
