"""把历史对话裁剪成模型上下文（system + 尾部尽量多的消息）。"""

from __future__ import annotations

from deskmate_contracts.conversation import Conversation


def build_llm_messages(
    system_prompt: str,
    conversation: Conversation,
    *,
    budget_chars: int = 8000,
    memory_context: str = "",
) -> list[dict[str, str]]:
    prompt = system_prompt
    if memory_context.strip():
        prompt = f"{system_prompt}\n\n## 项目记忆（只读上下文）\n{memory_context.strip()}"
    messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
    budget = budget_chars
    if prompt:
        budget -= len(prompt)
    tail: list[dict[str, str]] = []
    used = 0
    for msg in reversed(conversation.messages):
        size = len(msg.content) + 16
        if used + size > budget:
            break
        tail.append({"role": msg.role, "content": msg.content})
        used += size
    messages.extend(reversed(tail))
    return messages
