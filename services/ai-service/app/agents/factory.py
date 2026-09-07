"""从 AgentCatalog 构建默认 Agent 注册表。"""

from __future__ import annotations

from app.agents.catalog import AgentCatalog, load_agent_catalog
from app.agents.codex import CodexAdapter
from app.agents.registry import AgentRegistry
from app.agents.reserved import PendingAgentAdapter


def build_agent_registry(catalog: AgentCatalog | None = None) -> AgentRegistry:
    catalog = catalog or load_agent_catalog()
    registry = AgentRegistry(default_executor=catalog.default_executor or "codex")
    for entry in catalog.executors:
        if not entry.enabled:
            continue
        if entry.adapter == "codex":
            registry.register(CodexAdapter(catalog_entry=entry))
        else:
            registry.register(PendingAgentAdapter(entry))
    return registry
