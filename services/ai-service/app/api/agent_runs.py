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
    items = _manager(request).store.list_recent(limit=max(1, min(limit, 200)))
    return {"items": [run.model_dump(mode="json") for run in items]}


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
