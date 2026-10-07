"""把历史对话裁剪成模型上下文（system + 尾部尽量多的消息）。"""

from __future__ import annotations

from qiling_contracts.conversation import Conversation


def build_llm_messages(
    system_prompt: str,
    conversation: Conversation,
    *,
    budget_chars: int = 8000,
    memory_context: str = "",
    skill_context: str = "",
) -> list[dict[str, str]]:
    prompt = system_prompt
    if memory_context.strip():
        prompt = f"{system_prompt}\n\n## 项目记忆（只读上下文）\n{memory_context.strip()}"
    if skill_context.strip():
        prompt = f"{prompt}\n\n## 本轮技能指引（按需采用）\n{skill_context.strip()}"
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
        # tool（任务进展/结果）不是模型协议的 tool 消息，按助理口吻并入上下文
        role = msg.role if msg.role in ("system", "user", "assistant") else "assistant"
        tail.append({"role": role, "content": msg.content})
        used += size
    messages.extend(reversed(tail))
    return messages
