"""通用 ACP 执行器：任何实现 ACP/stdio 的 CLI 都能直接接入。

ACP 是 栖灵 的执行器主线（2026-10-01 定案）：对接一次协议，所有实现了
ACP 的 agent 都能插进来，不再为每家厂商写专用 adapter。厂商差异只剩两项——
**启动命令**与**凭据注入方式**——都由 ``config/agents.yaml`` 的 config 下发，
用户也可在页面覆盖。

config 约定（键名与已有 codex/workbuddy 一致，便于复用页面逻辑）：

- ``{name}_command`` / ``command``：页面覆盖的完整启动命令行（可带参数）。
- ``acp_command``：目录默认启动命令行（YAML 里配）。
- ``{name}_api_key`` / ``api_key``：页面填的自备凭据。
- ``api_key_env``：把上面的凭据注入到哪个环境变量（各家不同，YAML 配）。
- ``env``：额外固定环境变量（如 OPENAI_BASE_URL）。
- ``login_hint`` / ``signup_url``：给页面显示「去哪拿 Key」的可点链接文案。

探测只做 initialize + session/new 握手（便宜、不消耗额度）。真实执行走
``/run``：session/new → session/prompt → 流式 session/update → 收尾。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from qiling_contracts.agent import AgentInfo

from app.agents.acp import (
    AcpClient,
    AcpError,
    AcpRequestError,
    content_text,
    option_id_for_kind,
)
from app.agents.base import (
    AgentAdapter,
    AgentExecutionError,
    AgentTaskRequest,
    AgentTaskResult,
)
from app.agents.catalog import AgentCatalogEntry

logger = logging.getLogger(__name__)

_PROBE_TTL_S = 300.0
_PROBE_PROMPT = "只回复两个字：就绪"

# 默认启动命令兜底：目录没配 acp_command 时用 commands[0]。
_DEFAULT_ARGS = ("--acp",)


def _probe_workdir() -> str:
    """探测用工作目录：固定临时目录，不用用户主目录，避免 CLI 白扫大盘。"""
    base = Path(tempfile.gettempdir()) / "qiling-acp-cli-probe"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return str(Path(tempfile.gettempdir()))
    return str(base)


class AcpCliAdapter(AgentAdapter):
    """通过任意 ACP/stdio CLI 提交真实任务。"""

    executable = True
    default_eligible = True

    def __init__(
        self,
        timeout_s: float = 8.0,
        catalog_entry: AgentCatalogEntry | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.catalog_entry = catalog_entry or AgentCatalogEntry(
            name="acp-cli",
            label="ACP CLI",
            adapter="acp-cli",
            enabled=True,
            commands=["acp-cli"],
            protocol="acp",
            capabilities=["task", "agent"],
            source_url=None,
            tags=["acp", "cli"],
            detail="",
        )
        entry = self.catalog_entry
        self.name = entry.name
        self.adapter_id = entry.adapter or "acp-cli"
        self.display_name = entry.label or entry.name
        self.config: dict[str, Any] = dict(entry.config or {})
        self._probe_cache: tuple[float, str, str] | None = None
        # 被动健康检查不拉起子进程：npx 分发会在探测时联网下载，几十秒起步。
        # 首次真正握手只由「测试连接」（POST /refresh）触发。
        self._force_probe = False
        self._active_clients: dict[str, AcpClient] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._permission_futures: dict[str, dict[str, Any]] = {}
        self._pending_permissions: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, list[str]] = {}
        self._tool_calls: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ 解析

    def _command_line(self) -> list[str] | None:
        """生效的启动命令行：页面覆盖 > 目录 acp_command > commands[0] + 默认参数。"""
        raw = str(
            self.config.get(f"{self.name}_command")
            or self.config.get("command")
            or self.config.get("acp_command")
            or ""
        ).strip()
        if raw:
            parts = shlex.split(raw)
        else:
            commands = self.catalog_entry.commands or [self.name]
            parts = [commands[0], *_DEFAULT_ARGS]
        if not parts:
            return None
        return parts

    def _resolve(self) -> list[str] | None:
        """解析可执行文件：首段是绝对/相对路径则查文件，否则走 PATH。"""
        parts = self._command_line()
        if not parts:
            return None
        head = parts[0]
        if "/" in head or "\\" in head:
            candidate = Path(head).expanduser()
            if not candidate.is_file():
                return None
            return [str(candidate), *parts[1:]]
        found = shutil.which(head)
        if not found:
            return None
        return [found, *parts[1:]]

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        extra = self.config.get("env")
        if isinstance(extra, dict):
            for key, value in extra.items():
                if value is not None:
                    env[str(key)] = str(value)
        api_key = str(
            self.config.get(f"{self.name}_api_key")
            or self.config.get("api_key")
            or ""
        ).strip()
        key_env = str(self.config.get("api_key_env") or "").strip()
        if api_key and key_env:
            env[key_env] = api_key
        env["NO_COLOR"] = "1"
        return env

    def _auth_hint(self, raw: str) -> str:
        base = str(self.config.get("login_hint") or "").strip()
        if base:
            return base
        url = str(self.config.get("signup_url") or "").strip()
        if url:
            return f"请先在 {url} 获取凭据并填入本执行器的 API Key。"
        return "请确认该 CLI 已登录或已配置 API Key。"

    # ------------------------------------------------------------------ 探测

    async def detect(self) -> AgentInfo:
        resolved = self._resolve()
        if resolved is None:
            configured = str(
                self.config.get(f"{self.name}_command")
                or self.config.get("command")
                or self.config.get("acp_command")
                or ""
            ).strip()
            detail = f"未检测到 {self.display_name}，请在下方填写启动命令行"
            if configured:
                detail += f"（当前配置：{configured}）"
            return self._info("not_installed", False, detail=detail)

        cached = self._probe_cache
        if cached is not None and (time.monotonic() - cached[0]) < _PROBE_TTL_S:
            status, detail = cached[1], cached[2]
        elif self._force_probe:
            self._force_probe = False
            status, detail = await self._probe(resolved)
        else:
            status, detail = (
                "ready",
                f"已检测到 {self.display_name} 的启动命令；点「测试连接」可验证 ACP 握手与凭据。",
            )
        return self._info(
            status,
            status == "ready",
            command=" ".join(resolved),
            protocol="acp",
            detail=detail,
        )

    async def _probe(self, resolved: list[str]) -> tuple[str, str]:
        cached = self._probe_cache
        if cached is not None and (time.monotonic() - cached[0]) < _PROBE_TTL_S:
            return cached[1], cached[2]
        client: AcpClient | None = None
        try:
            client = await self._spawn(resolved, cwd=_probe_workdir(), logs_dir=None)
            await client.request("initialize", self._init_params(), timeout_s=20.0)
            await client.request(
                "session/new",
                {"cwd": _probe_workdir(), "mcpServers": []},
                timeout_s=30.0,
            )
            result = ("ready", f"{self.display_name} ACP 握手正常，可提交任务。")
        except AcpRequestError as exc:
            if exc.auth_required:
                result = (
                    "auth_required",
                    f"{self.display_name} 已安装但凭据不可用。{self._auth_hint(str(exc))}"
                    f"（原始错误：{exc}）",
                )
            else:
                result = ("error", f"{self.display_name} 握手失败：{exc}")
        except (AcpError, OSError) as exc:
            result = ("error", f"{self.display_name} 启动失败：{exc}")
        finally:
            if client is not None:
                await client.close()
        self._probe_cache = (time.monotonic(), result[0], result[1])
        return result

    def invalidate_probe(self) -> None:
        """「测试连接」/重新检测：清缓存并强制下一次探测真正握手。"""
        self._probe_cache = None
        self._force_probe = True

    def _info(
        self,
        status: str,
        available: bool,
        *,
        command: str | None = None,
        protocol: str | None = "acp",
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
            command=command,
            protocol=protocol,
            capabilities=list(self.catalog_entry.capabilities),
            tags=list(self.catalog_entry.tags),
            source_url=self.catalog_entry.source_url,
            detail=detail,
        )

    # ------------------------------------------------------------------ 启动

    @staticmethod
    def _init_params() -> dict[str, Any]:
        return {
            "protocolVersion": 1,
            "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False},
                "terminal": False,
            },
            "clientInfo": {"name": "栖灵", "version": "0.1.0"},
        }

    async def _spawn(
        self,
        resolved: list[str],
        *,
        cwd: str,
        logs_dir: Path | None,
        on_update=None,
        on_permission=None,
    ) -> AcpClient:
        return await AcpClient.spawn(
            resolved[0],
            args=resolved[1:],
            cwd=cwd,
            env=self._child_env(),
            on_update=on_update,
            on_permission=on_permission,
            logs_dir=logs_dir,
            stderr_log_name=f"{self.name}-acp-stderr.log",
        )

    # ------------------------------------------------------------------ 执行

    async def run(
        self,
        request: AgentTaskRequest,
        on_update,
    ) -> AgentTaskResult:
        resolved = self._resolve()
        if resolved is None:
            raise AgentExecutionError(f"{self.display_name} 不可用：未检测到可执行的启动命令。")

        self._outputs[request.task_id] = []
        self._tool_calls[request.task_id] = []
        self._cancel_events[request.task_id] = asyncio.Event()
        raw_logs = request.config.get("logs_dir") or Path(tempfile.gettempdir()) / "qiling-acp-logs"
        logs_dir = Path(str(raw_logs)).expanduser() / request.task_id
        client = await self._spawn(
            resolved,
            cwd=request.cwd,
            logs_dir=logs_dir,
            on_update=self._make_update_handler(request.task_id, on_update),
            on_permission=self._make_permission_handler(request.task_id, request.mode, on_update),
        )
        self._active_clients[request.task_id] = client
        session_id: str | None = None
        try:
            await client.request("initialize", self._init_params(), timeout_s=30.0)
            try:
                created = await client.request(
                    "session/new",
                    {"cwd": request.cwd, "mcpServers": []},
                    timeout_s=60.0,
                )
            except AcpRequestError as exc:
                if exc.auth_required:
                    self._probe_cache = None
                    raise AgentExecutionError(
                        f"{self.display_name} 凭据不可用，任务无法执行。{self._auth_hint(str(exc))}"
                    ) from exc
                raise
            session_id = created.get("sessionId") if isinstance(created, dict) else None
            if not session_id:
                raise AgentExecutionError(f"{self.display_name} ACP session/new 未返回 sessionId")
            await on_update("session_ready", {"session_id": session_id, "mode": request.mode})

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
            if self._cancel_events[request.task_id].is_set() or stop_reason == "cancelled":
                return AgentTaskResult(
                    status="cancelled",
                    message=f"{self.display_name} 任务已取消",
                    session_id=session_id,
                )
            if stop_reason == "refusal":
                return AgentTaskResult(
                    status="failed",
                    session_id=session_id,
                    error=f"{self.display_name} 拒绝执行该任务",
                )
            message = "".join(self._outputs.get(request.task_id, [])).strip()
            tool_calls = self._tool_calls.get(request.task_id, [])
            if tool_calls:
                tool_summary = "工具调用：" + " → ".join(tool_calls[:10])
                if len(tool_calls) > 10:
                    tool_summary += f" …（共 {len(tool_calls)} 次）"
                message = (tool_summary + "\n\n" + message) if message else tool_summary
            if not message:
                message = f"（{self.display_name} 未返回文本内容）"
            return AgentTaskResult(status="completed", message=message, session_id=session_id)
        except asyncio.CancelledError:
            raise
        except AgentExecutionError:
            raise
        except Exception as exc:
            event = self._cancel_events.get(request.task_id)
            if event is not None and event.is_set():
                return AgentTaskResult(
                    status="cancelled",
                    message=f"{self.display_name} 任务已取消",
                    session_id=session_id,
                )
            raise AgentExecutionError(f"{self.display_name} 执行失败：{exc}") from exc
        finally:
            await client.close()
            self._active_clients.pop(request.task_id, None)
            self._cancel_events.pop(request.task_id, None)
            self._pending_permissions.pop(request.task_id, None)
            self._outputs.pop(request.task_id, None)
            self._tool_calls.pop(request.task_id, None)

    async def cancel(self, task_id: str, session_id: str | None = None) -> None:
        event = self._cancel_events.get(task_id)
        if event is not None:
            event.set()
        client = self._active_clients.get(task_id)
        if client is not None:
            try:
                if session_id:
                    await client.notify("session/cancel", {"sessionId": session_id})
            finally:
                await client.close()
        entry = self._permission_futures.pop(task_id, None)
        if entry is not None:
            future = entry.get("future")
            if future is not None and not future.done():
                future.set_result({"outcome": "cancelled"})

    async def approve(self, task_id: str, decision: str) -> None:
        entry = self._permission_futures.get(task_id)
        if entry is None:
            return
        future = entry.get("future")
        if future is None or future.done():
            return
        options = entry.get("options") or []
        if decision == "approved":
            option = option_id_for_kind(options, "allow_once", "allow_always")
        else:
            option = option_id_for_kind(options, "reject_once", "reject_always")
        if option is None:
            future.set_result({"outcome": "cancelled"})
            return
        future.set_result({"outcome": "selected", "optionId": option})

    # ------------------------------------------------------------- 事件处理

    def _make_update_handler(self, task_id: str, on_update):
        async def handle(update: dict[str, Any]) -> None:
            kind = update.get("sessionUpdate")
            if kind == "agent_message_chunk":
                text = content_text(update.get("content"))
                if text:
                    self._outputs.setdefault(task_id, []).append(text)
                    await on_update("progress", {"text": text, "progress": text.strip()[:300]})
                return
            if kind in ("tool_call", "tool_call_update"):
                title = str(update.get("title") or "").strip()
                if title:
                    self._tool_calls.setdefault(task_id, []).append(title)
                    await on_update("progress", {"text": "", "progress": title[:300]})
        return handle

    def _make_permission_handler(self, task_id: str, mode: str, on_update):
        async def handle(params: dict[str, Any]) -> dict[str, Any]:
            options = params.get("options") or []
            if mode == "agent-full-access":
                option = option_id_for_kind(options, "allow_once", "allow_always")
                if option is not None:
                    return {"outcome": "selected", "optionId": option}
            self._pending_permissions[task_id] = params
            loop = asyncio.get_running_loop()
            future: asyncio.Future[dict[str, Any]] = loop.create_future()
            # future 必须先登记再通知：runtime 的 read-only 自动回绝是在这次回调里
            # 同步调 approve() 的，后建会让那次回绝静默丢失、任务永远挂着。
            self._permission_futures[task_id] = {"future": future, "options": options}
            await on_update(
                "permission_request",
                {"tool_call": params.get("toolCall"), "options": options},
            )
            return await future
        return handle
