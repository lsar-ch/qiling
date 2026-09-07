"""Step 1 验收：健康检查 / 会话信息 / WS 事件出口。"""

import json

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


def make_client() -> TestClient:
    settings = load_settings()
    return TestClient(create_app(settings))


def test_health_ok() -> None:
    with make_client() as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "deskmate-ai-service"
        assert "features" in body


def test_health_reports_capability_summary_without_secrets() -> None:
    with make_client() as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        caps = body["capabilities"]
        assert caps["text_chat"] is True
        assert caps["memory"] is True
        assert isinstance(caps["voice"], bool)
        assert caps["agents"]["default_executor"] == "codex"
        assert isinstance(caps["agents"]["ready"], list)
        assert isinstance(caps["agents"]["degraded"], list)
        assert all("integration_status" in item for item in caps["agents"]["degraded"])

        blob = json.dumps(body, ensure_ascii=False).lower()
        for secret_name in ("api_key", "dashscope_api_key", "minimax_api_key", "volc_token"):
            assert secret_name not in blob


def test_session_info() -> None:
    settings = load_settings()
    # 显式清空 LLM key：断言 echo 演示模式，避免依赖本地 .env 是否已配真实模型
    settings.llm_api_key = None
    settings.llm_base_url = None
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"].startswith("session_")
        assert body["ws_url"].startswith("ws://")
        assert body["capabilities"]["text_chat"] is True
    assert "model" in body
    assert body["model"]["echo_mode"] is True


def test_events_ws_hello() -> None:
    with make_client() as client:
        with client.websocket_connect("/api/events") as ws:
            hello = ws.receive_json()
            assert hello["event_type"] == "system.health"
            assert hello["payload"]["message"] == "connected"
