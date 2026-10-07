"""主动提醒 CRUD 接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from qiling_contracts.reminder import Reminder, ReminderKind, ReminderRepeat, ReminderStatus

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


class ReminderCreate(BaseModel):
    kind: ReminderKind = "memo"
    text: str = Field(min_length=1, max_length=500)
    remind_at: str = Field(min_length=1)
    repeat: ReminderRepeat = "none"
    task_id: str | None = None

    model_config = {"extra": "forbid"}


class ReminderUpdate(BaseModel):
    status: ReminderStatus | None = None
    text: str | None = Field(default=None, min_length=1, max_length=500)
    remind_at: str | None = Field(default=None, min_length=1)
    repeat: ReminderRepeat | None = None

    model_config = {"extra": "forbid"}


@router.get("")
def list_reminders(request: Request, limit: int = 50) -> dict:
    store = request.app.state.reminder_store
    return {
        "items": [
            reminder.model_dump(mode="json")
            for reminder in store.list_recent(max(1, min(limit, 100)))
        ]
    }


@router.post("")
def create_reminder(payload: ReminderCreate, request: Request) -> dict:
    reminder = Reminder(
        kind=payload.kind,
        text=payload.text,
        remind_at=payload.remind_at,
        repeat=payload.repeat,
        task_id=payload.task_id,
    )
    request.app.state.reminder_store.put(reminder)
    return {"reminder": reminder.model_dump(mode="json")}


@router.patch("/{reminder_id}")
def update_reminder(reminder_id: str, payload: ReminderUpdate, request: Request) -> dict:
    store = request.app.state.reminder_store
    reminder = store.get(reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    reminder = reminder.model_copy(update=changes)
    store.put(reminder)
    return {"reminder": reminder.model_dump(mode="json")}


@router.delete("/{reminder_id}")
def delete_reminder(reminder_id: str, request: Request) -> dict:
    if not request.app.state.reminder_store.delete(reminder_id):
        raise HTTPException(status_code=404, detail="提醒不存在")
    return {"deleted": reminder_id}
