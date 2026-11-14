"""受控的二步 Agent 工作流：实现完成后再交给另一个 Agent 审查。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from qiling_contracts.task import Task

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowStep(BaseModel):
    executor: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=8000)
    mode: str = "read-only"
    mcp_profile: str | None = None
    skill_id: str | None = None


class WorkflowCreate(BaseModel):
    steps: list[WorkflowStep] = Field(min_length=2, max_length=2)
    conversation_id: str | None = None


class WorkflowStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "workflows"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict] = {}
        for path in self._dir.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if item.get("workflow_id"):
                self._items[item["workflow_id"]] = item

    def put(self, item: dict) -> dict:
        item["updated_at"] = _now()
        self._items[item["workflow_id"]] = item
        (self._dir / f"{item['workflow_id']}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return item

    def get(self, workflow_id: str) -> dict | None:
        return self._items.get(workflow_id)

    def recover_interrupted(self, runs) -> None:
        for workflow in self._items.values():
            if workflow.get("status") not in ("queued", "running"):
                continue

            steps = workflow.get("steps")
            index = workflow.get("current_step", -1)
            if not isinstance(steps, list) or not steps:
                index = -1
            elif not isinstance(index, int) or index < 0 or index >= len(steps):
                index = 0

            step = steps[index] if index >= 0 else None
            run_id = step.get("run_id") if isinstance(step, dict) else None
            run = runs.get(run_id) if run_id else None
            if run is not None:
                step["status"] = run.status
                step["result"] = run.result

            all_completed = bool(steps) and all(
                isinstance(item, dict) and item.get("status") == "completed"
                for item in steps
            )
            if all_completed:
                workflow["status"] = "completed"
                workflow.pop("error", None)
            elif run is not None and run.status == "cancelled":
                workflow["status"] = "cancelled"
                workflow["error"] = run.error or "工作流已取消。"
            else:
                workflow["status"] = "failed"
                workflow["error"] = "服务重启时工作流未完成；请检查已完成步骤后重新提交。"
                if isinstance(step, dict) and step.get("status") not in ("completed", "cancelled"):
                    step["status"] = "failed"

            self.put(workflow)


def _store(request: Request) -> WorkflowStore:
    store = getattr(request.app.state, "workflow_store", None)
    if store is None:
        store = WorkflowStore(request.app.state.settings.data_dir)
        store.recover_interrupted(request.app.state.agent_run_manager.store)
        request.app.state.workflow_store = store
    return store


async def _wait_for_run(request: Request, run_id: str) -> dict:
    manager = request.app.state.agent_run_manager
    for _ in range(2400):  # 最长等待 120 秒，避免后台工作流永久挂起
        run = manager.store.get(run_id)
        if run is None:
            raise RuntimeError(f"Agent Run 不存在：{run_id}")
        if run is not None and run.status in ("completed", "failed", "cancelled"):
            return run.model_dump(mode="json")
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Agent Run 超时：{run_id}")


async def _run_workflow(request: Request, workflow_id: str, steps: list[WorkflowStep], conversation_id: str | None) -> None:
    store = _store(request)
    workflow = store.get(workflow_id)
    if workflow is None:
        return
    previous_result = ""
    try:
        workflow["status"] = "running"
        store.put(workflow)
        for index, step in enumerate(steps):
            prompt = step.prompt
            if previous_result:
                prompt = f"上一阶段结果（仅作输入，不代表已验证）：\n{previous_result[:6000]}\n\n{prompt}"
            task = Task(
                input=prompt,
                category="delegate_backend",
                work_kind="project",
                interaction_kind="work",
                conversation_id=conversation_id,
                complexity="complex",
                estimated_duration="long",
                preferred_executor=step.executor,
                skill_id=step.skill_id,
            )
            request.app.state.task_store.put(task)
            run = await request.app.state.agent_run_manager.execute(
                task,
                executor=step.executor,
                mode=step.mode,
                mcp_profile=step.mcp_profile,
            )
            workflow["steps"][index]["task_id"] = task.task_id
            workflow["steps"][index]["run_id"] = run.run_id
            workflow["current_step"] = index
            store.put(workflow)
            completed = await _wait_for_run(request, run.run_id)
            workflow["steps"][index]["status"] = completed["status"]
            workflow["steps"][index]["result"] = completed.get("result")
            store.put(workflow)
            if completed["status"] != "completed":
                workflow["status"] = completed["status"]
                workflow["error"] = completed.get("error") or "工作流步骤未完成"
                store.put(workflow)
                return
            previous_result = completed.get("result") or ""
        workflow["status"] = "completed"
        store.put(workflow)
    except Exception as exc:
        workflow["status"] = "failed"
        workflow["error"] = str(exc)
        store.put(workflow)


@router.post("")
async def create_workflow(payload: WorkflowCreate, request: Request) -> dict:
    for step in payload.steps:
        if step.mode not in ("read-only", "agent", "agent-full-access"):
            raise HTTPException(status_code=422, detail="工作流步骤 mode 不合法")
        try:
            request.app.state.mcp_manager.validate_profile(step.mcp_profile)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    workflow_id = f"workflow_{uuid4().hex[:10]}"
    item = {
        "workflow_id": workflow_id,
        "status": "queued",
        "current_step": -1,
        "steps": [step.model_dump(mode="json") for step in payload.steps],
        "conversation_id": payload.conversation_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _store(request).put(item)
    asyncio.create_task(_run_workflow(request, workflow_id, payload.steps, payload.conversation_id))
    return {"workflow": item}


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, request: Request) -> dict:
    item = _store(request).get(workflow_id)
    if item is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"workflow": item}
