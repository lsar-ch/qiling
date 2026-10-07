"""MCP 服务器管理：配置加载、懒启动、空闲回收与工具聚合。

配置见 config/mcp-servers.yaml（结构同 docs/EXTENSION-SKELETON-PLAN.md §4.3）。
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from qiling_contracts import McpServerInfo

from .http_client import McpHttpClient
from .stdio_client import McpStdioClient, McpStdioError, McpTool


class McpManagerError(RuntimeError):
    """MCP 配置或服务器操作失败。"""


DEFAULT_IDLE_TIMEOUT_S = 300
FAILURE_COOLDOWN_S = 30
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


@dataclass
class ServerConfig:
    id: str
    source: str
    enabled: bool
    transport: str
    access: str
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    idle_timeout_s: int = DEFAULT_IDLE_TIMEOUT_S


@dataclass
class _Runtime:
    client: McpStdioClient | McpHttpClient
    tools: list[McpTool]
    last_used: float


class McpManager:
    """配置在启动时读入；进程在首次工具调用时才启动。"""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._servers: dict[str, ServerConfig] = self._load()
        self._runtime: dict[str, _Runtime] = {}
        self._tool_cache: dict[str, list[McpTool]] = {}
        self._error_detail: dict[str, str] = {}
        self._fail_cooldown_until: dict[str, float] = {}

    def _load(self) -> dict[str, ServerConfig]:
        if not self._config_path.is_file():
            return {}
        try:
            data = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise McpManagerError(f"MCP 配置解析失败：{exc}") from exc
        raw_servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(raw_servers, list):
            return {}
        out: dict[str, ServerConfig] = {}
        for item in raw_servers:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            server_id = str(raw_id).strip() if raw_id else ""
            if not server_id:
                continue
            out[server_id] = ServerConfig(
                id=server_id,
                source=str(item.get("source", "user")),
                enabled=bool(item.get("enabled", False)),
                transport=str(item.get("transport", "stdio")),
                access=str(item.get("access", "read")),
                command=item.get("command"),
                args=[str(arg) for arg in item.get("args", [])] if item.get("args") else [],
                env={str(k): str(v) for k, v in item.get("env", {}).items()} if item.get("env") else {},
                url=item.get("url"),
                idle_timeout_s=int(item.get("idle_timeout_s", DEFAULT_IDLE_TIMEOUT_S)),
            )
        return out

    def reload(self) -> None:
        """重新读配置；已运行且仍存在的连接不动。"""
        self._servers = self._load()

    def add_or_update_server(self, payload: dict[str, Any]) -> None:
        """新增或更新用户服务器并持久化；内置服务器不可改。"""
        server_id = str(payload.get("id", "")).strip()
        if not _ID_RE.fullmatch(server_id):
            raise McpManagerError("服务器 id 只能含小写字母、数字、-、_（≤40 字符）")
        existing = self._servers.get(server_id)
        if existing is not None and existing.source == "builtin":
            raise McpManagerError("内置服务器不可修改")

        transport = str(payload.get("transport", "stdio")).strip()
        if transport not in ("stdio", "streamablehttp"):
            raise McpManagerError("transport 只能是 stdio 或 streamablehttp")
        access = str(payload.get("access", "read")).strip()
        if access not in ("read", "write"):
            raise McpManagerError("access 只能是 read 或 write")

        command = payload.get("command")
        command = str(command).strip() if command else None
        raw_args = payload.get("args") or []
        args = [str(item) for item in raw_args] if isinstance(raw_args, list) else []
        raw_env = payload.get("env") or {}
        env = (
            {str(k): str(v) for k, v in raw_env.items()}
            if isinstance(raw_env, dict)
            else {}
        )
        url = payload.get("url")
        url = str(url).strip() if url else None

        if transport == "stdio":
            if not command:
                raise McpManagerError("stdio 服务器必须填写 command")
            url = None
        else:
            if not url:
                raise McpManagerError("streamablehttp 服务器必须填写 url")
            command = None
            args = []
            env = {}

        cfg = ServerConfig(
            id=server_id,
            source="user",
            enabled=bool(payload.get("enabled", False)),
            transport=transport,
            access=access,
            command=command,
            args=args,
            env=env,
            url=url,
        )
        self._servers[server_id] = cfg
        self._persist()

    async def set_enabled(self, server_id: str, enabled: bool) -> None:
        cfg = self._servers.get(server_id)
        if cfg is None:
            raise McpManagerError(f"服务器不存在：{server_id}")
        if cfg.source == "builtin":
            raise McpManagerError("内置服务器不可停用")
        cfg.enabled = bool(enabled)
        self._persist()
        if not enabled:
            await self.stop(server_id)
            self._clear_failure(server_id)

    async def remove_server(self, server_id: str) -> None:
        cfg = self._servers.get(server_id)
        if cfg is None:
            raise McpManagerError(f"服务器不存在：{server_id}")
        if cfg.source == "builtin":
            raise McpManagerError("内置服务器不可删除")
        await self.stop(server_id)
        self._servers.pop(server_id, None)
        self._tool_cache.pop(server_id, None)
        self._clear_failure(server_id)
        self._persist()

    def _persist(self) -> None:
        servers: list[dict[str, Any]] = []
        for cfg in self._servers.values():
            entry: dict[str, Any] = {
                "id": cfg.id,
                "source": cfg.source,
                "enabled": cfg.enabled,
                "transport": cfg.transport,
                "access": cfg.access,
                "idle_timeout_s": cfg.idle_timeout_s,
            }
            if cfg.transport == "stdio":
                entry["command"] = cfg.command
                entry["args"] = cfg.args or []
                if cfg.env:
                    entry["env"] = cfg.env
            else:
                entry["url"] = cfg.url
            servers.append(entry)
        payload = {"version": 1, "servers": servers}
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def list_servers(self) -> list[McpServerInfo]:
        out: list[McpServerInfo] = []
        now = time.monotonic()
        for server_id, cfg in self._servers.items():
            runtime = self._runtime.get(server_id)
            cooling = now < self._fail_cooldown_until.get(server_id, 0)
            if runtime is not None and runtime.client.running:
                status = "ready"
            elif cooling:
                status = "error"
            elif cfg.enabled:
                status = "not_started"
            else:
                status = "disabled"
            detail = self._error_detail.get(server_id, "") if status == "error" else ""
            cached_tools = self._tool_cache.get(server_id)
            out.append(
                McpServerInfo(
                    id=server_id,
                    source=cfg.source,  # type: ignore[arg-type]
                    enabled=cfg.enabled,
                    transport=cfg.transport,  # type: ignore[arg-type]
                    status=status,  # type: ignore[arg-type]
                    access=cfg.access,  # type: ignore[arg-type]
                    command=cfg.command,
                    args=cfg.args or [],
                    url=cfg.url,
                    tool_count=len(runtime.tools) if runtime else len(cached_tools or []),
                    detail=detail,
                )
            )
        return out

    async def list_tools(self, server_id: str) -> list[McpTool]:
        runtime = await self._ensure_runtime(server_id)
        return runtime.tools

    async def prepare_tool_specs(self) -> list[tuple[str, McpTool]]:
        """汇总已启用服务器的工具；有缓存用缓存（不拉起进程），
        无缓存才懒启动拉取，失败进入冷却且不抛出，避免拖垮对话主链路。"""
        out: list[tuple[str, McpTool]] = []
        now = time.monotonic()
        for server_id, cfg in self._servers.items():
            if not cfg.enabled:
                continue
            cached = self._tool_cache.get(server_id)
            if cached is not None:
                out.extend((server_id, tool) for tool in cached)
                continue
            if now < self._fail_cooldown_until.get(server_id, 0):
                continue
            try:
                runtime = await self._ensure_runtime(server_id)
            except McpManagerError as exc:
                self._record_failure(server_id, str(exc))
                continue
            out.extend((server_id, tool) for tool in runtime.tools)
        return out

    def _record_failure(self, server_id: str, detail: str) -> None:
        self._error_detail[server_id] = detail[:300]
        self._fail_cooldown_until[server_id] = time.monotonic() + FAILURE_COOLDOWN_S
        self._runtime.pop(server_id, None)

    def _clear_failure(self, server_id: str) -> None:
        self._error_detail.pop(server_id, None)
        self._fail_cooldown_until.pop(server_id, None)

    def get_access(self, server_id: str) -> str | None:
        cfg = self._servers.get(server_id)
        return cfg.access if cfg else None

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        runtime = await self._ensure_runtime(server_id)
        runtime.last_used = time.monotonic()
        try:
            return await runtime.client.call_tool(tool_name, arguments)
        except McpStdioError as exc:
            self._record_failure(server_id, f"工具 {tool_name} 调用失败：{exc}")
            raise

    async def _ensure_runtime(self, server_id: str) -> _Runtime:
        cfg = self._servers.get(server_id)
        if cfg is None:
            raise McpManagerError(f"MCP 服务器不存在：{server_id}")
        if not cfg.enabled:
            raise McpManagerError(f"MCP 服务器已停用：{server_id}")
        runtime = self._runtime.get(server_id)
        if runtime is not None and runtime.client.running:
            return runtime
        if cfg.transport == "stdio":
            if not cfg.command:
                raise McpManagerError(f"stdio 服务器缺少 command：{server_id}")
            client: McpStdioClient | McpHttpClient = McpStdioClient(
                cfg.command, cfg.args or [], cfg.env or {}
            )
        elif cfg.transport == "streamablehttp":
            if not cfg.url:
                raise McpManagerError(f"http 服务器缺少 url：{server_id}")
            client = McpHttpClient(cfg.url)
        else:
            raise McpManagerError(f"暂不支持的传输：{cfg.transport}")
        try:
            await client.start()
            tools = await client.list_tools()
        except McpStdioError as exc:
            await client.stop()
            self._record_failure(server_id, str(exc))
            raise McpManagerError(f"连接 MCP 失败：{exc}") from exc
        runtime = _Runtime(client=client, tools=tools, last_used=time.monotonic())
        self._runtime[server_id] = runtime
        self._tool_cache[server_id] = tools
        self._clear_failure(server_id)
        return runtime

    async def test_connection(self, server_id: str) -> list[McpTool]:
        """强制建立连接并返回工具；用于 UI「测试连接」。"""
        self._clear_failure(server_id)
        self._runtime.pop(server_id, None)
        runtime = await self._ensure_runtime(server_id)
        return runtime.tools

    async def stop(self, server_id: str) -> None:
        runtime = self._runtime.pop(server_id, None)
        if runtime is not None:
            await runtime.client.stop()

    async def reclaim_idle(self) -> list[str]:
        """回收超过空闲超时的连接，返回被回收的服务器 id。"""
        now = time.monotonic()
        reclaimed: list[str] = []
        for server_id, cfg in list(self._servers.items()):
            runtime = self._runtime.get(server_id)
            if runtime is None or not runtime.client.running:
                continue
            if now - runtime.last_used >= cfg.idle_timeout_s:
                await runtime.client.stop()
                self._runtime.pop(server_id, None)
                reclaimed = [*reclaimed, server_id]
        return reclaimed

    async def shutdown(self) -> None:
        for server_id in list(self._runtime):
            await self.stop(server_id)
