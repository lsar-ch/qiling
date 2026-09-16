"""Step 1 验收：健康检查 / 会话信息 / WS 事件出口。"""

import json

from fastapi.testclient import TestClient

from app.agents.catalog import load_agent_catalog
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
        assert caps["agents"]["default_executor"] == load_agent_catalog().default_executor
        assert isinstance(caps["agents"]["ready"], list)
        assert isinstance(caps["agents"]["degraded"], list)
        assert all("integration_status" in item for item in caps["agents"]["degraded"])

        blob = json.dumps(body, ensure_ascii=False).lower()
        for secret_name in ("api_key", "dashscope_api_key", "minimax_api_key", "volc_token"):
            assert secret_name not in blob


def test_health_diagnostics_readable_and_secret_free() -> None:
    """诊断项：中文可读状态 + 修复建议；echo 模式下 LLM 标 error；真实密钥值不泄漏。"""
    settings = load_settings()
    settings.llm_provider = "echo"
    settings.llm_api_key = None
    settings.llm_base_url = None
    # 注入一个假密钥值，断言它不会出现在诊断输出里（提示文案含 "api_key" 字样是允许的）。
    fake_secret = "sk-FAKE-VALUE-9f3a2b1c"
    settings.dashscope_api_key = fake_secret
    settings.minimax_api_key = fake_secret
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        diag = resp.json()["diagnostics"]
        assert isinstance(diag, list) and diag
        names = {item["name"] for item in diag}
        assert {"llm", "voice", "memory", "agents"} <= names
        for item in diag:
            assert item["status"] in ("ok", "degraded", "error")
            assert isinstance(item["label"], str) and item["label"]
            assert isinstance(item["detail"], str) and item["detail"]
        llm = next(item for item in diag if item["name"] == "llm")
        assert llm["status"] == "error"
        assert llm["fix_hint"] and llm["fix_action"] == "open_settings"

        blob = json.dumps(diag, ensure_ascii=False)
        assert fake_secret not in blob


def test_session_info() -> None:
    settings = load_settings()
    # 显式切换 echo：默认模型档案优先级高于 .env，不能只清空 key 来断言演示模式。
    settings.llm_provider = "echo"
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
