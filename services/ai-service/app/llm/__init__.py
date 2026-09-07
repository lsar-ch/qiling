"""LLM Provider 适配层（对应 docs/VOICE-PIPELINE.md 模型接口）。"""

from __future__ import annotations

from app.config import Settings, resolve_llm_provider
from app.llm.base import LLMProvider
from app.llm.echo_provider import EchoProvider
from app.llm.openai_provider import OpenAICompatibleProvider


def create_provider(settings: Settings) -> LLMProvider:
    name = resolve_llm_provider(settings)
    if name == "openai":
        return OpenAICompatibleProvider(settings)
    return EchoProvider(settings)


__all__ = ["LLMProvider", "create_provider"]
