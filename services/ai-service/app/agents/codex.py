"""Codex ACP/stdio adapter：探测、会话创建、任务提交、取消与授权。"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from deskmate_contracts.agent import AgentInfo

from app.agents.acp import AcpClient
from app.agents.base import (
    AgentAdapter,
    AgentCancelled,
    AgentExecutionError,
    AgentTaskRequest,
    AgentTaskResult,
)
from app.agents.catalog import AgentCatalogEntry


_DEFAULT_CODEX_NAME = "codex"


def _platform_candidates() -> tuple[Path, ...]:
    """平台常见安装位置（仅作自动检测兜底，不猜死路径）。"""
    if sys.platform == "win32":
        return (
            Path.home() / ".codex" / "bin" / "codex.exe",
            Path.home() / ".codex" / "bin" / "codex.cmd",
        )
    return (
        Path("/Applications/Codex.app/Contents/Resources/codex"),
        Path.home() / ".codex" / "bin" / "codex",
        Path.home() / ".local" / "bin" / "codex",
    )


def _is_file_binary(path: Path) -> bool:
    """跨平台可执行文件判断：POSIX 看 X_OK，Windows 以文件存在为准（能否运行交给探测）。"""
    if not path.is_file():
        return False
    if sys.platform == "win32":
        return True
    return os.access(path, os.X_OK)


def _looks_like_path(value: str) -> bool:
    if "/" in value:
        return True
    if sys.platform == "win32" and "\\" in value:
        return True
    return False


def resolve_codex_command(configured: str | None) -> str | None:
    """解析生效的 codex 命令。

    优先级：页面显式配置 > CODEX_PATH 环境注入 > PATH > 平台常见位置。
    显式注入的值不可用时直接返回 None（不悄悄回退，便于提示用户路径错误）。
    """
    configured_value = (configured or "").strip()
    env_value = (os.environ.get("CODEX_PATH") or "").strip()
    config_explicit = bool(configured_value and configured_value != _DEFAULT_CODEX_NAME)

    if config_explicit:
        candidate = configured_value
        if _looks_like_path(candidate):
            return str(Path(candidate).expanduser()) if _is_file_binary(Path(candidate).expanduser()) else None
        return shutil.which(candidate)
    if env_value:
        if _looks_like_path(env_value):
            return str(Path(env_value).expanduser()) if _is_file_binary(Path(env_value).expanduser()) else None
        return shutil.which(env_value)

    found = shutil.which(_DEFAULT_CODEX_NAME)
    if found:
        return found
    for location in _platform_candidates():
        if _is_file_binary(location):
            return str(location)
    return None


class CodexAdapter(AgentAdapter):
    """通过 codex-acp 提交真实 Codex 任务。"""

    name = "codex"
    adapter_id = "codex"
    display_name = "Codex CLI"
    executable = True

    _ALLOWED_MODES = ("read-only", "agent", "agent-full-access")

    def __init__(
        self,
        timeout_s: float = 5.0,
        catalog_entry: AgentCatalogEntry | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.catalog_entry = catalog_entry or AgentCatalogEntry(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            enabled=True,
            commands=["codex"],
            protocol="codex-acp",
            capabilities=["code", "project", "task_execution"],
            source_url="https://github.com/openai/codex",
            tags=["official", "acp", "cli"],
            detail="",
        )
        self.name = self.catalog_entry.name
        self.adapter_id = self.catalog_entry.adapter or self.adapter_id
        self.display_name = self.catalog_entry.label or self.display_name
        self._codex_command = str(
            self.catalog_entry.config.get("codex_command") or "codex"
        )
        self._acp_command = str(
            self.catalog_entry.config.get("acp_command") or "codex-acp"
        )
        self._active_clients: dict[str, AcpClient] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._permission_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_permissions: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, list[str]] = {}
        self._run_errors: dict[str, list[str]] = {}

    async def detect(self) -> AgentInfo:
        resolved = resolve_codex_command(self._codex_command)
        acp_found = shutil.which(self._acp_command) is not None

        if resolved is None:
            detail = f"{self._codex_command} is not installed / 未检测到 {self._codex_command}。"
            configured = (self._codex_command or "").strip()
            if configured and configured != "codex":
                detail += f" 手动配置路径不可用：{configured}。"
            if acp_found:
                detail += f" {self._acp_command} exists but requires Codex CLI. / 已检测到 ACP，但依赖 Codex CLI。"
            return self._info("not_installed", False, detail=detail)

        codex_result = await asyncio.to_thread(self._probe, resolved)
        _found, version, probe_error = codex_result
        if probe_error:
            return self._info(
                "error",
                False,
                version=None,
                detail=f"Codex CLI probe failed / 探测失败：{probe_error}",
            )

        if not acp_found:
            return self._info(
                "pending",
                False,
                version=version,
                command=resolved,
                protocol=None,
                detail=(
                    f"Codex CLI {version or ''} detected at {resolved}; {self._acp_command} not found. "
                    f"真实 ACP 执行需要安装 {self._acp_command}。"
                ),
            )

        return self._info(
            "ready",
            True,
            version=version,
            command=resolved,
            protocol="codex-acp",
            detail=(
                f"Codex CLI {version or ''} at {resolved}; {self._acp_command} detected. "
                f"/ 已检测到 Codex 与 ACP，可提交真实任务。"
            ),
        )

    def _info(
        self,
        status: str,
        available: bool,
        *,
        version: str | None = None,
        command: str | None = None,
        protocol: str | None = "codex-acp",
        detail: str,
    ) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            integration_status=status,  # type: ignore[arg-type]
            available=available,
            enabled=self.catalog_entry.enabled,
            default_eligible=bool(self.executable and self.default_eligible),
            version=version,
            command=command,
            protocol=protocol,
            capabilities=list(self.catalog_entry.capabilities),
            tags=list(self.catalog_entry.tags),
            source_url=self.catalog_entry.source_url,
            detail=detail,
        )

    async def run(
        self,
        request: AgentTaskRequest,
        on_update,
    ) -> AgentTaskResult:
        codex_bin = resolve_codex_command(self._codex_command)
        acp_bin = shutil.which(self._acp_command)
        if not codex_bin or not acp_bin:
            raise AgentExecutionError(
                "Codex ACP 不可用：请先安装 codex 与 codex-acp。"
            )

        mode = request.mode if request.mode in self._ALLOWED_MODES else "read-only"
        self._outputs[request.task_id] = []
        self._run_errors[request.task_id] = []
        self._cancel_events[request.task_id] = asyncio.Event()
        logs_dir = Path(str(request.config.get("logs_dir") or "/tmp/deskmate-acp-logs"))
        client = await AcpClient.spawn(
            acp_bin,
            cwd=request.cwd,
            env={
                **os.environ,
                "CODEX_PATH": codex_bin,
                "NO_BROWSER": "1",
                "INITIAL_AGENT_MODE": mode,
                "APP_SERVER_LOGS": str(logs_dir / request.task_id),
            },
            on_update=self._make_update_handler(request.task_id, on_update),
            on_permission=self._make_permission_handler(request.task_id, on_update),
            logs_dir=logs_dir,
        )
        self._active_clients[request.task_id] = client
        session_id: str | None = None
        try:
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                        "auth": {"terminal": False},
                    },
                    "clientInfo": {"name": "DeskMate", "version": "0.1.0"},
                },
                timeout_s=30.0,
            )
            created = await client.request(
                "session/new",
                {"cwd": request.cwd, "mcpServers": []},
                timeout_s=60.0,
            )
            session_id = created.get("sessionId") if isinstance(created, dict) else None
            if not session_id:
                raise AgentExecutionError("ACP session/new 未返回 sessionId")
            await on_update(
                "session_ready",
                {"session_id": session_id, "mode": mode},
            )
            prompt_result = await client.request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": request.prompt}],
                },
                timeout_s=None,
            )
            stop_reason = (
                prompt_result.get("stopReason") if isinstance(prompt_result, dict) else None
            )
            if stop_reason == "refusal":
                return AgentTaskResult(
                    status="failed",
                    message="Codex refused this task",
                    session_id=session_id,
                    error="refusal",
                )
            if (
                self._cancel_events[request.task_id].is_set()
                or stop_reason == "cancelled"
            ):
                return AgentTaskResult(
                    status="cancelled",
                    message="Codex task cancelled",
                    session_id=session_id,
                )
            errors = self._run_errors.get(request.task_id) or []
            if errors:
                return AgentTaskResult(
                    status="failed",
                    message="Codex task ended with an upstream error",
                    session_id=session_id,
                    error="\n".join(errors)[-3000:],
                )
            return AgentTaskResult(
                status="completed",
                message="".join(self._outputs.get(request.task_id, [])).strip(),
                session_id=session_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            event = self._cancel_events.get(request.task_id)
            if event is not None and event.is_set():
                return AgentTaskResult(
                    status="cancelled",
                    message="Codex task cancelled",
                    session_id=session_id,
                )
            raise AgentExecutionError(str(exc)) from exc
        finally:
            if session_id:
                try:
                    await client.request(
                        "session/close",
                        {"sessionId": session_id},
                        timeout_s=5.0,
                    )
                except Exception:
                    pass
            await client.close()
            self._active_clients.pop(request.task_id, None)
            self._cancel_events.pop(request.task_id, None)
            self._pending_permissions.pop(request.task_id, None)
            self._outputs.pop(request.task_id, None)
            self._run_errors.pop(request.task_id, None)

    async def cancel(self, task_id: str, session_id: str | None = None) -> None:
        event = self._cancel_events.get(task_id)
        if event is not None:
            event.set()
        client = self._active_clients.get(task_id)
        if client is not None:
            try:
                if session_id:
                    await client.notify(
                        "session/cancel", {"sessionId": session_id}
                    )
            finally:
                await client.close()
        future = self._permission_futures.pop(task_id, None)
        if future is not None and not future.done():
            future.set_result({"outcome": "cancelled"})

    async def approve(self, task_id: str, decision: str) -> None:
        future = self._permission_futures.get(task_id)
        if future is None or future.done():
            return
        pending = self._pending_permissions.get(task_id) or {}
        options = pending.get("options") or []
        option_ids = {
            str(item.get("optionId"))
            for item in options
            if isinstance(item, dict) and item.get("optionId")
        }
        if decision == "approved":
            option = "allow_once" if "allow_once" in option_ids else (
                "allow_always" if "allow_always" in option_ids else None
            )
            if option is None:
                future.set_result({"outcome": "cancelled"})
                return
        else:
            option = "reject_always" if "reject_always" in option_ids else (
                "reject_once" if "reject_once" in option_ids else None
            )
            if option is None:
                future.set_result({"outcome": "rejected"})
                return
        future.set_result({"outcome": "selected", "optionId": option})

    def _make_update_handler(self, task_id: str, on_update):
        async def handle(update: dict[str, Any]) -> None:
            meta = update.get("_meta") or {}
            codex_meta = meta.get("codex") or {}
            thread_status = codex_meta.get("threadStatus") or {}
            if thread_status.get("type") == "systemError":
                error_text = str(update.get("title") or "Codex upstream error").strip()
                self._run_errors.setdefault(task_id, []).append(error_text)
                return
            text = _content_text(update.get("content"))
            if text:
                self._outputs.setdefault(task_id, []).append(text)
                if self._run_errors.get(task_id):
                    self._run_errors.setdefault(task_id, []).append(text.strip())
            title = update.get("title") or _update_title(update)
            progress = text.strip() if text else (str(title or "").strip())
            await on_update(
                "progress",
                {
                    "text": text.strip() if text else "",
                    "progress": progress[:300],
                    "session_update": update.get("sessionUpdate"),
                },
            )

        return handle

    def _make_permission_handler(self, task_id: str, on_update):
        async def handle(params: dict[str, Any]) -> dict[str, Any]:
            options = params.get("options") or []
            self._pending_permissions[task_id] = params
            loop = asyncio.get_running_loop()
            future: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._permission_futures[task_id] = future
            # future 必须先登记再通知：运行器的 read-only 自动回绝是在这次回调里
            # 同步调 approve() 的，future 后建会让那次回绝静默丢失、任务永远挂着。
            await on_update(
                "permission_request",
                {
                    "tool_call": params.get("toolCall"),
                    "options": options,
                },
            )
            return await future

        return handle

    def _probe(self, command: str) -> tuple[bool, str | None, str | None]:
        """非交互探测命令版本；只用于 detect。"""
        try:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return False, None, None
        except (OSError, subprocess.SubprocessError) as exc:
            return True, None, str(exc)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            return True, None, message
        output = (result.stdout or result.stderr).strip()
        version = output.splitlines()[0] if output else None
        return True, version, None


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    text = value.get("text")
    if isinstance(text, str):
        return text
    nested = value.get("content")
    if isinstance(nested, dict):
        return _content_text(nested)
    if isinstance(nested, str):
        return nested
    return ""


def _update_title(update: dict[str, Any]) -> str | None:
    kind = update.get("sessionUpdate")
    if kind == "plan":
        return "已更新执行计划"
    if kind == "tool_call":
        return update.get("title")
    if kind == "tool_call_update":
        return update.get("title")
    return None
