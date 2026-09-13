"""Agent Run 持久化与后台调度。"""

from __future__ import annotations

import asyncio
import json
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    ) -> None:
        self.registry = registry
        self.store = store
        self.task_store = task_store
        self.hub = hub
        self.memory = memory
        self.data_dir = data_dir
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._approval_timers: dict[str, asyncio.Task[None]] = {}  # task_id -> reminder timer

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

    async def execute(
        self,
        task: Task,
        *,
        executor: str | None = None,
        mode: str = "read-only",
    ) -> AgentRun:
        if task.category not in ("delegate_backend", "request_approval"):
            raise ValueError("只有后台任务可以交给外部执行器")
        if task.status in ("running", "completed", "cancelled"):
            raise ValueError(f"任务当前状态不能执行：{task.status}")
        executor_name = executor or task.preferred_executor or self.registry.default_executor
        adapter = self.registry.get(executor_name)
        if adapter is None:
            raise ValueError(f"执行器不存在：{executor_name}")
        if not adapter.executable:
            raise AgentExecutionUnsupported(f"{executor_name} 尚未接入真实执行")
        availability = await adapter.detect()
        if not availability.available or availability.integration_status != "ready":
            raise AgentExecutionUnsupported(
                f"{executor_name} 当前不可执行（{availability.integration_status}）："
                f"{availability.detail}"
            )

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
        background = asyncio.create_task(self._run_task(run, task, adapter, previous_session_id))
        self._tasks[task.task_id] = background
        return run

    async def _run_task(
        self,
        run: AgentRun,
        task: Task,
        adapter: AgentAdapter,
        previous_session_id: str | None = None,
    ) -> None:
        try:
            result = await adapter.run(
                AgentTaskRequest(
                    task_id=task.task_id,
                    prompt=task.input,
                    cwd=str(self.data_dir.parent),
                    conversation_id=task.conversation_id,
                    session_id=previous_session_id,
                    mode=run.mode,
                    config={"logs_dir": str(self.data_dir / "run_logs")},
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
            run.status = "awaiting_approval"
            run.progress = str(
                (payload.get("tool_call") or {}).get("title")
                or (payload.get("tool_call") or {}).get("name")
                or "等待授权"
            )[:300]
            self.store.put(run)
            task = self.task_store.get(run.task_id)
            if task is None:
                return
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
            self._start_approval_timer(run, task)


    _APPROVAL_REMINDER_SECONDS = 30

    def _start_approval_timer(self, run: AgentRun, task: Task) -> None:
        """等待授权超过 N 秒未响应时，广播提醒事件。"""
        old = self._approval_timers.pop(run.task_id, None)
        if old is not None and not old.done():
            old.cancel()

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

    def _cancel_approval_timer(self, task_id: str) -> None:
        timer = self._approval_timers.pop(task_id, None)
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
        elif status == "failed":
            summary = (error or "未知错误")[:60]
            bubble = f"✗ {summary}"
        else:
            bubble = "已取消"
        await self._publish(
            event_type,
            task,
            run,
            payload={"result": message or None, "error": error, "bubble": bubble},
        )
        self._record_memory(event_type, task, run)

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
            trace_id = self.memory.record_event(
                "task",
                event_type,
                {
                    "task_id": task.task_id,
                    "executor": run.executor,
                    "status": run.status,
                    "summary": run.result or run.error or run.progress,
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
        except Exception:
            pass
