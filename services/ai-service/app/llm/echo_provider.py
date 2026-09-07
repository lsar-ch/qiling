"""Echo 演示 Provider：未配置模型 API 时的离线兜底。

规则：
- 消息以「长回复」开头 → 返回多段长文本，用于验证「长回复展开主界面」。
- 其余 → 简短回显，用于验证「短回复气泡」。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.config import Settings

_CHUNK = 8


class EchoProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def display_name(self) -> str:
        return "echo（演示，未配置模型 API）"

    def _build(self, messages: list[dict[str, str]]) -> str:
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = msg["content"]
                break
        if user_text.startswith("长回复"):
            lines = [
                "这是一段用于验证「长回复自动展开主界面」的演示文本。",
                "当前文字对话闭环已打通：文字输入 → LLM Provider → 流式回显 → 会话保存。",
                "后续 Step 4 接入语音后，同样的消息会走 STT/TTS；Step 7 接入记忆后，",
                "这里的内容会沉淀为用户偏好与事实。",
                "如果你已经配置了 OpenAI 兼容模型地址（OPENAI_BASE_URL / OPENAI_API_KEY），",
                "这个演示会被真实模型替换。",
            ]
            return "。\n".join(lines) + "。"
        return f"（演示模式）已收到：{user_text}"

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        text = self._build(messages)
        for i in range(0, len(text), _CHUNK):
            await asyncio.sleep(0.015)
            yield text[i : i + _CHUNK]
