"""Agent 注册表：统一探测、聚合可用状态并隔离单点异常。"""

from __future__ import annotations

import asyncio

from deskmate_contracts.agent import AgentInfo

from app.agents.base import AgentAdapter


class AgentRegistry:
    def __init__(self, default_executor: str | None = None) -> None:
        self._adapters: dict[str, AgentAdapter] = {}
        self.default_executor = default_executor or "codex"

    def register(self, adapter: AgentAdapter) -> None:
        if not adapter.name:
            raise ValueError("AgentAdapter.name is required")
        self._adapters[adapter.name] = adapter

    def clear(self) -> None:
        """清空已注册适配器（供目录重载后就地重建，避免旧引用失效）。"""
        self._adapters.clear()

    def get(self, name: str) -> AgentAdapter | None:
        return self._adapters.get(name)

    def names(self) -> list[str]:
        return list(self._adapters)

    async def detect(self, name: str) -> AgentInfo:
        adapter = self.get(name)
        if adapter is None:
            raise KeyError(name)
        try:
            return await adapter.detect()
        except Exception as exc:
            return self._error_info(adapter, exc)

    async def detect_all(self) -> list[AgentInfo]:
        adapters = list(self._adapters.values())
        if not adapters:
            return []
        results = await asyncio.gather(
            *(adapter.detect() for adapter in adapters),
            return_exceptions=True,
        )
        return [
            self._error_info(adapter, item) if isinstance(item, BaseException) else item
            for adapter, item in zip(adapters, results)
        ]

    @staticmethod
    def _error_info(adapter: AgentAdapter, exc: BaseException) -> AgentInfo:
        return AgentInfo(
            name=adapter.name,
            label=adapter.display_name,
            adapter=adapter.adapter_id,
            integration_status="error",
            available=False,
            detail=f"Agent detection failed / Agent 探测失败：{exc}",
        )
