"""
LLM 客户端：封装与 LLM 的交互。

支持：
- Ollama（本地优先）
- OpenAI 兼容 API（云端备选）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncIterator, Iterator, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """LLM 交互客户端。"""

    def __init__(
        self,
        provider: str = "ollama",
        model: str = "qwen3:8b",
        base_url: str = "http://localhost:11434",
        api_key: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 512,
    ):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None

        logger.info(f"LLMClient initialized: provider={provider}, model={model}")

    def _get_client(self):
        """延迟初始化底层客户端。"""
        if self._client is not None:
            return self._client

        if self.provider == "ollama":
            try:
                import ollama
                self._client = ollama.Client(host=self.base_url)
                logger.info(f"Ollama client connected to {self.base_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Ollama: {e}")
                raise
        elif self.provider == "openai":
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key or "ollama",
                )
                logger.info(f"OpenAI client initialized (base_url={self.base_url})")
            except Exception as e:
                logger.error(f"Failed to init OpenAI client: {e}")
                raise
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        return self._client

    def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
    ) -> str | Iterator[str]:
        """发送对话请求。

        Args:
            messages: [{"role": "user"|"assistant"|"system", "content": "..."}]
            stream: 是否流式返回
        Returns:
            完整响应文本，或生成器（如果 stream=True）
        """
        client = self._get_client()

        # 注入系统提示
        if self.system_prompt and not any(m.get("role") == "system" for m in messages):
            messages = [{"role": "system", "content": self.system_prompt}] + messages

        if self.provider == "ollama":
            return self._ollama_chat(client, messages, stream)
        elif self.provider == "openai":
            return self._openai_chat(client, messages, stream)
        raise ValueError(f"Unknown provider: {self.provider}")

    def _ollama_chat(
        self,
        client,
        messages: list[dict],
        stream: bool,
    ) -> str | Iterator[str]:
        if stream:
            response = client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            )
            def gen():
                for chunk in response:
                    yield chunk["message"]["content"]
            return gen()
        else:
            response = client.chat(
                model=self.model,
                messages=messages,
                stream=False,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            )
            return response["message"]["content"]

    def _openai_chat(
        self,
        client,
        messages: list[dict],
        stream: bool,
    ) -> str | Iterator[str]:
        if stream:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            def gen():
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            return gen()
        else:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return response.choices[0].message.content

    def load_system_prompt(self, path: str | Path) -> None:
        """从文件加载系统提示。"""
        path = Path(path)
        if path.exists():
            self.system_prompt = path.read_text(encoding="utf-8")
            logger.info(f"System prompt loaded from {path} ({len(self.system_prompt)} chars)")
        else:
            logger.warning(f"System prompt file not found: {path}")
