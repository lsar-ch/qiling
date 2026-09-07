"""Agent Adapter 统一接口。

外部执行器统一走 detect/connect/run/cancel/approve。未接入真实执行的
adapter 调用 run 时必须抛出 AgentExecutionUnsupported，不能假装可运行。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from deskmate_contracts.agent import AgentInfo

AgentEventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


class AgentExecutionUnsupported(RuntimeError):
    """Adapter 已探测但执行协议尚未接入。"""


class AgentExecutionError(RuntimeError):
    """真实执行器启动/协议/权限失败；应由运行层标记为 failed。"""


class AgentCancelled(RuntimeError):
    """任务被 DeskMate 主动取消，不再作为普通失败处理。"""


@dataclass
class AgentTaskRequest:
    """交给外部 Agent 的统一任务载荷。"""

    task_id: str
    prompt: str
    cwd: str
    conversation_id: str | None = None
    mode: str = "read-only"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTaskResult:
    """外部 Agent 执行完成后的统一结果。"""

    status: str = "completed"   # completed | failed | cancelled
    message: str = ""
    session_id: str | None = None
    error: str | None = None


class AgentAdapter(ABC):
    """每种外部执行器实现一套探测与执行接口。"""

    name: str = ""
    adapter_id: str = ""
    display_name: str = ""
    executable: bool = False

    @abstractmethod
    async def detect(self) -> AgentInfo:
        """非交互探测本机安装/协议状态，不执行真实 Agent 任务。"""

    async def connect(self) -> None:
        self._unsupported("connect")

    async def run(
        self,
        request: AgentTaskRequest,
        on_update: AgentEventSink,
    ) -> AgentTaskResult:
        self._unsupported("run")

    async def cancel(self, task_id: str, session_id: str | None = None) -> None:
        self._unsupported("cancel")

    async def approve(self, task_id: str, decision: str) -> None:
        self._unsupported("approve")

    def _unsupported(self, method: str) -> None:
        raise AgentExecutionUnsupported(
            f"{self.adapter_id}.{method}() is reserved for future integration; "
            f"{self.display_name} 的真实执行接口尚未接入。"
        )
