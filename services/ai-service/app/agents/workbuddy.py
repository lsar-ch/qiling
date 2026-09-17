"""WorkBuddy 执行器适配器：复用本机 WorkBuddy 自带 CLI，通过 ACP 真实执行任务。

三个关键事实（2026-09-12 本机实测，见迁移文档 §10）：

1. CLI 位置：WorkBuddy 安装目录内的
   ``resources/app.asar.unpacked/cli/bin/codebuddy``。
   它是 JS 脚本，**需要 Node 运行时**，不能像普通 exe 那样直接双击运行。
2. **终端用户不必安装 Node**：WorkBuddy 桌面端本身就是 Electron 应用，
   设 ``ELECTRON_RUN_AS_NODE=1`` 后可用 ``WorkBuddy.exe`` / ``WorkBuddy``
   当 Node 解释器用（实测 Node v22.21.1）——这是满足「零安装」约束的关键。
3. **登录态是硬前提**：CLI 复用桌面端登录，未登录时 ``session/new`` 会返回
   JSON-RPC ``-32000 Authentication required``（1.8 秒快速失败、不消耗积分）。
   这与「未安装」是两种完全不同的状态，必须分开呈现给用户。

另外 ``session/close`` 在 WorkBuddy 的 ACP 实现里不存在（返回 -32601），
所以这里收尾只 terminate 进程，不发 session/close。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deskmate_contracts.agent import AgentInfo

from app.agents.acp import AcpClient, AcpError, AcpRequestError
from app.agents.base import (
    AgentAdapter,
    AgentExecutionError,
    AgentTaskRequest,
    AgentTaskResult,
)
from app.agents.catalog import AgentCatalogEntry
from app.agents.windows_install import fixed_drive_roots, registry_candidates

# CLI 相对安装根目录的位置（Windows / macOS 一致，只是根目录形态不同）
_CLI_RELATIVE = ("resources", "app.asar.unpacked", "cli", "bin", "codebuddy")

logger = logging.getLogger(__name__)

# 未登录引导文案：任何失败态都要给用户可执行的下一步
_LOGIN_HINT = (
    "请先打开 WorkBuddy 桌面端完成登录（右上角头像 → 登录），"
    "登录成功后回到这里点「重新检测」。登录态由 WorkBuddy 自己持久化，"
    "DeskMate 无法代替你登录。"
)


@dataclass(frozen=True)
class WorkBuddyRuntime:
    """一次启动所需的解释器 + CLI 脚本。"""

    cli: Path
    runner: Path | None  # None 表示 cli 自身可执行
    electron: bool  # runner 是否是 Electron 应用（需 ELECTRON_RUN_AS_NODE=1）

    @property
    def display(self) -> str:
        return str(self.runner or self.cli)


def _cli_from_install_root(root: Path) -> Path | None:
    candidate = root.joinpath(*_CLI_RELATIVE)
    return candidate if candidate.is_file() else None


def _electron_binary_from_cli(cli: Path) -> Path | None:
    """从 CLI 脚本位置反推桌面端 Electron 可执行文件。

    ``.../WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy``
    → ``.../WorkBuddy.app/Contents/MacOS/WorkBuddy``
    ``...\\WorkBuddy\\resources\\app.asar.unpacked\\cli\\bin\\codebuddy``
    → ``...\\WorkBuddy\\WorkBuddy.exe``
    """
    # cli 上溯：bin → cli → app.asar.unpacked → resources → <安装根>
    resources = cli.parent.parent.parent.parent
    if resources.name != "resources":
        return None
    if sys.platform == "darwin":
        app_root = resources.parent  # .../WorkBuddy.app/Contents
        macos = app_root / "MacOS"
        if not macos.is_dir():
            return None
        for item in sorted(macos.iterdir()):
            if item.is_file() and os.access(item, os.X_OK):
                return item
        return None
    if sys.platform == "win32":
        for name in ("WorkBuddy.exe", "CodeBuddy.exe", "codebuddy.exe"):
            candidate = resources.parent / name
            if candidate.is_file():
                return candidate
        return None
    for name in ("workbuddy", "WorkBuddy", "codebuddy"):
        candidate = resources.parent / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _runtime_from_path(raw: str) -> WorkBuddyRuntime | None:
    """把用户配置/环境变量给出的路径解析成可启动的运行时。"""
    value = raw.strip().strip('"').strip("'")
    if not value:
        return None
    path = Path(value).expanduser()

    # 1) 目录：按平台找桌面端安装包
    if path.is_dir():
        if sys.platform == "darwin":
            app = path if path.suffix == ".app" else next(
                (item for item in sorted(path.glob("*.app")) if item.is_dir()), None
            )
            if app is None:
                return None
            cli = _cli_from_install_root(app / "Contents")
            if cli is None:
                return None
            return WorkBuddyRuntime(cli=cli, runner=_electron_binary_from_cli(cli), electron=True)
        cli = _cli_from_install_root(path)
        if cli is None:
            return None
        return WorkBuddyRuntime(cli=cli, runner=_electron_binary_from_cli(cli), electron=True)

    if not path.is_file():
        return None

    # 2) 直接给了 CLI 脚本：自行找解释器（优先随包 Electron，零安装）
    if path.name in ("codebuddy", "codebuddy.js") or path.suffix in (".js", ".mjs", ".cjs"):
        runner = _electron_binary_from_cli(path)
        if runner is not None:
            return WorkBuddyRuntime(cli=path, runner=runner, electron=True)
        node = shutil.which("node")
        return WorkBuddyRuntime(cli=path, runner=Path(node) if node else None, electron=False)

    # 3) 给了桌面端 exe / 二进制：反推 CLI
    if path.suffix == ".app":
        cli = _cli_from_install_root(path / "Contents")
        return WorkBuddyRuntime(cli=cli, runner=path / "Contents" / "MacOS" / path.stem, electron=True) if cli else None
    install_root = path.parent
    cli = _cli_from_install_root(install_root)
    if cli is not None:
        return WorkBuddyRuntime(cli=cli, runner=path, electron=True)
    # macOS 的 Contents/MacOS/WorkBuddy
    if path.parent.name == "MacOS":
        cli = _cli_from_install_root(path.parent.parent)
        if cli is not None:
            return WorkBuddyRuntime(cli=cli, runner=path, electron=True)
    return None


def _platform_install_candidates() -> tuple[Path, ...]:
    """常见安装位置兜底（只用于自动发现，用户在页面显式配置优先）。"""
    if sys.platform == "win32":
        roots = [
            os.environ.get("ProgramFiles") or "C:\\Program Files",
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("ProgramW6432", ""),
        ]
        hits: list[Path] = []
        for raw in roots:
            if not raw:
                continue
            root = Path(raw)
            hits.append(root / "WorkBuddy" / "WorkBuddy.exe")
            hits.append(root / "Programs" / "WorkBuddy" / "WorkBuddy.exe")
        # 安装器允许换盘（WI-05）：环境变量只覆盖 C 盘，补注册表与非系统盘
        hits.extend(
            registry_candidates(
                ("WorkBuddy", "CodeBuddy"), ("WorkBuddy.exe", "CodeBuddy.exe")
            )
        )
        for drive in fixed_drive_roots():
            hits.append(drive / "Program Files" / "WorkBuddy" / "WorkBuddy.exe")
            hits.append(drive / "Program Files (x86)" / "WorkBuddy" / "WorkBuddy.exe")
        return tuple(hits)
    if sys.platform == "darwin":
        return (
            Path("/Applications/WorkBuddy.app"),
            Path.home() / "Applications" / "WorkBuddy.app",
        )
    return (
        Path("/opt/WorkBuddy/workbuddy"),
        Path("/usr/lib/workbuddy/workbuddy"),
    )


def resolve_workbuddy_runtime(configured: str | None) -> WorkBuddyRuntime | None:
    """解析生效的 WorkBuddy 运行时。

    优先级：页面配置 ``workbuddy_command`` > ``CODEBUDDY_CODE_PATH`` >
    PATH 里的 ``workbuddy`` > 平台常见安装位置。
    显式配置不可用时返回 None（不偷偷回退，便于提示用户路径填错了）。
    """
    configured_value = (configured or "").strip()
    if configured_value:
        runtime = _runtime_from_path(configured_value)
        if runtime is not None:
            return runtime
        # 页面允许填命令名（如 workbuddy / wb）；它不是路径时走 PATH。
        if "/" not in configured_value and "\\" not in configured_value:
            found = shutil.which(configured_value)
            if found:
                return _runtime_from_path(found)
        return None

    env_value = (os.environ.get("CODEBUDDY_CODE_PATH") or "").strip()
    if env_value:
        return _runtime_from_path(env_value)

    which_command = shutil.which("workbuddy") or shutil.which("wb")
    if which_command:
        resolved = _runtime_from_path(which_command)
        if resolved is not None:
            return resolved

    for candidate in _platform_install_candidates():
        resolved = _runtime_from_path(str(candidate))
        if resolved is not None:
            return resolved
    return None


def _parse_version(output: str) -> str | None:
    """从 ``codebuddy --version`` 输出里取版本号。

    输出形如 ``@tencent-ai/codebuddy-code/2.137.1 win32-x64 node-v22.21.1``，
    CLI 自带 package.json 的 version 是占位值 0.0.0，不能拿来显示。
    """
    for token in output.split():
        if token.startswith("@") and "/" in token:
            parts = token.split("/")
            if len(parts) >= 2:
                return parts[-1]
    match = re.search(r"\d+\.\d+\.\d+", output)
    return match.group(0) if match else (output.splitlines()[0].strip() or None)


class WorkBuddyAdapter(AgentAdapter):
    """通过 WorkBuddy 自带 CLI 的 ACP/stdio 提交真实任务。"""

    name = "workbuddy"
    adapter_id = "workbuddy"
    display_name = "WorkBuddy"
    executable = True

    # DeskMate 的执行模式 → WorkBuddy 的 Permission Mode（session/new 下发的
    # config_option_update 里可选项，经 session/set_config_option 设置）。
    #
    # 2026-09-16 实测修正（探针报文见 /tmp/wb-probe-traffic.jsonl）：
    # 旧注释里「Always Ask 下 WorkBuddy 不发 session/request_permission、
    # 10~30 秒直接退出」是误诊。真实行为是 default(Always Ask) 下遇到 Bash 类
    # 工具**会**发 session/request_permission（T+8~15s），应答后任务正常
    # end_turn；不应答则一直阻塞、不会自己退出。所以授权照常转给 UI 即可。
    #
    # 2026-09-17 实测再修正：plan **不是**硬隔离。它和 default 一样会逐个操作发
    # session/request_permission，只要有人应答就照样写盘（run_685d6db533 里
    # read-only 批准 Write 后文件真的落到了桌面）。昨夜「写不出」只是因为无人应答，
    # 请求被静默挡住。所以 read-only 的隔离由 AgentRunManager 在收到
    # permission_request 时自动回绝来保证，这里只按「弹窗频率」选档。
    #   - plan：每次问（read-only：真正的隔离在运行器层补）
    #   - default：Always Ask，逐个操作发授权请求（agent）
    #   - bypassPermissions：跳过所有授权弹窗（agent-full-access，无人值守）
    _MODE_TO_WB = {
        "read-only": "plan",
        "agent": "default",
        "agent-full-access": "bypassPermissions",
    }

    _PROBE_TTL_S = 300.0

    def __init__(
        self,
        timeout_s: float = 8.0,
        catalog_entry: AgentCatalogEntry | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.catalog_entry = catalog_entry or AgentCatalogEntry(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            enabled=True,
            commands=["workbuddy"],
            protocol="acp",
            capabilities=["task", "agent"],
            source_url=None,
            tags=["custom", "acp"],
            detail="",
        )
        self.name = self.catalog_entry.name
        self.adapter_id = self.catalog_entry.adapter or self.adapter_id
        self.display_name = self.catalog_entry.label or self.display_name
        self._configured = self.catalog_entry.config.get(
            f"{self.name}_command"
        ) or self.catalog_entry.config.get("command")
        self._internet_env = str(
            self.catalog_entry.config.get("internet_environment") or "internal"
        )
        self._probe_cache: tuple[float, str, str] | None = None  # (ts, status, detail)
        self._version_cache: dict[str, str | None] = {}
        self._active_clients: dict[str, AcpClient] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._permission_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_permissions: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, list[str]] = {}
        self._tool_calls: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ 探测

    async def detect(self) -> AgentInfo:
        runtime = resolve_workbuddy_runtime(self._configured)
        if runtime is None or runtime.runner is None:
            detail = "未检测到 WorkBuddy，请在下方填写 WorkBuddy 可执行文件完整路径"
            if runtime is not None and runtime.runner is None:
                detail = (
                    f"已找到 CLI（{runtime.cli}），但本机没有可用的 Node 运行时，"
                    f"也没有可当 Node 用的 WorkBuddy 桌面端。请填写 WorkBuddy.exe 完整路径。"
                )
            if self._configured:
                detail += f"（当前配置：{self._configured}）"
            return self._info("not_installed", False, detail=detail)

        version = await self._version(runtime)
        status, detail = await self._probe(runtime)
        return self._info(
            status,
            status == "ready",
            version=version,
            command=str(runtime.cli),
            protocol="acp",
            detail=detail,
        )

    async def _version(self, runtime: WorkBuddyRuntime) -> str | None:
        """取 CLI 版本：只有 --version 会打印真实版本，结果按路径缓存。"""
        key = str(runtime.cli)
        if key in self._version_cache:
            return self._version_cache[key]
        version = await asyncio.to_thread(self._version_blocking, runtime)
        self._version_cache[key] = version
        return version

    def _version_blocking(self, runtime: WorkBuddyRuntime) -> str | None:
        runner = runtime.runner
        if runner is None:
            return None
        try:
            result = subprocess.run(
                [str(runner), str(runtime.cli), "--version"],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                env=self._child_env(runtime),
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        output = (result.stdout or result.stderr or "").strip()
        return _parse_version(output) if output else None

    async def _probe(self, runtime: WorkBuddyRuntime) -> tuple[str, str]:
        """握手探测登录态：initialize + session/new，结果按 TTL 缓存。

        未登录时 session/new 会立刻返回 -32000，不调用模型、不消耗积分，
        比跑一次真实提问（8 秒 + 积分）便宜得多。
        """
        cached = self._probe_cache
        if cached is not None and (time.monotonic() - cached[0]) < self._PROBE_TTL_S:
            return cached[1], cached[2]

        client: AcpClient | None = None
        try:
            client = await self._spawn(runtime, logs_dir=None)
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "DeskMate", "version": "0.1.0"},
                },
                timeout_s=20.0,
            )
            await client.request(
                "session/new",
                {"cwd": str(Path.home()), "mcpServers": []},
                timeout_s=30.0,
            )
            result = ("ready", "WorkBuddy 已就绪：CLI 可启动、账号已登录，可提交真实任务。")
        except AcpRequestError as exc:
            if exc.auth_required:
                result = (
                    "auth_required",
                    f"WorkBuddy 已安装且 CLI 可运行，但账号未登录或登录已失效。"
                    f"{_LOGIN_HINT}（原始错误：{exc}）",
                )
            else:
                result = ("error", f"WorkBuddy 握手失败：{exc}")
        except (AcpError, OSError) as exc:
            result = ("error", f"WorkBuddy CLI 启动失败：{exc}")
        finally:
            if client is not None:
                await client.close()

        self._probe_cache = (time.monotonic(), result[0], result[1])
        return result

    def invalidate_probe(self) -> None:
        """用户点「重新检测」时清掉缓存。"""
        self._probe_cache = None

    def _info(
        self,
        status: str,
        available: bool,
        *,
        version: str | None = None,
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
            version=version,
            command=command,
            protocol=protocol,
            capabilities=list(self.catalog_entry.capabilities),
            tags=list(self.catalog_entry.tags),
            source_url=self.catalog_entry.source_url,
            detail=detail,
        )

    # ------------------------------------------------------------------ 启动

    def _child_env(self, runtime: WorkBuddyRuntime) -> dict[str, str]:
        """子进程环境：保留基础变量，只叠加 CLI 需要的几项。

        ``SERVER__PORT=0`` 是必需的：WorkBuddy 桌面端与 CLI 会抢同一个本地端口，
        不设会出现「卡住不返回、日志里 waiting for endpoint」。
        """
        env = dict(os.environ)
        env.pop("ELECTRON_RUN_AS_NODE", None)
        if runtime.electron:
            env["ELECTRON_RUN_AS_NODE"] = "1"
        env["CODEBUDDY_DISABLE_IDE"] = "1"
        env["SERVER__PORT"] = "0"
        env["SERVER__HOST"] = "127.0.0.1"
        env["CODEBUDDY_INTERNET_ENVIRONMENT"] = self._internet_env
        env["NO_COLOR"] = "1"
        return env

    async def _spawn(
        self,
        runtime: WorkBuddyRuntime,
        *,
        cwd: str | None = None,
        logs_dir: Path | None,
        on_update=None,
        on_permission=None,
        stderr_log_name: str = "workbuddy-acp-stderr.log",
    ) -> AcpClient:
        assert runtime.runner is not None
        return await AcpClient.spawn(
            str(runtime.runner),
            args=[str(runtime.cli), "--acp"],
            cwd=cwd or str(Path.home()),
            env=self._child_env(runtime),
            on_update=on_update,
            on_permission=on_permission,
            logs_dir=logs_dir,
            stderr_log_name=stderr_log_name,
        )

    # ------------------------------------------------------------------ 执行

    async def run(
        self,
        request: AgentTaskRequest,
        on_update,
    ) -> AgentTaskResult:
        runtime = resolve_workbuddy_runtime(self._configured)
        if runtime is None or runtime.runner is None:
            raise AgentExecutionError("WorkBuddy 不可用：未检测到可执行的 CLI。")

        self._outputs[request.task_id] = []
        self._tool_calls[request.task_id] = []
        self._cancel_events[request.task_id] = asyncio.Event()
        # 与 codex.py 一致默认落 /tmp/deskmate-acp-logs；按 task 分目录，
        # 否则多次运行的 stderr 日志会互相覆盖，出问题时没有证据可查。
        raw_logs_dir = request.config.get("logs_dir") or "/tmp/deskmate-acp-logs"
        logs_dir = Path(str(raw_logs_dir)).expanduser() / request.task_id
        client = await self._spawn(
            runtime,
            cwd=request.cwd,
            logs_dir=logs_dir,
            on_update=self._make_update_handler(request.task_id, on_update),
            on_permission=self._make_permission_handler(request.task_id, request.mode, on_update),
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
                    },
                    "clientInfo": {"name": "DeskMate", "version": "0.1.0"},
                },
                timeout_s=30.0,
            )
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
                        f"WorkBuddy 未登录，任务无法执行。{_LOGIN_HINT}"
                    ) from exc
                raise
            session_id = created.get("sessionId") if isinstance(created, dict) else None
            if not session_id:
                raise AgentExecutionError("WorkBuddy ACP session/new 未返回 sessionId")
            await self._apply_permission_mode(client, session_id, request.mode)
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
                    message="WorkBuddy 任务已取消",
                    session_id=session_id,
                )
            if stop_reason == "refusal":
                return AgentTaskResult(
                    status="failed",
                    message="",
                    session_id=session_id,
                    error="WorkBuddy 拒绝执行该任务",
                )
            message = "".join(self._outputs.get(request.task_id, [])).strip()
            tool_calls = self._tool_calls.get(request.task_id, [])
            if tool_calls:
                tool_summary = "工具调用：" + " → ".join(tool_calls[:10])
                if len(tool_calls) > 10:
                    tool_summary += f" …（共 {len(tool_calls)} 次）"
                message = (tool_summary + "\n\n" + message) if message else tool_summary
            if not message:
                message = "（WorkBuddy 未返回文本内容）"
            return AgentTaskResult(
                status="completed",
                message=message,
                session_id=session_id,
            )
        except asyncio.CancelledError:
            raise
        except AgentExecutionError:
            raise
        except Exception as exc:
            event = self._cancel_events.get(request.task_id)
            if event is not None and event.is_set():
                return AgentTaskResult(
                    status="cancelled",
                    message="WorkBuddy 任务已取消",
                    session_id=session_id,
                )
            raise AgentExecutionError(f"WorkBuddy 执行失败：{exc}") from exc
        finally:
            # WorkBuddy 的 ACP 没有 session/close（-32601），直接终止进程。
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
        future = self._permission_futures.pop(task_id, None)
        if future is not None and not future.done():
            future.set_result({"outcome": "cancelled"})

    async def approve(self, task_id: str, decision: str) -> None:
        future = self._permission_futures.get(task_id)
        if future is None or future.done():
            return
        pending = self._pending_permissions.get(task_id) or {}
        options = pending.get("options") or []
        if decision == "approved":
            option = _option_id_for_kind(options, "allow_once", "allow_always")
        else:
            option = _option_id_for_kind(options, "reject_once", "reject_always")
        if option is None:
            # ACP 只有 selected / cancelled 两种合法 outcome，没有 "rejected"
            future.set_result({"outcome": "cancelled"})
            return
        future.set_result({"outcome": "selected", "optionId": option})

    async def _apply_permission_mode(
        self, client: AcpClient, session_id: str, mode: str
    ) -> None:
        """把执行模式翻译成 WorkBuddy 的 Permission Mode。

        失败只记日志不中断：老版本 CLI 没有这个方法（-32601），
        那就退回「授权请求转发给 UI」的老路径。
        """
        # 未知模式兜底成 default(Always Ask)：宁可转 UI 授权，也不静默放行；
        # 卡住的风险由 runtime 的授权超时（自动拒绝）兜底。
        value = self._MODE_TO_WB.get(mode, "default")
        try:
            await client.request(
                "session/set_config_option",
                {"sessionId": session_id, "configId": "mode", "value": value},
                timeout_s=15.0,
            )
        except (AcpError, OSError) as exc:
            logger.warning("WorkBuddy 设置 Permission Mode 失败（%s）：%s", value, exc)

    # ------------------------------------------------------------- 事件处理

    _PHASE_ZH = {
        "preparing": "准备中",
        "model_requesting": "正在请求模型",
        "model_streaming": "模型输出中",
        "model_done": "模型输出完成",
        "tool_executing": "执行工具中",
        "idle": "空闲",
    }

    def _make_update_handler(self, task_id: str, on_update):
        async def handle(update: dict[str, Any]) -> None:
            kind = update.get("sessionUpdate")
            if kind == "agent_message_chunk":
                text = _content_text(update.get("content"))
                if text:
                    self._outputs.setdefault(task_id, []).append(text)
                    await on_update("progress", {"text": text, "progress": text.strip()[:300]})
                return
            if kind == "tool_call" or kind == "tool_call_update":
                title = str(update.get("title") or "").strip()
                if title:
                    self._tool_calls.setdefault(task_id, []).append(title)
                    await on_update("progress", {"text": "", "progress": title[:300]})
                return
            if kind == "session_info_update":
                phase = ((update.get("_meta") or {}).get("codebuddy.ai/agentPhase") or {}).get("phase")
                label = self._PHASE_ZH.get(str(phase))
                if label:
                    await on_update("progress", {"text": "", "progress": label})
            # 其余（usage_update / available_commands_update / config_option_update 等）忽略

        return handle

    def _make_permission_handler(self, task_id: str, mode: str, on_update):
        async def handle(params: dict[str, Any]) -> dict[str, Any]:
            options = params.get("options") or []
            # 全权限模式下无人值守，直接放行，避免卡在授权等待
            if mode == "agent-full-access":
                option = _option_id_for_kind(options, "allow_once", "allow_always")
                if option is not None:
                    return {"outcome": "selected", "optionId": option}
            self._pending_permissions[task_id] = params
            loop = asyncio.get_running_loop()
            future: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._permission_futures[task_id] = future
            # future 必须先登记再通知：运行器的 read-only 自动回绝是在这次回调里
            # 同步调 approve() 的，future 后建会让那次回绝静默丢失、任务永远挂着。
            await on_update(
                "permission_request",
                {"tool_call": params.get("toolCall"), "options": options},
            )
            return await future

        return handle


def _option_id_for_kind(options: object, *kinds: str) -> str | None:
    """按 ACP PermissionOption.kind 找出真正的 optionId。

    WorkBuddy 的 kind 与 optionId 不同名（实测：kind="allow_once" 对应
    optionId="allow"，kind="reject_once" 对应 optionId="reject"）。只按
    optionId 猜会命中不到 allow_once、静默升级成 allow_always（永久放行），
    因此必须以 kind 为准；kind 缺失时才退回「optionId 与 kind 同名」的惯例
    （Codex ACP 就是同名），保证两种执行器共用同一套逻辑不出错。
    """
    items = [item for item in (options or []) if isinstance(item, dict)]
    by_kind: dict[str, str] = {}
    by_id: set[str] = set()
    for item in items:
        option_id = str(item.get("optionId") or "").strip()
        if not option_id:
            continue
        by_id.add(option_id)
        kind = str(item.get("kind") or "").strip()
        if kind:
            by_kind.setdefault(kind, option_id)
    for kind in kinds:
        if kind in by_kind:
            return by_kind[kind]
        if kind in by_id:
            return kind
    return None


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
