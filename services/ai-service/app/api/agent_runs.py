"""Agent Run 查询、取消与授权。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/agent-runs", tags=["agent-runs"])


def _manager(request: Request):
    return request.app.state.agent_run_manager


class ApprovalAction(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")


@router.get("")
async def list_runs(request: Request, limit: int = 50) -> dict:
    manager = _manager(request)
    items = manager.store.list_recent(limit=max(1, min(limit, 200)))
    enriched = []
    for run in items:
        item = run.model_dump(mode="json")
        task = request.app.state.task_store.get(run.task_id)
        if task:
            item.update(
                task_input=task.input,
                conversation_id=task.conversation_id,
                project=task.project,
            )
        enriched.append(item)
    return {"items": enriched}


@router.get("/awaiting")
async def awaiting_runs(request: Request, conversation_id: str | None = None) -> dict:
    """列出等待授权的 run：对话页刷新或重开会话后，仍能恢复批准/拒绝入口。"""
    manager = _manager(request)
    task_store = request.app.state.task_store
    items = []
    for run in manager.store.list_recent(limit=200):
        if run.status != "awaiting_approval":
            continue
        task = task_store.get(run.task_id)
        if conversation_id and (task is None or task.conversation_id != conversation_id):
            continue
        items.append(run.model_dump(mode="json"))
    return {"items": items}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict:
    try:
        run = await _manager(request).cancel_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent Run 不存在")
    return {"run": run.model_dump(mode="json")}


@router.post("/{run_id}/approval")
async def approve_run(run_id: str, request: Request, body: ApprovalAction) -> dict:
    try:
        run = await _manager(request).approve_run(run_id, body.decision)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent Run 不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"run": run.model_dump(mode="json")}
