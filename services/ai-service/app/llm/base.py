"""LLM Provider 统一接口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass
class ToolSpec:
    """注入模型的工具定义（OpenAI function 格式）。"""

    name: str
    description: str
    parameters: dict


@dataclass
class ToolCallRequest:
    """模型请求调用某个工具。"""

    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    """非结构化一轮的结果：文本回复或工具调用。"""

    text: str = ""
    tool_calls: list[ToolCallRequest] | None = None


class LLMProvider(Protocol):
    """流式对话；messages 为 [{role, content}]，role ∈ system/user/assistant。"""

    @property
    def display_name(self) -> str: ...

    async def chat(
        self,
        messages: list[dict],
        *,
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        """非流式一轮；tools 非空时模型可返回工具调用。"""

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...
