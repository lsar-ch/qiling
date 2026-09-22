"""对话工具执行主循环集成测试（P4/P5）：假 provider 返回 tool_calls → 走 MCP。"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import load_settings
from app.llm.base import ChatResult, ToolCallRequest
from app.main import create_app


FAKE_SERVER = """\
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1"},
        }}), flush=True)
    elif method == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": "echo", "description": "回声工具", "inputSchema": {
                "type": "object", "properties": {"text": {"type": "string"}}}},
        ]}}), flush=True)
    elif method == "tools/call":
        args = msg["params"].get("arguments", {})
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": "echo:" + str(args.get("text", ""))}]}}), flush=True)
    elif method == "notifications/initialized":
        pass
"""


class FakeToolProvider:
    display_name = "fake-tool-provider"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, *, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ChatResult(
                text="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1", name="mcp__fake__echo", arguments={"text": "hi"}
                    )
                ],
            )
        return ChatResult(text="工具结果已处理")

    async def stream_chat(self, messages, **kwargs):
        yield "stream"


def _make_app(tmp_path, monkeypatch, access: str):
    home = tmp_path / "deskmate-home"
    monkeypatch.setenv("DESKMATE_HOME", str(home))
    (home / "config").mkdir(parents=True)
    (home / "config" / "system_prompt.md").write_text("你是 DeskMate。", encoding="utf-8")
    shutil.copyfile(
        Path(__file__).resolve().parents[3] / "config" / "agents.yaml",
        home / "config" / "agents.yaml",
    )
    script = home / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    (home / "config" / "mcp-servers.yaml").write_text(
        "version: 1\n"
        "servers:\n"
        "  - id: fake\n"
        "    source: user\n"
        "    enabled: true\n"
        "    transport: stdio\n"
        f"    access: {access}\n"
        f"    command: {sys.executable}\n"
        f"    args: [{json.dumps(str(script))}]\n",
        encoding="utf-8",
    )
    app = create_app(load_settings())
    app.state.llm_provider = FakeToolProvider()
    return app


def test_chat_tool_loop_calls_mcp(tmp_path, monkeypatch) -> None:
    app = _make_app(tmp_path, monkeypatch, "read")
    with TestClient(app) as client:
        resp = client.post("/api/chat/stream", json={"message": "你好", "mode": "auto"})
    assert resp.status_code == 200
    body = resp.text
    assert '"type": "tool_call"' in body
    assert '"server": "fake"' in body
    assert '"tool": "echo"' in body
    assert "工具结果已处理" in body
    assert '"type": "done"' in body


def test_write_tool_requires_approval(tmp_path, monkeypatch) -> None:
    async def run() -> None:
        app = _make_app(tmp_path, monkeypatch, "write")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            task = asyncio.create_task(
                client.post("/api/chat/stream", json={"message": "你好", "mode": "auto"})
            )
            approval_id = ""
            for _ in range(200):
                await asyncio.sleep(0.05)
                pending = getattr(app.state, "tool_approvals", {})
                if pending:
                    approval_id = next(iter(pending))
                    break
            assert approval_id, "写类工具未进入审批挂起"
            app.state.tool_approvals[approval_id].set_result("approved")
            resp = await asyncio.wait_for(task, timeout=10)
            assert resp.status_code == 200
            assert "工具结果已处理" in resp.text
            assert '"type": "done"' in resp.text

    asyncio.run(run())


def test_tool_approval_endpoint(tmp_path, monkeypatch) -> None:
    app = _make_app(tmp_path, monkeypatch, "read")
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    app.state.tool_approvals["approve_test"] = future
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/mcp-tool-approvals/approve_test",
                json={"decision": "approved"},
            )
        assert resp.status_code == 200
        assert future.done() and future.result() == "approved"
    finally:
        loop.close()


def test_tool_approval_endpoint_missing(tmp_path, monkeypatch) -> None:
    app = _make_app(tmp_path, monkeypatch, "read")
    with TestClient(app) as client:
        resp = client.post(
            "/api/mcp-tool-approvals/approve_nope",
            json={"decision": "approved"},
        )
    assert resp.status_code == 404
