"""MCP stdio 客户端：换行分隔的 JSON-RPC 2.0，零第三方依赖。

协议要点（2026 年 MCP stdio 传输）：
- 每行一个 JSON-RPC 消息；initialize → notifications/initialized → tools/list、tools/call。
- 子进程 stdin 写请求、stdout 读响应；stderr 仅作日志，不参与协议。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any


class McpStdioError(RuntimeError):
    """stdio MCP 启动或通信失败。"""


PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "deskmate-mcp-client"
CLIENT_VERSION = "0.1.0"


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]


class McpStdioClient:
    """单个 stdio MCP 服务器连接；懒启动，由 manager 决定回收。"""

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = list(args)
        self._env = dict(env or {})
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_tail = ""

    async def start(self) -> None:
        if self._proc is not None:
            return
        env = os.environ.copy()
        env.update(self._env)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except (OSError, FileNotFoundError) as exc:
            raise McpStdioError(f"无法启动 MCP 命令 {self._command}: {exc}") from exc
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._initialize()

    async def _initialize(self) -> None:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
            timeout=10,
        )
        server_protocol = result.get("protocolVersion")
        if isinstance(server_protocol, str) and server_protocol != PROTOCOL_VERSION:
            # 仅记录，不强制失败：多数服务器向后兼容。
            pass
        await self._notify("notifications/initialized", {})

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float = 15,
    ) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise McpStdioError("MCP 连接未启动")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise McpStdioError(f"MCP 请求超时：{method}") from exc
        if "error" in response:
            error = response["error"]
            raise McpStdioError(f"MCP 错误：{error}")
        return response.get("result", {})

    async def _write(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                break
            try:
                message = json.loads(raw.decode("utf-8").strip())
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            request_id = message.get("id")
            if request_id is not None and request_id in self._pending:
                future = self._pending.pop(request_id)
                if not future.done():
                    future.set_result(message)
        self._fail_all_pending(McpStdioError("MCP 进程已关闭"))

    def _fail_all_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def list_tools(self) -> list[McpTool]:
        result = await self.request("tools/list", {})
        raw_tools = result.get("tools", [])
        tools: list[McpTool] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            description = item.get("description", "")
            schema = item.get("inputSchema", {"type": "object", "properties": {}})
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
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
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
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._proc is not None:
            self._fail_all_pending(McpStdioError("MCP 连接已关闭"))
            if self._proc.stdin is not None:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self._proc.kill()
            self._proc = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None
