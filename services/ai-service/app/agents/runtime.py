"""Agent Run 持久化与后台调度。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.task import Task

from app.agents.base import (
    AgentAdapter,
    AgentCancelled,
    AgentExecutionError,
    AgentExecutionUnsupported,
    AgentTaskRequest,
)
from app.agents.registry import AgentRegistry
from app.routing.store import TaskStore

# 办公域：外部 Agent 不可用时都能降级到本地办公执行器。
_OFFICE_KINDS = {"word", "excel", "ppt", "pdf", "image", "email"}
# 每种办公任务的产物后缀，用于执行后识别本次新增/修改的文件。
_OFFICE_SUFFIXES: dict[str, set[str]] = {
    "word": {".doc", ".docx"},
    "excel": {".xls", ".xlsx", ".xlsm"},
    "ppt": {".ppt", ".pptx"},
    "pdf": {".pdf"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"},
    "email": {".eml", ".msg"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _permission_summary(tool_call: object) -> str:
    """从 ACP session/request_permission 的 toolCall 里提取人类可读摘要。

    Codex 的 toolCall 带 title/name；WorkBuddy 两者都没有，只有 rawInput 里的
    工具参数（2026-09-17 实测各家 key：Bash→command/description，
    Write/Read→file_path，DeferExecuteTool→toolName/params）。按此顺序兜底，
    否则卡片只能显示「等待授权」或 WorkBuddy 的包装器名，用户看不懂要批什么。
    """
    if not isinstance(tool_call, dict):
        return "等待授权"
    title = str(tool_call.get("title") or tool_call.get("name") or "").strip()
    if title:
        return title[:300]
    meta = tool_call.get("_meta")
    tool_name = ""
    if isinstance(meta, dict):
        tool_name = str(meta.get("codebuddy.ai/toolName") or "").strip()
    raw_input = tool_call.get("rawInput")
    if isinstance(raw_input, dict):
        # DeferExecuteTool 只是分发器：真实操作在它自己的 toolName 里（如
        # ExitPlanMode「离开只读规划、开始动手」），直接显示包装器名等于没说。
        deferred = str(raw_input.get("toolName") or "").strip()
        if deferred:
            params = raw_input.get("params")
            prompts = params.get("allowedPrompts") if isinstance(params, dict) else None
            prompt = ""
            if isinstance(prompts, list) and prompts and isinstance(prompts[0], dict):
                prompt = str(prompts[0].get("prompt") or "").strip()
            return (f"{deferred}：{prompt}" if prompt else deferred)[:300]
        for key in ("command", "description"):
            value = str(raw_input.get(key) or "").strip()
            if value:
                return value[:300]
        # 只有路径/查询时补上工具名，否则批准者分不清是读还是写
        for key in ("file_path", "path", "url", "query", "pattern"):
            value = str(raw_input.get(key) or "").strip()
            if value:
                return (f"{tool_name}：{value}" if tool_name else value)[:300]
    return f"{tool_name} 操作"[:300] if tool_name else "等待授权"


logger = logging.getLogger(__name__)


class AgentRun(BaseModel):
    """一次外部 Agent 执行。只放在 ai-service，不属于共享 contracts。"""

    run_id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:10]}")
    task_id: str
    executor: str
    status: str = "queued"
    session_id: str | None = None
    mode: str = "read-only"
    progress: str = ""
    result: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    finished_at: str | None = None

    def touch(self) -> None:
        self.updated_at = _now()


class AgentRunStore:
    def __init__(self, root: Path, max_items: int = 300) -> None:
        self._max_items = max_items
        self._dir = root / "agent_runs"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, AgentRun] = {}
        self._load()

    def _load(self) -> None:
        for path in sorted(self._dir.glob("*.json")):
            try:
                run = AgentRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            self._items[run.run_id] = run

    def put(self, run: AgentRun) -> AgentRun:
        run.touch()
        self._items[run.run_id] = run
        if len(self._items) > self._max_items:
            oldest = min(self._items.values(), key=lambda item: item.created_at)
            self._items.pop(oldest.run_id, None)
            old_path = self._dir / f"{oldest.run_id}.json"
            if old_path.exists():
                old_path.unlink()
        path = self._dir / f"{run.run_id}.json"
        path.write_text(
            run.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return run

    def get(self, run_id: str) -> AgentRun | None:
        return self._items.get(run_id)

    def latest_for_task(self, task_id: str) -> AgentRun | None:
        hits = [run for run in self._items.values() if run.task_id == task_id]
        return max(hits, key=lambda run: run.created_at, default=None)

    def list_recent(self, limit: int = 50) -> list[AgentRun]:
        items = sorted(self._items.values(), key=lambda run: run.updated_at, reverse=True)
        return items[:limit]


class AgentRunManager:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        store: AgentRunStore,
        task_store: TaskStore,
        hub,
        memory,
        data_dir: Path,
        conversations=None,
        project_nodes=None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.task_store = task_store
        self.hub = hub
        self.memory = memory
        self.data_dir = data_dir
        # 任务进展回流到来源会话（对话页可见）；未注入时静默跳过
        self.conversations = conversations
        # 项目节点联动；未注入时静默跳过
        self.project_nodes = project_nodes
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._approval_timers: dict[str, asyncio.Task[None]] = {}  # task_id -> reminder timer
        self._approval_deadlines: dict[str, asyncio.Task[None]] = {}  # task_id -> 超时自动拒绝
        self._stale_reminded: set[str] = set()  # 已提醒过的 run_id，只提醒一次
        # 服务重启后，磁盘上仍是 queued/running 的 run 必然没有在跑：拉起它的
        # asyncio 任务随进程一起没了。判据是「进程存活」而不是「跑了多久」，
        # 所以长任务不会被误杀（Celery/Sidekiq 启动时回收孤儿任务同此思路）。
        self._reconcile_orphaned_runs()

    def _reconcile_orphaned_runs(self) -> None:
        """启动时把上次进程遗留的未终态 run 判失败，避免任务台永远转圈。"""
        for run in self.store.list_recent(limit=1000):
            if run.status not in ("queued", "running"):
                continue
            run.status = "failed"
            run.error = "服务重启，任务已中断；可重新运行。"
            run.finished_at = _now()
            self.store.put(run)
            task = self.task_store.get(run.task_id)
            if task is not None:
                task.status = "failed"
                self.task_store.put(task)

    def _find_previous_session(self, conversation_id: str | None, exclude_task_id: str) -> str | None:
        """找到同一 conversation 下最近一次已完成的 run 的 session_id。"""
        if not conversation_id:
            return None
        # 找到同一 conversation 的所有 task_id
        conv_task_ids = {
            t.task_id for t in self.task_store._items.values()
            if t.conversation_id == conversation_id and t.task_id != exclude_task_id
        }
        if not conv_task_ids:
            return None
        # 找到这些 task 的已完成 run
        hits = [
            run for run in self.store._items.values()
            if run.task_id in conv_task_ids
            and run.status == "completed"
            and run.session_id
        ]
        if not hits:
            return None
        latest = max(hits, key=lambda run: run.created_at)
        return latest.session_id

    async def _try_office_fallback(
        self,
        task: Task,
        original_adapter: AgentAdapter,
        original_name: str,
    ) -> AgentAdapter:
        """外部 Agent 不可用时，办公任务降级到本地执行器。"""
        if task.work_kind not in _OFFICE_KINDS:
            raise AgentExecutionUnsupported(
                f"{original_name} 当前不可执行；此任务类型不支持本地降级。"
            )
        fallback = self.registry.get("local-office")
        if fallback is None:
            raise AgentExecutionUnsupported(
                f"{original_name} 当前不可执行且本地办公执行器未注册。"
            )
        logger.info(
            "办公任务降级：%s 不可用，使用本地办公执行器",
            original_name,
        )
        return fallback

    async def _notify_conversation(self, task: Task, text: str) -> None:
        """把任务进展写回来源会话；没有会话或没有存储时跳过。"""
        if self.conversations is None or not task.conversation_id or not text:
            return
        try:
            await self.conversations.append_message(task.conversation_id, "tool", text)
        except Exception:
            pass  # 回写失败不影响任务本身

    async def _compose_prompt(self, task: Task) -> str:
        """多轮上下文：把对话页此前几轮拼进任务提示词，后台 agent 才不会忘掉前文。

        浏览器执行器（搜索/打开）按自己的语法解析 prompt，不能注入对话历史。
        """
        if self.conversations is None or not task.conversation_id:
            return task.input
        try:
            conversation = await self.conversations.get(task.conversation_id)
        except Exception:
            return task.input
        if conversation is None:
            return task.input
        # 末条是本轮刚写入的指令，排除后取更早的轮次
        prior = [m for m in conversation.messages[:-1] if (m.content or "").strip()]
        lines: list[str] = []
        for msg in prior[-6:]:
            label = {"user": "用户", "tool": "工具结果"}.get(msg.role, "助手")
            lines.append(f"{label}：{msg.content.strip()[:400]}")
        parts: list[str] = []
        if lines:
            parts.append("对话上下文（此前几轮，仅作参考）：\n" + "\n".join(lines))
        last_user = next(
            (m for m in reversed(conversation.messages) if m.role == "user"), None
        )
        attachments = getattr(last_user, "attachments", None) or []
        if attachments:
            names = [f"- {item.name}" for item in attachments]
            parts.append("本轮附件文件（位于任务工作目录，可用相对路径读取）：\n" + "\n".join(names))
        parts.append(f"当前任务：{task.input}")
        if task.work_kind == "word":
            parts.append(
                "Word 文档处理要求：读取并理解相关文档后再修改；默认不要覆盖原文件，"
                "请在同一目录生成带 _edited 后缀的新 .docx（旧 .doc 如无法直接编辑，"
                "请明确说明并保留原文件）；完成后在最终回复中列出输出文件路径和修改摘要。"
            )
        elif task.work_kind == "excel":
            parts.append(
                "Excel 表格处理要求：先读取并理解工作表结构和数据，再进行清洗、计算、"
                "分析或图表处理；默认不要覆盖原文件，请在同一目录生成带 _processed 后缀"
                "的新 .xlsx（旧 .xls 如无法直接编辑，请明确说明并保留原文件）；完成后"
                "在最终回复中列出输出文件路径、关键统计结果和修改摘要。"
            )
        elif task.work_kind == "ppt":
            parts.append(
                "PowerPoint 演示文稿处理要求：先读取并理解页面结构、内容层级和视觉样式，"
                "再进行内容修改、结构调整、排版或美化；默认不要覆盖原文件，请在同一目录"
                "生成带 _edited 后缀的新 .pptx（旧 .ppt 如无法直接编辑，请明确说明并保留"
                "原文件）；完成后在最终回复中列出输出文件路径、页面变更摘要和视觉调整摘要。"
            )
        elif task.work_kind == "pdf":
            parts.append(
                "PDF 处理要求：先读取并理解 PDF 内容（含表格与扫描件说明），再进行提取、"
                "摘要、合并拆分或表单处理；默认不要覆盖原文件，生成带 _processed 后缀的新文件；"
                "扫描件若无法直接提取文字请明确说明需要 OCR。完成后列出输出文件路径和变更摘要。"
            )
        elif task.work_kind == "image":
            parts.append(
                "图片处理要求：先读取图片基本信息（尺寸/格式/EXIF），再进行缩放、裁剪、旋转、"
                "格式转换、压缩、水印或批量处理；默认不要覆盖原文件，生成带 _processed 后缀的新文件；"
                "需要识别图片文字时说明使用 OCR。完成后列出输出文件路径和处理摘要。"
            )
        elif task.work_kind == "email":
            parts.append(
                "邮件处理要求：先解析邮件头、正文与附件，再进行摘要、归类或整理；"
                "回复/发送邮件需要显式授权，默认只做本地解析，不自动发送。"
                "完成后列出解析结论与（如有）生成的输出文件路径。"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _file_snapshot(cwd: str) -> dict[str, tuple[int, int]]:
        """记录目录下文件的 mtime/size，用于识别本次执行产物。"""
        root = Path(cwd)
        if not root.is_dir():
            return {}
        snapshot: dict[str, tuple[int, int]] = {}
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    stat = path.stat()
                except OSError:
                    continue
                snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
        return snapshot

    @staticmethod
    def _office_artifacts(
        cwd: str,
        before: dict[str, tuple[int, int]],
        suffixes: set[str],
    ) -> list[str]:
        """返回本次新增或变更的办公文件，避免把项目旧文件当成结果。"""
        root = Path(cwd)
        if not root.is_dir():
            return []
        artifacts: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            current = (stat.st_mtime_ns, stat.st_size)
            if before.get(str(path)) != current:
                artifacts.append(str(path))
        return sorted(artifacts)
    async def execute(
        self,
        task: Task,
        *,
        executor: str | None = None,
        mode: str = "read-only",
        cwd: str | None = None,
    ) -> AgentRun:
        if task.category not in ("delegate_backend", "request_approval"):
            raise ValueError("只有后台任务可以交给外部执行器")
        if task.status in ("running", "completed", "cancelled"):
            raise ValueError(f"任务当前状态不能执行：{task.status}")
        executor_name = executor or task.preferred_executor or self.registry.default_executor
        adapter = self.registry.get(executor_name)
        if adapter is None:
            raise ValueError(f"执行器不存在：{executor_name}")
        _is_office = task.work_kind in _OFFICE_KINDS
        if not adapter.executable:
            if _is_office:
                adapter = await self._try_office_fallback(task, adapter, executor_name)
            else:
                raise AgentExecutionUnsupported(f"{executor_name} 尚未接入真实执行")
        else:
            availability = await adapter.detect()
            if not availability.enabled:
                if _is_office:
                    adapter = await self._try_office_fallback(task, adapter, executor_name)
                else:
                    raise AgentExecutionUnsupported(
                        f"{executor_name} 已停用：到「我的智能体」页面重新启用后才能运行任务。"
                    )
            elif not availability.available or availability.integration_status != "ready":
                if _is_office:
                    adapter = await self._try_office_fallback(task, adapter, executor_name)
                else:
                    raise AgentExecutionUnsupported(
                        f"{executor_name} 当前不可执行（{availability.integration_status}）："
                        f"{availability.detail}"
                    )
        # 降级后更新执行器名称
        if adapter.name != executor_name:
            executor_name = adapter.name

        latest = self.store.latest_for_task(task.task_id)
        if latest and latest.status in ("running", "awaiting_approval"):
            raise ValueError("任务已有进行中的 run")

        # 查找同一 conversation 下之前的 session_id（用于多轮续接）
        previous_session_id = self._find_previous_session(task.conversation_id, task.task_id)

        run = AgentRun(
            task_id=task.task_id,
            executor=executor_name,
            mode=mode if mode in ("read-only", "agent", "agent-full-access") else "read-only",
        )
        self.store.put(run)
        task.status = "running"
        task = self.task_store.put(task)
        await self._publish(
            "task.started",
            task,
            run,
            payload={"executor": executor_name, "mode": run.mode},
        )
        await self._notify_conversation(
            task,
            f"▶ 已交给 {executor_name}（{run.mode}）执行。",
        )
        background = asyncio.create_task(
            self._run_task(run, task, adapter, previous_session_id, cwd)
        )
        self._tasks[task.task_id] = background
        return run

    async def _resolve_cwd(self, task: Task) -> str:
        """项目对话把执行器工作目录切到项目根；普通对话仍用 DeskMate 数据目录的上一级。"""
        fallback = str(self.data_dir.parent)
        if not task.conversation_id or self.conversations is None:
            return fallback
        try:
            conversation = await self.conversations.get(task.conversation_id)
        except Exception:
            return fallback
        project = (conversation.project or "").strip() if conversation else ""
        return project if project and Path(project).is_dir() else fallback

    async def _run_task(
        self,
        run: AgentRun,
        task: Task,
        adapter: AgentAdapter,
        previous_session_id: str | None = None,
        cwd_override: str | None = None,
    ) -> None:
        try:
            resolved_cwd = cwd_override or await self._resolve_cwd(task)
            before = (
                self._file_snapshot(resolved_cwd)
                if task.work_kind in _OFFICE_KINDS
                else {}
            )
            prompt = task.input if run.executor == "browser" else await self._compose_prompt(task)
            result = await adapter.run(
                AgentTaskRequest(
                    task_id=task.task_id,
                    prompt=prompt,
                    cwd=resolved_cwd,
                    conversation_id=task.conversation_id,
                    session_id=previous_session_id,
                    mode=run.mode,
                    config={"logs_dir": str(self.data_dir / "run_logs"), "work_kind": task.work_kind},
                ),
                on_update=lambda kind, payload: self._on_update(run, kind, payload),
            )
        except asyncio.CancelledError:
            return
        except AgentCancelled:
            await self._finish(run, task, "cancelled", message="已取消")
            return
        except AgentExecutionError as exc:
            await self._finish(run, task, "failed", error=str(exc))
            return
        except Exception as exc:
            await self._finish(run, task, "failed", error=str(exc))
            return
        if result.status not in ("completed", "failed", "cancelled"):
            result.status = "completed"
        if result.status == "completed" and task.work_kind in _OFFICE_KINDS:
            artifacts = self._office_artifacts(
                resolved_cwd, before, _OFFICE_SUFFIXES.get(task.work_kind, set())
            )
            if artifacts:
                artifact_lines = "\n".join(f"- {path}" for path in artifacts)
                result.message = (
                    f"{result.message.rstrip()}\n\n输出文件：\n{artifact_lines}"
                ).strip()
        await self._finish(
            run,
            task,
            result.status,
            message=result.message,
            error=result.error,
            session_id=result.session_id,
        )

    async def _on_update(self, run: AgentRun, kind: str, payload: dict) -> None:
        if kind == "session_ready":
            run.session_id = str(payload.get("session_id") or "")
            run.status = "running"
            run.progress = payload.get("mode") or run.progress
            self.store.put(run)
            task = self.task_store.get(run.task_id)
            if task is None:
                return
            task.status = "running"
            task = self.task_store.put(task)
            await self._publish(
                "task.started",
                task,
                run,
                payload={"session_id": run.session_id, "mode": run.mode},
            )
            return
        if kind == "progress":
            run.progress = str(payload.get("progress") or payload.get("text") or "").strip()[:600]
            if run.status != "awaiting_approval":
                run.status = "running"
            self.store.put(run)
            task = self.task_store.get(run.task_id)
            if task is None:
                return
            if task.status != "awaiting_approval":
                task.status = "running"
                task = self.task_store.put(task)
            bubble = (run.progress[:60] + "…") if len(run.progress) > 60 else run.progress
            await self._publish(
                "task.progress",
                task,
                run,
                payload={"progress": run.progress, "bubble": bubble or "执行中…"},
            )
            return
        if kind == "permission_request":
            summary = _permission_summary(payload.get("tool_call"))
            task = self.task_store.get(run.task_id)
            if task is None:
                return
            if run.mode == "read-only":
                # read-only 的隔离只能由运行器自己收口：WorkBuddy 的 plan 和 Codex 的
                # 只读档都只是「每次问」（2026-09-17 实测：plan 下写文件有人应答就落盘），
                # 转给 UI 等于没隔离。这里不进 awaiting_approval、不弹卡片，
                # 直接走与人工拒绝同一条回绝路径。
                adapter = self.registry.get(run.executor)
                if adapter is not None:
                    await adapter.approve(run.task_id, "rejected")
                run.progress = summary
                self.store.put(run)
                await self._notify_conversation(
                    task,
                    f"⛔ read-only 模式不执行需授权的操作，已自动拒绝：{summary}",
                )
                return
            run.status = "awaiting_approval"
            run.progress = summary
            self.store.put(run)
            task.status = "awaiting_approval"
            task = self.task_store.put(task)
            await self._publish(
                "task.approval_required",
                task,
                run,
                payload={
                    "tool_call": payload.get("tool_call"),
                    "options": payload.get("options"),
                    "bubble": f"需要确认：{run.progress[:40]}",
                },
            )
            await self._notify_conversation(
                task,
                f"⚠ {run.executor}（{run.mode}）请求授权：{run.progress}",
            )
            self._start_approval_timer(run, task)


    _APPROVAL_REMINDER_SECONDS = 30
    # 无人值守场景不能让 run 永远挂在 awaiting_approval：超时按拒绝收口，
    # 复用人工拒绝同一条路径（状态机 / 事件 / 会话回流都一致）。
    _APPROVAL_TIMEOUT_SECONDS = 300

    def _start_approval_timer(self, run: AgentRun, task: Task) -> None:
        """等待授权超过 N 秒未响应时广播提醒；超过 M 秒自动按拒绝收口。"""
        old = self._approval_timers.pop(run.task_id, None)
        if old is not None and not old.done():
            old.cancel()
        old_deadline = self._approval_deadlines.pop(run.task_id, None)
        if old_deadline is not None and not old_deadline.done():
            old_deadline.cancel()

        async def _fire() -> None:
            try:
                await asyncio.sleep(self._APPROVAL_REMINDER_SECONDS)
            except asyncio.CancelledError:
                return
            self._approval_timers.pop(run.task_id, None)
            current_run = self.store.get(run.run_id)
            if current_run is None or current_run.status != "awaiting_approval":
                return
            await self._publish(
                "task.approval_reminder",
                task,
                current_run,
                payload={"bubble": f"等待确认已 {self._APPROVAL_REMINDER_SECONDS} 秒，需要你决定"},
            )

        self._approval_timers[run.task_id] = asyncio.create_task(_fire())

        async def _expire() -> None:
            try:
                await asyncio.sleep(self._APPROVAL_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                return
            # 先摘掉自己，避免 approve_run 里的 _cancel_approval_timer 反手
            # 取消当前任务，导致后面的会话回流被 CancelledError 打断
            self._approval_deadlines.pop(run.task_id, None)
            current_run = self.store.get(run.run_id)
            if current_run is None or current_run.status != "awaiting_approval":
                return
            try:
                await self.approve_run(run.run_id, "rejected")
            except (KeyError, ValueError):
                return
            await self._notify_conversation(
                task,
                f"⏱ 等待授权超过 {self._APPROVAL_TIMEOUT_SECONDS // 60} 分钟，"
                "已自动拒绝该操作。",
            )

        self._approval_deadlines[run.task_id] = asyncio.create_task(_expire())

    def _cancel_approval_timer(self, task_id: str) -> None:
        for registry in (self._approval_timers, self._approval_deadlines):
            timer = registry.pop(task_id, None)
            if timer is not None and not timer.done():
                timer.cancel()

    async def cancel_run(self, run_id: str) -> AgentRun:
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        task = self.task_store.get(run.task_id)
        if task is None:
            raise KeyError(run.task_id)
        adapter = self.registry.get(run.executor)
        if adapter is not None and run.status in ("running", "awaiting_approval"):
            await adapter.cancel(task.task_id, run.session_id)
        self._cancel_approval_timer(task.task_id)
        background = self._tasks.pop(task.task_id, None)
        if background is not None and not background.done():
            background.cancel()
        run.status = "cancelled"
        run.error = None
        run.finished_at = _now()
        self.store.put(run)
        task.status = "cancelled"
        task = self.task_store.put(task)
        await self._publish("task.cancelled", task, run)
        await self._notify_conversation(task, "任务已取消。")
        self._record_memory("task.cancelled", task, run)
        return run

    async def approve_run(self, run_id: str, decision: str) -> AgentRun:
        if decision not in ("approved", "rejected"):
            raise ValueError("decision 必须是 approved 或 rejected")
        run = self.store.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status != "awaiting_approval":
            raise ValueError("run 不在等待授权状态")
        adapter = self.registry.get(run.executor)
        if adapter is None:
            raise KeyError(run.executor)
        self._cancel_approval_timer(run.task_id)
        await adapter.approve(run.task_id, decision)
        run.status = "running"
        run.progress = "已" + ("批准" if decision == "approved" else "拒绝") + "当前操作"
        self.store.put(run)
        task = self.task_store.get(run.task_id)
        if task is not None:
            task.status = "running"
            task = self.task_store.put(task)
            await self._publish("task.started", task, run)
        return run

    async def _finish(
        self,
        run: AgentRun,
        task: Task,
        status: str,
        *,
        message: str = "",
        error: str | None = None,
        session_id: str | None = None,
    ) -> None:
        run.status = status
        run.result = message or None
        run.error = error
        run.session_id = session_id or run.session_id
        run.finished_at = _now()
        self.store.put(run)
        task.status = status
        task = self.task_store.put(task)
        self._cancel_approval_timer(task.task_id)
        event_type = {
            "completed": "task.completed",
            "failed": "task.failed",
            "cancelled": "task.cancelled",
        }[status]
        if status == "completed":
            summary = (message or run.progress or "任务完成")[:60]
            bubble = f"✓ {summary}"
            speak_text = f"任务完成了。{summary}"
        elif status == "failed":
            summary = (error or "未知错误")[:60]
            bubble = f"✗ {summary}"
            speak_text = f"任务没成功。{summary}"
        else:
            bubble = "已取消"
            speak_text = None
        if status == "completed":
            notify = f"✓ 任务完成\n\n{(message or run.progress or '任务完成').strip()[:2000]}"
        elif status == "failed":
            notify = f"✗ 任务失败\n\n{(error or '未知错误')[:2000]}"
        else:
            notify = "任务已取消。"
        await self._publish(
            event_type,
            task,
            run,
            payload={"result": message or None, "error": error, "bubble": bubble, "speak_text": speak_text},
        )
        await self._notify_conversation(task, notify)
        self._record_memory(event_type, task, run)
        await self._advance_project_nodes(task, status, error)

    def start_stale_sweeper(self, interval_s: float = 300.0, threshold_s: float = 900.0) -> None:
        """ponytail: 全局单轮询循环、每个 run 只提醒一次；提醒时效要求高再换每任务定时器。"""

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval_s)
                await self._sweep_stale_runs(threshold_s)

        asyncio.create_task(_loop())

    async def _sweep_stale_runs(self, threshold_s: float) -> None:
        now = datetime.now(timezone.utc)
        for run in self.store.list_recent(100):
            if run.status not in ("queued", "running") or run.run_id in self._stale_reminded:
                continue
            try:
                age_s = (now - datetime.fromisoformat(run.updated_at)).total_seconds()
            except ValueError:
                continue
            if age_s < threshold_s:
                continue
            self._stale_reminded.add(run.run_id)
            minutes = max(1, int(age_s // 60))
            task = self.task_store.get(run.task_id)
            bubble = f"任务 {minutes} 分钟无进展：{(task.input if task else run.task_id)[:30]}"
            await self.hub.publish(
                EventEnvelope(
                    event_type="task.stale",  # type: ignore[arg-type]
                    source="task",
                    conversation_id=task.conversation_id if task else None,
                    task_id=run.task_id,
                    payload={"bubble": bubble, "speak_text": bubble},
                )
            )

    async def _advance_project_nodes(self, task: Task, status: str, error: str | None) -> None:
        """任务收口时推进关联的项目节点：完成→completed，失败→blocked。

        取消不改节点状态，用户可能马上重跑。节点联动失败不影响任务本身。
        阻塞与阶段/项目级完成会发主动事件，挂件气泡与语音消费。
        """
        if self.project_nodes is None or not task.project or status not in ("completed", "failed"):
            return
        try:
            for node in self.project_nodes.list_project(task.project):
                if task.task_id not in node.task_ids:
                    continue
                if status == "completed":
                    node.status = "completed"
                    node.blocker = None
                else:
                    node.status = "blocked"
                    node.blocker = (error or "任务执行失败")[:300]
                self.project_nodes.put(node)
                if status == "failed":
                    event_type = "project.blocked"
                    bubble = f"⚠ 节点阻塞：{node.title}"
                    speak_text = f"项目遇到阻塞。{node.title}"
                elif node.kind in ("phase", "project"):
                    event_type = "project.milestone"
                    bubble = f"★ 里程碑达成：{node.title}"
                    speak_text = f"里程碑达成。{node.title}"
                else:
                    continue
                await self.hub.publish(
                    EventEnvelope(
                        event_type=event_type,  # type: ignore[arg-type]
                        source="task",
                        conversation_id=task.conversation_id,
                        task_id=task.task_id,
                        payload={"bubble": bubble, "speak_text": speak_text, "node_id": node.node_id},
                    )
                )
        except Exception:
            logger.warning("项目节点联动失败：task=%s", task.task_id, exc_info=True)

    async def _publish(
        self,
        event_type: str,
        task: Task,
        run: AgentRun,
        *,
        payload: dict | None = None,
    ) -> None:
        await self.hub.publish(
            EventEnvelope(
                event_type=event_type,  # type: ignore[arg-type]
                source="task",
                conversation_id=task.conversation_id,
                task_id=task.task_id,
                payload={
                    **(payload or {}),
                    "task": task.model_dump(mode="json"),
                    "run": run.model_dump(mode="json"),
                },
            )
        )

    def _record_memory(self, event_type: str, task: Task, run: AgentRun) -> None:
        try:
            summary = (run.result or run.error or run.progress or task.input)[:80]
            trace_id = self.memory.record_event(
                "task",
                event_type,
                {
                    "task_id": task.task_id,
                    "executor": run.executor,
                    "status": run.status,
                    "summary": summary,
                },
                session_id=task.conversation_id,
                turn_id=task.task_id,
            )
            if event_type in ("task.completed", "task.failed"):
                self.memory.upsert_entry(
                    "L3",
                    "recent",
                    "最近结果",
                    (run.result or run.error or task.input)[:500],
                    [trace_id],
                )
            # 记忆气泡：写入完成后短气泡提示
            bubble_text = f"已记住：{summary}"
            try:
                asyncio.ensure_future(
                    self.hub.publish(
                        EventEnvelope(
                            event_type="memory.updated",
                            source="task",
                            conversation_id=task.conversation_id,
                            task_id=task.task_id,
                            payload={"bubble": bubble_text},
                        )
                    )
                )
            except Exception:
                pass
        except Exception:
            pass
