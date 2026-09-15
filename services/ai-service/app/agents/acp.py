"""Minimal line-delimited JSON-RPC 2.0 client for ACP stdio servers.

The ACP server (e.g. codex-acp) is spawned per task. This module does not
implement the full spec; it covers initialize/session lifecycle, streamed
session updates, permission requests, cancellation, and close.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# ACP 单行 JSON-RPC 可能非常大（工具输出、文件内容、转录）。asyncio 的
# StreamReader 默认只给 64 KiB，超了 readline() 会直接抛错，reader 停摆后整条
# 会话被判失败。这里放宽到 16 MiB；再大就该走分片协议而不是加内存。
ACP_STREAM_LIMIT = 16 * 1024 * 1024

UpdateHandler = Callable[[dict[str, Any]], Awaitable[None]]
PermissionHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class AcpError(RuntimeError):
    """ACP protocol/process failure."""


class AcpRequestError(AcpError):
    """ACP request returned a JSON-RPC error, optionally auth-related."""

    def __init__(self, message: str, *, auth_required: bool = False) -> None:
        super().__init__(message)
        self.auth_required = auth_required


class AcpClient:
    """Keep one reader task and correlate JSON-RPC requests by id."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        on_update: UpdateHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> None:
        self._process = process
        self._on_update = on_update
        self._on_permission = on_permission
        self._next_id = 0
        self._requests: dict[int, asyncio.Future[Any]] = {}
        self._closed = False
        self._reader: asyncio.Task[None] | None = None

    @classmethod
    async def spawn(
        cls,
        command: str,
        *,
        args: list[str] | tuple[str, ...] | None = None,
        cwd: str,
        env: dict[str, str],
        on_update: UpdateHandler | None = None,
        on_permission: PermissionHandler | None = None,
        logs_dir: Path | None = None,
        stderr_log_name: str = "codex-acp-stderr.log",
    ) -> "AcpClient":
        if logs_dir is not None:
            logs_dir.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            command,
            *(args or ()),
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=ACP_STREAM_LIMIT,
        )
        client = cls(process, on_update=on_update, on_permission=on_permission)
        client._reader = asyncio.create_task(client._read_loop())
        log_path = logs_dir / stderr_log_name if logs_dir is not None else None
        client._stderr_log_task = asyncio.create_task(client._drain_stderr(log_path))
        return client

    async def _drain_stderr(self, path: Path | None) -> None:
        assert self._process.stderr is not None
        try:
            data = await self._process.stderr.read()
            if data and path is not None:
                path.write_bytes(data)
            elif not data:
                pass
        except (OSError, RuntimeError):
            pass

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_s: float | None = 30.0,
    ) -> Any:
        if self._closed or self._process.returncode is not None:
            raise AcpError("ACP process is not running")
        self._next_id += 1
        request_id = self._next_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._requests[request_id] = future
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        await self._write(message)
        try:
            if timeout_s is None:
                return await future
            return await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            self._requests.pop(request_id, None)
            raise AcpError(f"ACP request {method} timed out") from None

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if self._closed:
            raise AcpError("ACP process is not running")
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
        self._fail_pending(AcpError("ACP process closed"))
        if self._reader is not None:
            self._reader.cancel()

    async def _write(self, message: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._process.stdout is not None
        try:
            while True:
                raw = await self._process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("discarded non-JSON ACP line: %.160s", line)
                    continue
                await self._dispatch(message)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("ACP reader stopped: %s", exc)
        finally:
            self._fail_pending(AcpError("ACP process exited"))

    async def _dispatch(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if "method" not in message:
            future = self._requests.pop(request_id, None)
            if future is not None and not future.done():
                if "error" in message:
                    error = message.get("error") or {}
                    if isinstance(error, dict):
                        message_text = str(error.get("message", "ACP error"))
                        code = error.get("code")
                        auth_required = (
                            "authentication required" in message_text.lower()
                            or code == -32000
                        )
                        future.set_exception(
                            AcpRequestError(
                                message_text,
                                auth_required=auth_required,
                            )
                        )
                    else:
                        future.set_exception(AcpError(str(error)))
                else:
                    future.set_result(message.get("result"))
            return

        method = str(message["method"])
        if method == "session/update" and self._on_update is not None:
            params = message.get("params") or {}
            update = params.get("update")
            if isinstance(update, dict):
                await self._on_update(update)
            return
        if method == "session/request_permission" and self._on_permission is not None:
            params = message.get("params") or {}
            try:
                outcome = await self._on_permission(params)
                result = {"outcome": outcome}
            except Exception as exc:
                logger.warning("permission handler failed: %s", exc)
                result = {"outcome": {"outcome": "cancelled"}}
            if request_id is not None:
                await self._write(
                    {"jsonrpc": "2.0", "id": request_id, "result": result}
                )
            return
        if method == "$/cancel_request":
            return
        logger.info("ignored ACP message method=%s", method)

    def _fail_pending(self, exc: BaseException) -> None:
        for future in list(self._requests.values()):
            if not future.done():
                future.set_exception(exc)
        self._requests.clear()
