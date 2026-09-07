"""WebSocket 事件出口：/api/events 广播 EventEnvelope。"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from deskmate_contracts.events import EventEnvelope

router = APIRouter(prefix="/api", tags=["events"])


@router.websocket("/events")
async def events_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    hub = websocket.app.state.event_hub
    sub_id, queue = await hub.subscribe()
    try:
        current = websocket.app.state.widget_state.current()
        await websocket.send_json(
            EventEnvelope(
                event_type="system.health",
                source="system",
                payload={
                    "message": "connected",
                    "session_id": websocket.app.state.session_id,
                    "widget_state": current.model_dump(mode="json") if current else None,
                },
            ).to_ws_dict()
        )
        while True:
            item = await queue.get()
            await websocket.send_json(item)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(sub_id)
