"""挂件状态与事件发布接口（Step 2 演练/集成入口）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from deskmate_contracts.events import (
    EventEnvelope,
    EventSource,
    EventType,
    new_event_id,
)
from deskmate_contracts.widget import WidgetState

router = APIRouter(prefix="/api", tags=["widget"])


class EventPublishRequest(BaseModel):
    """发布一个系统事件；event_id / timestamp 由服务端补齐。"""

    event_type: EventType
    source: EventSource
    payload: dict = Field(default_factory=dict)
    conversation_id: str | None = None
    task_id: str | None = None

    model_config = {"extra": "forbid"}


@router.post("/events/publish")
async def publish_event(request: Request, body: EventPublishRequest) -> dict:
    envelope = EventEnvelope(
        event_id=new_event_id(),
        event_type=body.event_type,
        source=body.source,
        payload=body.payload,
        conversation_id=body.conversation_id,
        task_id=body.task_id,
    )
    await request.app.state.event_hub.publish(envelope)
    if body.event_type == "widget.activity":
        try:
            idle_seconds = float(body.payload.get("idle_seconds") or 0)
        except (TypeError, ValueError):
            idle_seconds = 0.0
        request.app.state.wellness.ingest_activity(idle_seconds)
    current = request.app.state.widget_state.current()
    return {
        "event": envelope.to_ws_dict(),
        "widget_state": current.model_dump(mode="json") if current else None,
    }


@router.get("/widget/state")
async def widget_state(request: Request) -> dict:
    current = request.app.state.widget_state.current()
    return {"widget_state": current.model_dump(mode="json") if current else None}


@router.get("/widget/states")
async def widget_states() -> dict:
    """可用状态清单（调试/演练用）。"""
    states: list[WidgetState] = [
        "idle",
        "listening",
        "thinking",
        "speaking",
        "executing",
        "awaiting_approval",
        "completed",
        "interrupted",
    ]
    return {"states": states}
