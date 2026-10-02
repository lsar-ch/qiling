"""流式 provider：尾片空 choices 不得中断或覆盖已产出的内容。"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.llm import openai_provider
from app.llm.openai_provider import OpenAICompatibleProvider


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self.status_code = status_code
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b""


class _FakeStreamCtx:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeAsyncClient:
    lines: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def stream(self, method, url, headers=None, json=None):
        return _FakeStreamCtx(_FakeStreamResponse(type(self).lines))


def _drain(provider: OpenAICompatibleProvider) -> list[str]:
    async def run() -> list[str]:
        return [
            chunk
            async for chunk in provider.stream_chat(
                [{"role": "user", "content": "hi"}]
            )
        ]

    return asyncio.run(run())


def test_stream_chat_ignores_empty_choices_tail(monkeypatch) -> None:
    monkeypatch.setattr(openai_provider.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.lines = [
        'data: {"choices":[{"delta":{"content":"\u4f60\u597d"}}]}',
        'data: {"choices":[{"delta":{"content":"\u4e16\u754c"}}]}',
        'data: {"choices":[],"usage":{"total_tokens":9}}',
        "data: [DONE]",
    ]
    provider = OpenAICompatibleProvider(
        Settings(
            llm_base_url="https://example.com/v1",
            llm_model="m",
            llm_api_key="k",
        )
    )

    assert _drain(provider) == ["\u4f60\u597d", "\u4e16\u754c"]
