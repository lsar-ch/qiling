"""从 AgentCatalog 构建/重建 Agent 注册表。"""

from __future__ import annotations

from app.agents.acp_cli import AcpCliAdapter
from app.agents.browser import BrowserAdapter
from app.agents.catalog import AgentCatalog, load_agent_catalog
from app.agents.codex import CodexAdapter
from app.agents.local_office import LocalOfficeAdapter
from app.agents.registry import AgentRegistry
from app.agents.reserved import PendingAgentAdapter
from app.agents.workbuddy import WorkBuddyAdapter
from app.llm.base import LLMProvider


def build_agent_registry(
    catalog: AgentCatalog | None = None,
    llm_provider: LLMProvider | None = None,
) -> AgentRegistry:
    catalog = catalog or load_agent_catalog()
    registry = AgentRegistry(default_executor=catalog.default_executor or "codex")
    rebuild_agent_registry(registry, catalog, llm_provider)
    return registry


def rebuild_agent_registry(
    registry: AgentRegistry,
    catalog: AgentCatalog,
    llm_provider: LLMProvider | None = None,
) -> None:
    """把目录条目就地重建进现有 registry（保留 registry 对象引用）。"""
    registry.clear()
    registry.default_executor = catalog.default_executor or "codex"
    # 停用条目也注册：页面要显示「已停用」，是否可执行由 runtime 按 enabled 判定。
    for entry in catalog.executors:
        if entry.adapter == "codex":
            registry.register(CodexAdapter(catalog_entry=entry))
        elif entry.adapter == "workbuddy":
            registry.register(WorkBuddyAdapter(catalog_entry=entry))
        elif entry.adapter == "acp-cli":
            registry.register(AcpCliAdapter(catalog_entry=entry))
        elif entry.adapter == "browser":
            registry.register(BrowserAdapter(catalog_entry=entry))
        else:
            registry.register(PendingAgentAdapter(entry))
    # 内置执行器始终注册，不受 agents.yaml 影响；写作能力复用当前生效的模型 provider
    registry.register(LocalOfficeAdapter(llm_provider))
