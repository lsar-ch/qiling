"""角色资产后台任务：复用 AgentRun 对外暴露，任务 JSON 仍由 persona_asset_import.py 维护。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.runtime import AgentRun

router = APIRouter(prefix="/api/persona-tasks", tags=["persona-tasks"])

_REQUIRED_PARAMS = {
    "voice_clone": ("reference_audio", "transcript", "voice_name"),
    "avatar_import": ("input", "persona_id", "out_dir"),
}


def _tasks_dir(request: Request) -> Path:
    path = request.app.state.settings.data_dir / "persona-tasks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _to_run(task: dict[str, Any]) -> dict[str, Any]:
    status = str(task.get("status") or "pending")
    terminal = status in ("completed", "failed")
    run = AgentRun(
        run_id=str(task["task_id"]),
        task_id=str(task["task_id"]),
        executor="persona_asset",
        status=status,
        mode="read-only",
        progress=str(task.get("kind") or "asset_task"),
        result=task.get("result"),
        error=task.get("error"),
        created_at=str(task.get("created_at") or _now()),
        updated_at=str(task.get("updated_at") or _now()),
        finished_at=str(task.get("updated_at") or _now()) if terminal else None,
    )
    return run.model_dump(mode="json")


class PersonaTaskCreate(BaseModel):
    kind: Literal["voice_clone", "avatar_import"]
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_persona_tasks(request: Request, limit: int = 20) -> dict[str, Any]:
    tasks = []
    for path in sorted(_tasks_dir(request).glob("*.json")):
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(task, dict) and task.get("task_id"):
            tasks.append(task)
    tasks.sort(key=lambda item: (item.get("created_at") or "", item.get("task_id") or ""), reverse=True)
    items = [_to_run(task) for task in tasks[: max(1, min(limit, 100))]]
    return {"items": items}


@router.post("")
def create_persona_task(payload: PersonaTaskCreate, request: Request) -> dict[str, Any]:
    required = _REQUIRED_PARAMS[payload.kind]
    missing = [key for key in required if not payload.params.get(key)]
    if missing:
        raise HTTPException(status_code=422, detail=f"{payload.kind} 缺少参数: {', '.join(missing)}")
    stamp = _now()
    task_id = f"{payload.kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    task = {
        "task_id": task_id,
        "kind": payload.kind,
        "status": "pending",
        "created_at": stamp,
        "updated_at": stamp,
        "params": payload.params,
        "result": None,
        "error": None,
    }
    path = _tasks_dir(request) / f"{task_id}.json"
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"run": _to_run(task)}


@router.get("/{task_id}")
def get_persona_task(task_id: str, request: Request) -> dict[str, Any]:
    path = _tasks_dir(request) / f"{task_id}.json"
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise HTTPException(status_code=404, detail="角色资产任务不存在")
    if not isinstance(task, dict) or not task.get("task_id"):
        raise HTTPException(status_code=500, detail="角色资产任务格式异常")
    return {"run": _to_run(task)}
