"""通用 ACP 执行器（acp-cli）：命令解析、凭据注入与目录接线。

这些测试不拉起子进程、不联网：只验证配置→命令行/环境变量的映射，
以及被动探测在命令存在时不触发进程启动。
"""

from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path

from app.agents.acp_cli import AcpCliAdapter
from app.agents.base import AgentTaskRequest
from app.agents.catalog import AgentCatalog, AgentCatalogEntry
from app.agents.factory import build_agent_registry


def _entry(name: str = "demo", **config) -> AgentCatalogEntry:
    return AgentCatalogEntry(
        name=name,
        label=name,
        adapter="acp-cli",
        enabled=True,
        commands=["demo"],
        protocol="acp",
        capabilities=["code"],
        source_url=None,
        tags=["acp"],
        detail="",
        config=config,
    )


class TestCommandLine:
    def test_page_override_wins(self):
        entry = _entry(demo_command="my-cli --acp --verbose", acp_command="npx -y demo")
        adapter = AcpCliAdapter(catalog_entry=entry)
        assert adapter._command_line() == ["my-cli", "--acp", "--verbose"]

    def test_uses_acp_command_from_catalog(self):
        adapter = AcpCliAdapter(catalog_entry=_entry(acp_command="kimi acp"))
        assert adapter._command_line() == ["kimi", "acp"]

    def test_falls_back_to_commands_plus_default_args(self):
        adapter = AcpCliAdapter(catalog_entry=_entry())
        assert adapter._command_line() == ["demo", "--acp"]

    def test_missing_command_reports_not_installed(self):
        adapter = AcpCliAdapter(catalog_entry=_entry(acp_command="definitely-not-here-xyz --acp"))
        info = asyncio.run(adapter.detect())
        assert info.integration_status == "not_installed"
        assert info.available is False


class TestChildEnv:
    def test_injects_key_into_declared_env_var(self):
        entry = _entry(demo_api_key="sk-test", api_key_env="DEMO_API_KEY")
        env = AcpCliAdapter(catalog_entry=entry)._child_env()
        assert env["DEMO_API_KEY"] == "sk-test"

    def test_extra_env_is_applied(self):
        entry = _entry(env={"OPENAI_BASE_URL": "https://example.invalid/v1"})
        env = AcpCliAdapter(catalog_entry=entry)._child_env()
        assert env["OPENAI_BASE_URL"] == "https://example.invalid/v1"

    def test_no_key_no_injection(self):
        entry = _entry(api_key_env="DEMO_API_KEY")
        assert "DEMO_API_KEY" not in AcpCliAdapter(catalog_entry=entry)._child_env()


class TestPassiveProbe:
    def test_existing_command_is_ready_without_spawning(self):
        # 用本机一定存在的解释器当命令，验证「命令在 → ready」且不进 _probe。
        adapter = AcpCliAdapter(catalog_entry=_entry(acp_command="python3"))
        info = asyncio.run(adapter.detect())
        assert info.integration_status == "ready"
        assert info.available is True
        assert adapter._probe_cache is None  # 没跑握手

    def test_refresh_forces_real_probe_next_time(self):
        adapter = AcpCliAdapter(catalog_entry=_entry(acp_command="python3"))
        asyncio.run(adapter.detect())
        adapter.invalidate_probe()
        assert adapter._force_probe is True
        assert adapter._probe_cache is None


def test_factory_registers_acp_cli_adapter():
    catalog = AgentCatalog(
        version="1",
        default_executor="demo",
        executors=[_entry(acp_command="demo --acp")],
    )
    registry = build_agent_registry(catalog)
    adapter = registry.get("demo")
    assert isinstance(adapter, AcpCliAdapter)
    assert adapter.executable is True


def test_second_acp_agent_reuses_adapter_and_forwards_mcp_profile(monkeypatch):
    """Claude-style ACP entries use the shared lifecycle without spawning a CLI."""
    calls = []

    class FakeClient:
        def __init__(self, on_update):
            self.on_update = on_update

        async def request(self, method, params, *, timeout_s=None):
            calls.append((method, params))
            if method == "initialize":
                return {"protocolVersion": 1}
            if method == "session/new":
                return {"sessionId": "session-claude"}
            if method == "session/prompt":
                await self.on_update(
                    {"sessionUpdate": "agent_message_chunk", "content": "已完成"}
                )
                return {"stopReason": "end_turn"}
            raise AssertionError(f"unexpected ACP method: {method}")

        async def close(self):
            return None

    entry = _entry(
        name="claude-code",
        claude_code_command="claude-agent-acp",
        api_key_env="ANTHROPIC_API_KEY",
    )
    adapter = AcpCliAdapter(catalog_entry=entry)

    async def fake_spawn(resolved, *, cwd, logs_dir, on_update=None, on_permission=None):
        assert resolved == ["claude-agent-acp"]
        return FakeClient(on_update)

    monkeypatch.setattr(adapter, "_resolve", lambda: ["claude-agent-acp"])
    monkeypatch.setattr(adapter, "_spawn", fake_spawn)

    updates = []

    async def on_update(kind, payload):
        updates.append((kind, payload))

    result = asyncio.run(
        adapter.run(
            AgentTaskRequest(
                task_id="task-claude",
                prompt="只回复结果",
                cwd="/tmp",
                config={
                    "mcp_servers": [
                        {"name": "web", "command": "mcp-web", "args": []}
                    ]
                },
            ),
            on_update,
        )
    )

    assert result.status == "completed"
    assert result.session_id == "session-claude"
    assert result.message == "已完成"
    new_call = next(params for method, params in calls if method == "session/new")
    assert new_call["mcpServers"] == [
        {"name": "web", "command": "mcp-web", "args": []}
    ]
    assert any(kind == "progress" for kind, _ in updates)


def test_offline_acp_fixture_exercises_real_stdio_lifecycle():
    fixture = Path(__file__).parent / "fixtures" / "fake_acp_server.py"
    adapter = AcpCliAdapter(
        catalog_entry=_entry(
            acp_command=f"{shlex.quote(sys.executable)} {shlex.quote(str(fixture))}"
        )
    )
    updates = []

    async def on_update(kind, payload):
        updates.append((kind, payload))

    from app.agents.base import AgentTaskRequest

    result = asyncio.run(
        adapter.run(
            AgentTaskRequest(
                task_id="offline-acp",
                prompt="只回复结果",
                cwd=str(fixture.parent),
            ),
            on_update,
        )
    )

    assert result.status == "completed"
    assert result.session_id == "offline-session"
    assert result.message == "离线模拟结果"
    assert any(kind == "progress" for kind, _ in updates)
