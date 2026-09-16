"""预留但尚未接入的外部 Agent 适配器。

这类适配器只做非侵入式命令探测，不执行 --version，也不启动 Agent。
"""

from __future__ import annotations

import shutil

from deskmate_contracts.agent import AgentInfo

from app.agents.base import AgentAdapter
from app.agents.catalog import AgentCatalogEntry


class PendingAgentAdapter(AgentAdapter):
    """根据 catalog entry 探测命令并返回 pending/not_installed 状态。"""

    def __init__(self, entry: AgentCatalogEntry) -> None:
        self.entry = entry
        self.name = entry.name
        self.adapter_id = entry.adapter or entry.name
        self.display_name = entry.label or entry.name

    async def detect(self) -> AgentInfo:
        command = self._first_existing_command()
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.entry.adapter or self.entry.name,
            integration_status="pending" if command else "not_installed",
            available=command is not None,
            enabled=self.entry.enabled,
            default_eligible=False,
            command=command,
            protocol=self.entry.protocol,
            capabilities=list(self.entry.capabilities),
            tags=list(self.entry.tags),
            source_url=self.entry.source_url,
            detail=self.entry.detail
            or f"{self.display_name} 已预留；命令安装后可进入待接入状态。",
        )

    def _first_existing_command(self) -> str | None:
        configured = self.entry.config.get(f"{self.name}_command") or self.entry.config.get("command")
        commands = [str(configured)] if configured else self.entry.commands
        for command in commands:
            if shutil.which(command):
                return command
        return None
