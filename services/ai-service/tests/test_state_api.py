"""Step 2：事件发布 → 挂件状态派生 → WS 广播/回放。"""

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app(load_settings()))


def _publish(client: TestClient, event_type: str, task_id: str | None = None) -> dict:
    resp = client.post(
        "/api/events/publish",
        json={
            "event_type": event_type,
            "source": "speech" if "speech" in event_type else "task",
            "task_id": task_id,
            "payload": {"message": "demo"},
        },
    )
    assert resp.status_code == 200
    return resp.json()


def test_state_derived_from_events() -> None:
    with make_client() as client:
        # 初始为空
        body = client.get("/api/widget/state").json()
        assert body["widget_state"] is None

        _publish(client, "speech.started")
        body = client.get("/api/widget/state").json()
        assert body["widget_state"]["state"] == "listening"

        _publish(client, "conversation.input")
        body = client.get("/api/widget/state").json()
        assert body["widget_state"]["state"] == "thinking"

        _publish(client, "task.approval_required", task_id="task_01")
        body = client.get("/api/widget/state").json()
        assert body["widget_state"]["state"] == "awaiting_approval"
        assert body["widget_state"]["task_id"] == "task_01"


def test_interrupted_transitions_to_listening() -> None:
    with make_client() as client:
        _publish(client, "conversation.response")
        _publish(client, "speech.interrupted")
        body = client.get("/api/widget/state").json()
        assert body["widget_state"]["state"] == "listening"


def test_publish_response_and_ws_replay() -> None:
    with make_client() as client:
        result = _publish(client, "task.started", task_id="task_99")
        assert result["event"]["event_type"] == "task.started"
        assert result["widget_state"]["state"] == "executing"

        with client.websocket_connect("/api/events") as ws:
            hello = ws.receive_json()
            assert hello["event_type"] == "system.health"
            # 历史回放应包含刚发布的事件（可能先有 persona.presentation）
            replayed = ws.receive_json()
            if replayed["event_type"] == "persona.presentation":
                replayed = ws.receive_json()
            assert replayed["event_type"] == "task.started"
            assert replayed["task_id"] == "task_99"


def test_expression_attached_automatically() -> None:
    """Step 9.5 P1/P2：publish 时 expression 自动附加（情绪由事件类型推导）。"""
    with make_client() as client:
        result = _publish(client, "task.completed", task_id="task_42")
        expr = result["event"].get("expression")
        assert expr is not None
        assert expr["state"] == "completed"
        assert expr["emotion"] == "success"
        assert expr["task_id"] == "task_42"

        # 不在状态映射表的事件（如 memory.created）不附加 expression
        result = _publish(client, "memory.created")
        assert result["event"].get("expression") is None


def test_expression_broadcast_over_ws() -> None:
    """回归：expression 必须出现在 WS 广播载荷里。

    此前 EventHub 先 to_ws_dict() 再跑 on_publish，HTTP 响应带 expression、
    但广播出去的载荷是 null，挂件因此永远停在 neutral 情绪。
    """
    with make_client() as client:
        with client.websocket_connect("/api/events") as ws:
            assert ws.receive_json()["event_type"] == "system.health"
            _publish(client, "conversation.completed")
            msg = ws.receive_json()
            while msg["event_type"] != "conversation.completed":
                msg = ws.receive_json()
            assert msg["expression"]["emotion"] == "success"
            assert msg["expression"]["state"] == "completed"
