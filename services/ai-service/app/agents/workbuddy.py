"""WorkBuddy 执行器适配器：复用本机 WorkBuddy 自带 CLI，通过 ACP 真实执行任务。

三个关键事实：

1. CLI 位置：WorkBuddy 安装目录内的
   ``resources/app.asar.unpacked/cli/bin/codebuddy``。
   它是 JS 脚本，**需要 Node 运行时**，不能像普通 exe 那样直接双击运行。
2. **终端用户不必安装 Node**：WorkBuddy 桌面端本身就是 Electron 应用，
   设 ``ELECTRON_RUN_AS_NODE=1`` 后可用 ``WorkBuddy.exe`` / ``WorkBuddy`` /
   ``Electron`` 当 Node 解释器用（实测 Node v22.21.1）——这是「零安装」约束的关键。
3. **凭据必须自备**（2026-10-01 实测，macOS + Windows 双端复现）：
   CLI 2.147.0 起把凭据落盘加密（``$wbEncrypted``），解封用的 protector key 只由
   桌面端主进程经 ``CODEBUDDY_SIDECAR_CREDENTIAL_BOOTSTRAP_SOCKET`` 下发给它自己的
   子进程。外部进程 fork 出来的 CLI 一律读不到 → ``at-rest-failures-v1.json`` 记
   ``missing-key`` → ``-32000 Authentication required``。**登录桌面端不再有用**，
   唯一通道是把 API Key 经 env（``CODEBUDDY_API_KEY`` / ``CODEBUDDY_AUTH_TOKEN``）
   传给子进程。这与「未安装」是两种完全不同的状态，必须分开呈现给用户。

探测分两步：``session/new`` 握手（便宜，但**不校验登录**，会假报就绪），
再跑一条极短 ``session/prompt`` 确认账号真能执行（见 ``_run_exec_probe``）。

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
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qiling_contracts.agent import AgentInfo

from app.agents.acp import (
    AcpClient,
    AcpError,
    AcpRequestError,
    content_text as _content_text,
    option_id_for_kind as _option_id_for_kind,
)
from app.agents.base import (
    AgentAdapter,
    AgentExecutionError,
    AgentTaskRequest,
    AgentTaskResult,
)
from app.agents.catalog import AgentCatalogEntry
from app.agents.secret_store import SecretStore, SecretStoreError
from app.agents.windows_install import fixed_drive_roots, registry_candidates

# CLI 相对安装根目录的位置（Windows / macOS 一致，只是根目录形态不同）
_CLI_RELATIVE = ("resources", "app.asar.unpacked", "cli", "bin", "codebuddy")

logger = logging.getLogger(__name__)

# 凭据引导文案：任何失败态都要给用户可执行的下一步。
# WorkBuddy CLI 2.147.0 起把凭据落盘加密，解封密钥只由桌面端主进程经私有通道
# 下发给它自己的子进程 —— 外部进程拉起的 CLI 一律读不到（at-rest-failures 记 missing-key）。
# 所以「打开桌面端登录」不再是一条可行路径，唯一正门是自备 API Key 注入子进程 env。
_LOGIN_HINT = (
    "WorkBuddy 的 API Key 需要先订阅付费版才能在 https://copilot.tencent.com/profile/ 申请"
    "（是否订阅由你决定，栖灵 不代购也不提供凭据）。"
    "拿到后填入执行器卡片里的「API Key」并保存，再点「测试连接」。"
    "WorkBuddy 2.147.0 起桌面端登录态只对它自己的子进程可见，栖灵 无法复用。"
)


def _credential_hint(raw: str) -> str:
    """凭据失败的具体形态决定下一步：没配 Key vs Key 被拒。

    带 Key 时 CLI 的报错里会带 401 与 auth-type；完全没有凭据时只有一句
    "Authentication required"。两者要让用户做的事不同，不能混成一句。
    """
    lowered = raw.lower()
    if "401" in lowered or "auth-type" in lowered:
        return (
            "WorkBuddy 拒绝了这把 API Key：可能是未订阅付费版、Key 已失效或额度用尽。"
            "请到 https://copilot.tencent.com/profile/ 核对订阅与 Key 后重填。"
        )
    return _LOGIN_HINT

# 真实执行探针：只握手证明不了「账号能跑任务」——账号为空时 session/new 照样成功，
# 却在 session/prompt 阶段回 refusal。这条极短、不碰文件、不调工具的提示词用来区分两者。
_EXEC_PROBE_PROMPT = "只回复两个字：就绪"


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


def _probe_workdir() -> str:
    """探测用的 CLI 工作目录：固定的临时目录，**不用用户主目录**。

    主目录可能非常大（Windows 上尤其），把它当 workspace 会让 CLI 白扫一遍；
    固定目录还让 CLI 自身日志文件名稳定可查。跨平台都落在系统临时目录下。
    """
    base = Path(tempfile.gettempdir()) / "qiling-workbuddy-probe"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return str(Path(tempfile.gettempdir()))
    return str(base)


class WorkBuddyAdapter(AgentAdapter):
    """通过 WorkBuddy 自带 CLI 的 ACP/stdio 提交真实任务。"""

    name = "workbuddy"
    adapter_id = "workbuddy"
    display_name = "WorkBuddy"
    executable = True

    # 栖灵 的执行模式 → WorkBuddy 的 Permission Mode（session/new 下发的
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
        # 网络环境（internal / ioa / cloudhosted / selfhosted）由 WorkBuddy 自身持久化
        # 状态决定：CLI 文档写明填错会 401 endpoint mismatch。只在显式配置时覆盖，
        # 不替用户猜环境。
        self._internet_env = str(
            self.catalog_entry.config.get("internet_environment") or ""
        ).strip()
        # 自备凭据：WorkBuddy CLI 2.147.0 起外部进程读不到桌面端登录态（凭据落盘加密，
        # protector key 只走桌面端私有通道），唯一可用通道是把 API Key 作为 env 传给
        # 子进程（官方 ACP 文档的 Zed 示例即如此）。留空则沿用系统环境里已有的
        # CODEBUDDY_API_KEY / CODEBUDDY_AUTH_TOKEN。
        self._api_key = str(
            self.catalog_entry.config.get(f"{self.name}_api_key")
            or self.catalog_entry.config.get("api_key")
            or ""
        ).strip()
        self._secret_store = SecretStore()
        if not self._api_key:
            try:
                self._api_key = self._secret_store.read(self.name) or ""
            except SecretStoreError:
                self._api_key = ""
        self._probe_cache: tuple[float, str, str] | None = None  # (ts, status, detail)
        # 真实 prompt 探测结果。健康检查带 3~5s 超时，而真实 prompt 要十几秒，
        # 所以它只在后台跑，detect() 读缓存，绝不占住请求。
        self._exec_probe: tuple[float, str, str] | None = None
        self._exec_task: asyncio.Task[None] | None = None
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
        if status == "ready":
            exec_status, exec_detail = self._exec_verdict(runtime)
            if exec_status is not None:
                status, detail = exec_status, exec_detail
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
        """握手探测：initialize + session/new，结果按 TTL 缓存。

        注意 session/new **不校验登录**，未登录也会照发 sessionId（旧结论说它会返回
        -32000，已在 2026-10-01 证伪）。所以它只能证明「CLI 起得来」，
        真伪由 _run_exec_probe 的 session/prompt 定夺。
        它便宜（不调用模型、不消耗积分），适合先给用户一个快速反馈。
        """
        cached = self._probe_cache
        if cached is not None and (time.monotonic() - cached[0]) < self._PROBE_TTL_S:
            return cached[1], cached[2]

        client: AcpClient | None = None
        try:
            client = await self._spawn(runtime, cwd=_probe_workdir(), logs_dir=None)
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "栖灵", "version": "0.1.0"},
                },
                timeout_s=20.0,
            )
            await client.request(
                "session/new",
                {"cwd": _probe_workdir(), "mcpServers": []},
                timeout_s=30.0,
            )
            result = ("ready", "WorkBuddy CLI 可启动、ACP 握手正常，正在核实账号是否可用。")
        except AcpRequestError as exc:
            if exc.auth_required:
                result = (
                    "auth_required",
                    f"WorkBuddy 已安装且 CLI 可运行，但没有可用的账号凭据。"
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

    def _exec_verdict(self, runtime: WorkBuddyRuntime) -> tuple[str | None, str | None]:
        """后台真实-prompt 探测的当前结论；必要时顺带发起一次。

        返回 (None, None) 表示还没有结论，调用方沿用握手结果。
        """
        cached = self._exec_probe
        if cached is not None and (time.monotonic() - cached[0]) < self._PROBE_TTL_S:
            return cached[1], cached[2]
        if self._exec_task is None or self._exec_task.done():
            self._exec_task = asyncio.create_task(self._run_exec_probe(runtime))
        return (cached[1], cached[2]) if cached is not None else (None, None)

    async def _probe_with_api_key(
        self,
        runtime: WorkBuddyRuntime,
        api_key: str | None = None,
    ) -> tuple[str, str]:
        """用指定 Key 执行真实 prompt 探测，返回状态与用户可读结论。"""
        client: AcpClient | None = None
        try:
            client = await self._spawn(
                runtime,
                cwd=_probe_workdir(),
                logs_dir=None,
                api_key=api_key,
            )
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "栖灵", "version": "0.1.0"},
                },
                timeout_s=20.0,
            )
            created = await client.request(
                "session/new",
                {"cwd": _probe_workdir(), "mcpServers": []},
                timeout_s=30.0,
            )
            session_id = created.get("sessionId") if isinstance(created, dict) else None
            if not session_id:
                result = ("error", "WorkBuddy session/new 未返回 sessionId")
            else:
                prompt_result = await client.request(
                    "session/prompt",
                    {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": _EXEC_PROBE_PROMPT}],
                    },
                    timeout_s=90.0,
                )
                stop_reason = (
                    prompt_result.get("stopReason")
                    if isinstance(prompt_result, dict)
                    else None
                )
                if stop_reason == "refusal":
                    meta = prompt_result.get("_meta") if isinstance(prompt_result, dict) else None
                    raw_error = str((meta or {}).get("codebuddy.ai/errorMessage") or "")
                    result = (
                        "auth_required",
                        "WorkBuddy 能建立会话但拒绝执行任务。\n" + _credential_hint(raw_error),
                    )
                else:
                    result = ("ready", "WorkBuddy 已就绪：CLI 可启动、账号可提交真实任务。")
        except AcpRequestError as exc:
            if exc.auth_required:
                result = (
                    "auth_required",
                    f"WorkBuddy 账号凭据不可用。{_LOGIN_HINT}（原始错误：{exc}）",
                )
            else:
                result = ("error", f"WorkBuddy 真实执行探测失败：{exc}")
        except (AcpError, OSError) as exc:
            result = ("error", f"WorkBuddy CLI 启动失败：{exc}")
        finally:
            if client is not None:
                await client.close()
        return result

    async def _run_exec_probe(self, runtime: WorkBuddyRuntime) -> None:
        """后台真实-prompt 探测；异常只影响结论，不污染事件循环。"""
        result = await self._probe_with_api_key(runtime)
        self._exec_probe = (time.monotonic(), result[0], result[1])

    async def validate_api_key(self, api_key: str) -> None:
        """先用临时 Key 真实探测，成功后才允许调用方写入安全存储。"""
        runtime = resolve_workbuddy_runtime(self._configured)
        if runtime is None or runtime.runner is None:
            raise AgentExecutionError("WorkBuddy 不可用：未检测到可执行的 CLI。")
        status, detail = await self._probe_with_api_key(runtime, api_key.strip())
        if status != "ready":
            raise AgentExecutionError(detail or "WorkBuddy API Key 验证失败。")

    def invalidate_probe(self) -> None:
        """用户点「重新检测」时清掉缓存。"""
        self._probe_cache = None
        self._exec_probe = None

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

    def _child_env(
        self,
        runtime: WorkBuddyRuntime,
        api_key: str | None = None,
    ) -> dict[str, str]:
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
        if self._internet_env:
            env["CODEBUDDY_INTERNET_ENVIRONMENT"] = self._internet_env
        key = api_key if api_key is not None else self._api_key
        if key:
            env["CODEBUDDY_API_KEY"] = key
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
        api_key: str | None = None,
    ) -> AcpClient:
        assert runtime.runner is not None
        return await AcpClient.spawn(
            str(runtime.runner),
            args=[str(runtime.cli), "--acp"],
            cwd=cwd or _probe_workdir(),
            env=self._child_env(runtime, api_key),
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
        # 与 codex.py 一致默认落 /tmp/qiling-acp-logs；按 task 分目录，
        # 否则多次运行的 stderr 日志会互相覆盖，出问题时没有证据可查。
        raw_logs_dir = request.config.get("logs_dir") or Path(tempfile.gettempdir()) / "qiling-acp-logs"
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
                    "clientInfo": {"name": "栖灵", "version": "0.1.0"},
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
                    self._exec_probe = None
                    raise AgentExecutionError(
                        f"WorkBuddy 账号凭据不可用，任务无法执行。{_credential_hint(str(exc))}"
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
