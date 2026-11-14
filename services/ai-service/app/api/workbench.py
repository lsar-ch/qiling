"""工作台条目、便签与待办接口。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.workbench import WorkbenchDataStore
from qiling_contracts.workbench import WorkbenchItem, WorkbenchNote, WorkbenchSettings, WorkbenchTodo

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


class WorkbenchItemPatch(BaseModel):
    kind: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=100)
    group: str | None = Field(default=None, max_length=80)
    url: str | None = None
    feature_id: str | None = None
    visible: bool | None = None
    order: int | None = Field(default=None, ge=0, le=10000)
    model_config = {"extra": "forbid"}


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(default="", max_length=10000)
    project_path: str | None = Field(default=None, max_length=2000)
    model_config = {"extra": "forbid"}


class NotePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, max_length=10000)
    project_path: str | None = Field(default=None, max_length=2000)
    model_config = {"extra": "forbid"}


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    project_path: str | None = Field(default=None, max_length=2000)
    model_config = {"extra": "forbid"}


class TodoPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    project_path: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern=r"^(pending|completed)$")
    model_config = {"extra": "forbid"}


def _workbench(request: Request) -> WorkbenchSettings:
    return request.app.state.settings.workbench


def _save_workbench(request: Request, items: list[WorkbenchItem]) -> WorkbenchSettings:
    path = request.app.state.settings.local_settings_path
    try:
        overrides = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        overrides = {}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="本地设置文件无法读取；未覆盖原文件") from exc
    if not isinstance(overrides, dict):
        raise HTTPException(status_code=500, detail="本地设置格式无效；未覆盖原文件")
    settings = WorkbenchSettings(items=items)
    overrides["workbench"] = settings.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    request.app.state.settings.workbench = settings
    return settings


def _store(request: Request, name: str) -> WorkbenchDataStore:
    return request.app.state.workbench_stores[name]


@router.get("/items")
def list_items(request: Request) -> dict[str, Any]:
    items = sorted(_workbench(request).items, key=lambda item: item.order)
    return {"items": [item.model_dump(mode="json") for item in items]}


@router.get("/items/{item_id}")
def get_item(item_id: str, request: Request) -> dict[str, Any]:
    item = next((item for item in _workbench(request).items if item.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="工作台条目不存在")
    return {"item": item.model_dump(mode="json")}


@router.post("/items")
def create_item(item: WorkbenchItem, request: Request) -> dict[str, Any]:
    current = _workbench(request).items
    if any(existing.id == item.id for existing in current):
        raise HTTPException(status_code=409, detail="工作台条目 ID 已存在")
    settings = _save_workbench(request, [*current, item])
    return {"item": item.model_dump(mode="json"), "workbench": settings.model_dump(mode="json")}


@router.patch("/items/{item_id}")
def update_item(item_id: str, payload: WorkbenchItemPatch, request: Request) -> dict[str, Any]:
    current = _workbench(request).items
    item = next((candidate for candidate in current if candidate.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="工作台条目不存在")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    try:
        updated = WorkbenchItem.model_validate({**item.model_dump(mode="python"), **changes})
        settings = _save_workbench(
            request, [updated if candidate.id == item_id else candidate for candidate in current]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": updated.model_dump(mode="json"), "workbench": settings.model_dump(mode="json")}


@router.delete("/items/{item_id}")
def delete_item(item_id: str, request: Request) -> dict[str, Any]:
    current = _workbench(request).items
    items = [item for item in current if item.id != item_id]
    if len(items) == len(current):
        raise HTTPException(status_code=404, detail="工作台条目不存在")
    _save_workbench(request, items)
    return {"deleted": item_id}


@router.get("/notes")
def list_notes(request: Request, limit: int = 100) -> dict[str, Any]:
    items = _store(request, "notes").list_recent(max(1, min(limit, 500)))
    return {"items": [item.model_dump(mode="json") for item in items]}


@router.get("/notes/{note_id}")
def get_note(note_id: str, request: Request) -> dict[str, Any]:
    note = _store(request, "notes").get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="便签不存在")
    return {"note": note.model_dump(mode="json")}


@router.post("/notes")
def create_note(payload: NoteCreate, request: Request) -> dict[str, Any]:
    note = WorkbenchNote(**payload.model_dump())
    try:
        _store(request, "notes").put(note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"note": note.model_dump(mode="json")}


@router.patch("/notes/{note_id}")
def update_note(note_id: str, payload: NotePatch, request: Request) -> dict[str, Any]:
    store = _store(request, "notes")
    note = store.get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="便签不存在")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    note = WorkbenchNote.model_validate({**note.model_dump(), **changes})
    store.put(note)
    return {"note": note.model_dump(mode="json")}


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, request: Request) -> dict[str, Any]:
    if not _store(request, "notes").delete(note_id):
        raise HTTPException(status_code=404, detail="便签不存在")
    return {"deleted": note_id}


@router.get("/todos")
def list_todos(request: Request, limit: int = 100) -> dict[str, Any]:
    items = _store(request, "todos").list_recent(max(1, min(limit, 500)))
    return {"items": [item.model_dump(mode="json") for item in items]}


@router.get("/todos/{todo_id}")
def get_todo(todo_id: str, request: Request) -> dict[str, Any]:
    todo = _store(request, "todos").get(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"todo": todo.model_dump(mode="json")}


@router.post("/todos")
def create_todo(payload: TodoCreate, request: Request) -> dict[str, Any]:
    todo = WorkbenchTodo(**payload.model_dump())
    try:
        _store(request, "todos").put(todo)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"todo": todo.model_dump(mode="json")}


@router.patch("/todos/{todo_id}")
def update_todo(todo_id: str, payload: TodoPatch, request: Request) -> dict[str, Any]:
    store = _store(request, "todos")
    todo = store.get(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    todo = WorkbenchTodo.model_validate({**todo.model_dump(), **changes})
    store.put(todo)
    return {"todo": todo.model_dump(mode="json")}


@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: str, request: Request) -> dict[str, Any]:
    if not _store(request, "todos").delete(todo_id):
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"deleted": todo_id}
