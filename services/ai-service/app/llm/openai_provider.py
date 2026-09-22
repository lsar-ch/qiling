"""OpenAI 兼容 Chat Completions 流式 Provider。"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from app.config import Settings
from app.llm.base import ChatResult, ToolCallRequest, ToolSpec


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        self._url = f"{base}/chat/completions"
        self._headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            self._headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    @property
    def display_name(self) -> str:
        return f"openai-compatible / {self._settings.llm_model or '未设置模型'}"

    async def chat(
        self,
        messages: list[dict],
        *,
        tools: list[ToolSpec] | None = None,
    ) -> ChatResult:
        payload: dict = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": self._settings.llm_temperature,
            "max_tokens": self._settings.llm_max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "description": item.description,
                        "parameters": item.parameters,
                    },
                }
                for item in tools
            ]
            payload["tool_choice"] = "auto"
        if not payload["model"]:
            raise RuntimeError("未配置模型名称（OPENAI_MODEL）")
        timeout = httpx.Timeout(self._settings.llm_timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(self._url, headers=self._headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"模型接口 {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        raw_calls = message.get("tool_calls") or []
        if raw_calls:
            calls: list[ToolCallRequest] = []
            for item in raw_calls:
                function = item.get("function", {})
                raw_args = function.get("arguments", "{}")
                try:
                    arguments = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    arguments = {}
                calls.append(
                    ToolCallRequest(
                        id=str(item.get("id", "")),
                        name=str(function.get("name", "")),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
            return ChatResult(text=message.get("content", "") or "", tool_calls=calls)
        return ChatResult(text=message.get("content", "") or "")

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": (
                temperature
                if temperature is not None
                else self._settings.llm_temperature
            ),
            "max_tokens": max_tokens or self._settings.llm_max_tokens,
            "stream": True,
        }
        if not payload["model"]:
            raise RuntimeError("未配置模型名称（OPENAI_MODEL）")
        timeout = httpx.Timeout(self._settings.llm_timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", self._url, headers=self._headers, json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")
                    raise RuntimeError(f"模型接口 {resp.status_code}: {body[:200]}")
                async for raw in resp.aiter_lines():
                    if not raw.startswith("data:"):
                        continue
                    data = raw[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = (
                            obj.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        )
                    except json.JSONDecodeError:
                        continue
                    if delta:
                        yield delta
