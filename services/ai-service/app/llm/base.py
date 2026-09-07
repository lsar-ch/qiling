"""LLM Provider 统一接口。"""

from __future__ import annotations

from typing import AsyncIterator, Protocol


class LLMProvider(Protocol):
    """流式对话；messages 为 [{role, content}]，role ∈ system/user/assistant。"""

    @property
    def display_name(self) -> str: ...

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...
