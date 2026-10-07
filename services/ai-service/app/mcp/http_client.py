"""MCP streamablehttp 客户端：零第三方依赖的 HTTP JSON-RPC 2.0。

无状态实现：每次请求独立 POST，兼容服务器返回单条 JSON 或 SSE 流。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .stdio_client import McpStdioError, McpTool, PROTOCOL_VERSION


class McpHttpClient:
    """远程 streamablehttp MCP 服务器；无持久连接，running 恒为 True。"""

    def __init__(self, url: str) -> None:
        self._url = url
        self._next_id = 1
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15))
        await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "qiling-mcp-client", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, "params": params})

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        assert self._client is not None
        try:
            resp = await self._client.post(
                self._url,
                json=payload,
                headers={"Accept": "application/json, text/event-stream"},
            )
        except httpx.HTTPError as exc:
            raise McpStdioError(f"HTTP MCP 请求失败：{exc}") from exc
        if resp.status_code != 200:
            raise McpStdioError(f"HTTP MCP {resp.status_code}: {resp.text[:200]}")
        return resp

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float = 15,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        resp = await self._post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        body = self._decode_response(resp)
        if "error" in body:
            raise McpStdioError(f"MCP 错误：{body['error']}")
        return body.get("result", {})

    @staticmethod
    def _decode_response(resp: httpx.Response) -> dict[str, Any]:
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise McpStdioError("HTTP MCP 返回非 JSON") from exc

    async def list_tools(self) -> list[McpTool]:
        result = await self.request("tools/list", {})
        tools: list[McpTool] = []
        for item in result.get("tools", []):
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            description = item.get("description", "")
            schema = item.get("inputSchema", {})
            tools.append(
                McpTool(
                    name=name,
                    description=description if isinstance(description, str) else "",
                    input_schema=schema if isinstance(schema, dict) else {},
                )
            )
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float = 60,
    ) -> str:
        result = await self.request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=timeout
        )
        parts: list[str] = []
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if not parts and result.get("isError"):
            raise McpStdioError("MCP 工具返回错误")
        return "\n".join(parts)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def running(self) -> bool:
        return True
