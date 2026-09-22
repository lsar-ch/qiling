"""MCP stdio 客户端与 manager 的假 server 测试（P4）。"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from app.mcp.manager import McpManager


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


@pytest.fixture
def manager(tmp_path) -> McpManager:
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    config = tmp_path / "mcp-servers.yaml"
    config.write_text(
        "version: 1\n"
        "servers:\n"
        "  - id: fake\n"
        "    source: user\n"
        "    enabled: true\n"
        "    transport: stdio\n"
        "    access: read\n"
        f"    command: {sys.executable}\n"
        f"    args: [{json.dumps(str(script))}]\n",
        encoding="utf-8",
    )
    return McpManager(Path(config))


def test_lazy_start_and_call(manager: McpManager) -> None:
    async def run() -> None:
        assert manager.list_servers()[0].status == "not_started"
        tools = await manager.list_tools("fake")
        assert [item.name for item in tools] == ["echo"]
        assert manager.list_servers()[0].status == "ready"
        result = await manager.call_tool("fake", "echo", {"text": "hi"})
        assert result == "echo:hi"

    asyncio.run(run())


def test_prepare_specs_caches_after_reclaim(manager: McpManager) -> None:
    async def run() -> None:
        specs = await manager.prepare_tool_specs()
        assert specs and specs[0][0] == "fake" and specs[0][1].name == "echo"
        # 空闲回收后进程停止，但工具缓存仍在，prepare 不应再拉起进程
        manager._runtime["fake"].last_used = time.monotonic() - 1000
        await manager.reclaim_idle()
        assert manager.list_servers()[0].status == "not_started"
        specs = await manager.prepare_tool_specs()
        assert len(specs) == 1

    asyncio.run(run())


def test_disabled_not_in_specs(manager: McpManager) -> None:
    async def run() -> None:
        await manager.set_enabled("fake", False)
        assert await manager.prepare_tool_specs() == []
        with pytest.raises(Exception):
            await manager.list_tools("fake")

    asyncio.run(run())
