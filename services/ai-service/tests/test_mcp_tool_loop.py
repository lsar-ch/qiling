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

    def __init__(self, requested_tool: str = "mcp__fake__echo") -> None:
        self.calls = 0
        self.requested_tool = requested_tool
        self.offered_tools: list[str] = []
        self.tool_results: list[str] = []
        self.first_messages: list[dict] = []

    async def chat(self, messages, *, tools=None):
        self.calls += 1
        self.tool_results = [
            str(message["content"])
            for message in messages
            if message.get("role") == "tool"
        ]
        if self.calls == 1:
            self.first_messages = messages
            self.offered_tools = [tool.name for tool in tools or []]
            return ChatResult(
                text="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1", name=self.requested_tool, arguments={"text": "hi"}
                    )
                ],
            )
        return ChatResult(text="工具结果已处理")

    async def stream_chat(self, messages, **kwargs):
        yield "stream"


def _make_app(
    tmp_path,
    monkeypatch,
    access: str,
    *,
    profile: bool = False,
    provider: FakeToolProvider | None = None,
):
    home = tmp_path / "qiling-home"
    monkeypatch.setenv("QILING_HOME", str(home))
    (home / "config").mkdir(parents=True)
    if profile:
        skill_dir = home / "data" / "skills" / "mcp-demo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: mcp-demo\n"
            "description: MCP 测试技能\n"
            "execution:\n"
            "  modes: [inline, mcp]\n"
            "tools: [mcp__fake-write__echo]\n"
            "enabled: true\n"
            "---\n"
            "MCP 技能指引标记。\n",
            encoding="utf-8",
        )
    (home / "config" / "system_prompt.md").write_text("你是 栖灵。", encoding="utf-8")
    shutil.copyfile(
        Path(__file__).resolve().parents[3] / "config" / "agents.yaml",
        home / "config" / "agents.yaml",
    )
    script = home / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    config = (
        "version: 1\n"
        + ("profiles:\n  research:\n    servers: [fake, fake-write]\n" if profile else "")
        + "servers:\n"
        + "  - id: fake\n"
        + "    source: user\n"
        + "    enabled: true\n"
        + "    transport: stdio\n"
        + f"    access: {access}\n"
        + f"    command: {sys.executable}\n"
        + f"    args: [{json.dumps(str(script))}]\n"
        + (
            "  - id: fake-write\n"
            "    source: user\n"
            "    enabled: true\n"
            "    transport: stdio\n"
            "    access: write\n"
            f"    command: {sys.executable}\n"
            f"    args: [{json.dumps(str(script))}]\n"
            if profile
            else ""
        )
    )
    (home / "config" / "mcp-servers.yaml").write_text(config, encoding="utf-8")
    app = create_app(load_settings())
    app.state.llm_provider = provider or FakeToolProvider()
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


def test_read_only_profile_exposes_only_allowed_read_servers(tmp_path, monkeypatch) -> None:
    provider = FakeToolProvider()
    app = _make_app(tmp_path, monkeypatch, "read", profile=True, provider=provider)
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "搜索资料", "mcp_profile": "research"},
        )
    assert resp.status_code == 200
    assert provider.offered_tools == ["mcp__fake__echo"]
    assert "fake" in app.state.mcp_manager._runtime
    assert "fake-write" not in app.state.mcp_manager._runtime
    tasks = list(app.state.task_store.values())
    assert tasks and tasks[0].status == "completed"
    assert "echo:hi" in provider.tool_results


def test_mcp_profile_injects_compatible_skill_guidance(tmp_path, monkeypatch) -> None:
    provider = FakeToolProvider()
    app = _make_app(tmp_path, monkeypatch, "read", profile=True, provider=provider)
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat/stream",
            json={
                "message": "你好",
                "skill_id": "mcp-demo",
                "mcp_profile": "research",
            },
        )
    assert resp.status_code == 200
    assert provider.first_messages
    assert "MCP 技能指引标记" in provider.first_messages[0]["content"]
    assert provider.offered_tools == ["mcp__fake__echo"]


def test_read_only_profile_rejects_unexposed_write_tool_call(tmp_path, monkeypatch) -> None:
    provider = FakeToolProvider(requested_tool="mcp__fake-write__echo")
    app = _make_app(tmp_path, monkeypatch, "read", profile=True, provider=provider)
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "搜索资料", "mcp_profile": "research"},
        )
    assert resp.status_code == 200
    assert provider.offered_tools == ["mcp__fake__echo"]
    assert "fake-write" not in app.state.mcp_manager._runtime


def test_unknown_mcp_profile_is_rejected(tmp_path, monkeypatch) -> None:
    app = _make_app(tmp_path, monkeypatch, "read")
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "搜索资料", "mcp_profile": "missing"},
        )
    assert resp.status_code == 400


def test_profile_does_not_complete_high_risk_browser_task(tmp_path, monkeypatch) -> None:
    app = _make_app(tmp_path, monkeypatch, "read", profile=True)
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "删除网页内容", "mcp_profile": "research"},
        )
        assert resp.status_code == 200
        tasks = client.get("/api/tasks").json()["items"]
    assert tasks and tasks[0]["category"] == "request_approval"
    assert tasks[0]["status"] == "awaiting_approval"


def test_profile_handles_url_fetch_without_starting_agent(tmp_path, monkeypatch) -> None:
    provider = FakeToolProvider()
    app = _make_app(tmp_path, monkeypatch, "read", profile=True, provider=provider)

    async def _unexpected_execute(*args, **kwargs):
        raise AssertionError("MCP profile 网页读取不应启动 ACP")

    with TestClient(app) as client:
        monkeypatch.setattr(
            app.state.agent_run_manager, "execute", _unexpected_execute
        )
        resp = client.post(
            "/api/chat/stream",
            json={
                "message": "总结一下这篇文章 https://example.com/a",
                "mcp_profile": "research",
            },
        )
    assert resp.status_code == 200
    assert provider.offered_tools == ["mcp__fake__echo"]


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
