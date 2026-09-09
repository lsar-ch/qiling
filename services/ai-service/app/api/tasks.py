"""任务分流与任务台接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deskmate_contracts.events import EventEnvelope
from app.routing import classify_task_input

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class RouteRequest(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class ExecuteRequest(BaseModel):
    executor: str | None = None
    mode: str = "read-only"

    model_config = {"extra": "forbid"}


def task_store(request: Request):
    return request.app.state.task_store


def run_manager(request: Request):
    return request.app.state.agent_run_manager


@router.get("/{task_id}/run")
def get_task_run(task_id: str, request: Request) -> dict:
    run = run_manager(request).store.latest_for_task(task_id)
    return {"run": run.model_dump(mode="json") if run else None}


@router.post("/{task_id}/execute")
async def execute_task(task_id: str, request: Request, body: ExecuteRequest) -> dict:
    task = task_store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if body.mode not in ("read-only", "agent", "agent-full-access"):
        raise HTTPException(status_code=422, detail="mode 不合法")
    try:
        run = await run_manager(request).execute(
            task,
            executor=body.executor,
            mode=body.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"task": task.model_dump(mode="json"), "run": run.model_dump(mode="json")}


@router.get("")
def list_tasks(request: Request, limit: int = 50) -> dict:
    items = [task.model_dump(mode="json") for task in task_store(request).list_recent(limit=limit)]
    return {"items": items}


@router.get("/{task_id}")
def get_task(task_id: str, request: Request) -> dict:
    task = task_store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.model_dump(mode="json")


@router.post("")
@router.post("/route")
async def route_task(payload: RouteRequest, request: Request) -> dict:
    task = classify_task_input(payload.input, request.app.state.settings.permission_level)
    task.conversation_id = payload.conversation_id
    task = task_store(request).put(task)
    await request.app.state.event_hub.publish(
        EventEnvelope(
            event_type="task.classified",
            source="task",
            conversation_id=payload.conversation_id,
            task_id=task.task_id,
            payload=task.model_dump(mode="json"),
        )
    )
    approval_event = None
    if task.required_approval:
        approval_event = EventEnvelope(
            event_type="task.approval_required",
            source="task",
            conversation_id=payload.conversation_id,
            task_id=task.task_id,
            payload={"reason": "risk_gate", "task": task.model_dump(mode="json")},
        )
        await request.app.state.event_hub.publish(approval_event)
    return {
        "task": task.model_dump(mode="json"),
        "approval_event": approval_event.model_dump(mode="json") if approval_event else None,
    }


@router.post("/{task_id}/running")
async def mark_running(task_id: str, request: Request) -> dict:
    task = task_store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.status = "running"
    task = task_store(request).put(task)
    return {"task": task.model_dump(mode="json")}


@router.post("/{task_id}/approval")
async def mark_approval(task_id: str, request: Request) -> dict:
    task = task_store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.status = "awaiting_approval"
    task = task_store(request).put(task)
    return {"task": task.model_dump(mode="json")}


@router.post("/{task_id}/completed")
async def mark_completed(task_id: str, request: Request) -> dict:
    task = task_store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.status = "completed"
    task = task_store(request).put(task)
    return {"task": task.model_dump(mode="json")}


@router.post("/{task_id}/failed")
async def mark_failed(task_id: str, request: Request) -> dict:
    task = task_store(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.status = "failed"
    task = task_store(request).put(task)
    return {"task": task.model_dump(mode="json")}
