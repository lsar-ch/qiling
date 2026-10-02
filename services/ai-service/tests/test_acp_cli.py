"""通用 ACP 执行器（acp-cli）：命令解析、凭据注入与目录接线。

这些测试不拉起子进程、不联网：只验证配置→命令行/环境变量的映射，
以及被动探测在命令存在时不触发进程启动。
"""

from __future__ import annotations

import asyncio

from app.agents.acp_cli import AcpCliAdapter
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
