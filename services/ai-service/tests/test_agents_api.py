"""Step 7：Agent 探测、Registry 与 API。"""

from __future__ import annotations

import asyncio
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agents.base import AgentAdapter
from app.agents.catalog import AgentCatalogError, load_agent_catalog
from app.agents.codex import CodexAdapter
from app.agents import workbuddy as workbuddy_module
from app.agents.registry import AgentRegistry
from app.config import load_settings
from app.main import create_app
from deskmate_contracts.agent import AgentInfo


PROJECT_ROOT = Path(__file__).resolve().parents[3]
# 默认执行器以仓库 config/agents.yaml 为准，切换默认值时不必改测试。
DEFAULT_EXECUTOR = yaml.safe_load(
    (PROJECT_ROOT / "config" / "agents.yaml").read_text(encoding="utf-8")
)["default_executor"]


def prepare_home(tmp_path, monkeypatch) -> None:
    home = tmp_path / "deskmate-home"
    monkeypatch.setenv("DESKMATE_HOME", str(home))
    (home / "config" / "personas").mkdir(parents=True)
    (home / "data").mkdir(parents=True)
    (home / "config").joinpath("settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (home / "config").joinpath("system_prompt.md").write_text(
        "你是 DeskMate。",
        encoding="utf-8",
    )
    shutil.copyfile(
        PROJECT_ROOT / "config" / "agents.yaml",
        home / "config" / "agents.yaml",
    )
    monkeypatch.setattr(workbuddy_module, "resolve_workbuddy_runtime", lambda _configured: None)


@contextmanager
def make_client(tmp_path, monkeypatch) -> TestClient:
    prepare_home(tmp_path, monkeypatch)
    with TestClient(create_app(load_settings())) as client:
        yield client


class FakeAdapter(AgentAdapter):
    name = "fake"
    adapter_id = "fake-adapter"
    display_name = "Fake Agent"

    async def detect(self) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            integration_status="ready",
            available=True,
            version="9.9",
            command="fake",
            capabilities=["fake"],
        )


class FailingAdapter(FakeAdapter):
    name = "failing"
    adapter_id = "failing-adapter"
    display_name = "Failing Agent"

    async def detect(self) -> AgentInfo:
        raise RuntimeError("probe boom")


class RefreshableAdapter(FakeAdapter):
    name = "refreshable"
    adapter_id = "refreshable"
    display_name = "Refreshable Agent"

    def __init__(self) -> None:
        self.invalidated = False

    def invalidate_probe(self) -> None:
        self.invalidated = True


def _expected_pending_status(commands: list[str]) -> tuple[str, bool]:
    if any(shutil.which(command) for command in commands):
        return "pending", True
    return "not_installed", False


def _catalog_entry(name: str, commands: list[str]) -> dict:
    return {
        "name": name,
        "label": name.replace("-", " ").title(),
        "adapter": "pending",
        "enabled": True,
        "commands": commands,
        "protocol": None,
        "capabilities": ["code"],
        "source_url": None,
        "tags": ["test"],
        "detail": f"{name} test detail",
    }


def test_agents_api_lists_all_default_agents(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        body = resp.json()
        assert body["default_executor"] == DEFAULT_EXECUTOR
        items = {item["name"]: item for item in body["items"]}
        assert len(items) == 7
        assert set(items) == {
            "codex",
            "claude-code",
            "qwen-code",
            "kimi-cli",
            "reasonix",
            "workbuddy",
            "browser",
        }
        claude_status, claude_available = _expected_pending_status(["claude"])
        assert items["claude-code"]["integration_status"] == claude_status
        assert items["claude-code"]["available"] is claude_available
        assert items["claude-code"]["enabled"] is True
        assert items["workbuddy"]["integration_status"] == "not_installed"
        assert items["workbuddy"]["available"] is False

        codex = items["codex"]
        if shutil.which("codex") is not None:
            assert codex["available"] is True
            assert codex["integration_status"] == "ready"
        else:
            assert codex["available"] is False
            assert codex["integration_status"] == "not_installed"


def test_agents_api_config_returns_catalog(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/api/agents/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["default_executor"] == DEFAULT_EXECUTOR
        assert len(body["items"]) == 7
        assert {item["name"] for item in body["items"]} == {
            "codex",
            "claude-code",
            "qwen-code",
            "kimi-cli",
            "reasonix",
            "workbuddy",
            "browser",
        }
        assert all(item["enabled"] is True for item in body["items"])


def test_workbuddy_command_config_is_persisted_and_detected(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        updated = client.put(
            "/api/agents/workbuddy/config",
            json={"command": "/tmp/deskmate-workbuddy-test"},
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["name"] == "workbuddy"
        assert body["adapter"] == "workbuddy"
        assert body["integration_status"] == "not_installed"
        assert body["available"] is False

        config = client.get("/api/agents/config").json()
        workbuddy = next(item for item in config["items"] if item["name"] == "workbuddy")
        assert workbuddy["config"]["workbuddy_command"] == "/tmp/deskmate-workbuddy-test"


def test_load_agent_catalog_merges_local_agents(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    base = {
        "version": 1,
        "default_executor": "codex",
        "executors": [
            _catalog_entry("alpha", ["alpha"]),
            _catalog_entry("beta", ["beta"]),
            _catalog_entry("gamma", ["gamma"]),
        ],
    }
    (config_dir / "agents.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True),
        encoding="utf-8",
    )
    local_entries = [
        {
            **_catalog_entry("beta", ["local-beta"]),
            "enabled": False,
            "protocol": "local-acp",
            "capabilities": ["local-capability"],
            "source_url": "https://example.com/local",
            "tags": ["local"],
            "detail": "local override detail",
        },
        _catalog_entry("delta", ["delta"]),
    ]
    (config_dir / "agents.local.yaml").write_text(
        yaml.safe_dump({"version": 1, "executors": local_entries}, allow_unicode=True),
        encoding="utf-8",
    )

    catalog = load_agent_catalog(config_dir / "agents.yaml")

    assert [entry.name for entry in catalog.executors] == [
        "alpha",
        "beta",
        "gamma",
        "delta",
    ]
    beta = catalog.executors[1]
    assert beta.enabled is False
    assert beta.commands == ["local-beta"]
    assert beta.protocol == "local-acp"
    assert beta.capabilities == ["local-capability"]
    assert beta.source_url == "https://example.com/local"
    assert beta.tags == ["local"]
    assert beta.detail == "local override detail"
    assert catalog.executors[-1].name == "delta"


def test_load_agent_catalog_missing_file_raises_clear_error(tmp_path) -> None:
    missing = tmp_path / "config" / "agents.yaml"
    with pytest.raises(AgentCatalogError, match="不存在"):
        load_agent_catalog(missing)


def test_agents_api_returns_codex_detail(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/api/agents/codex")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "codex"
        assert body["adapter"] == "codex"
        assert "detail" in body


def test_agents_api_unknown_agent_returns_404(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/api/agents/not-a-real-agent")
        assert resp.status_code == 404


def test_agents_api_refresh_invalidates_probe_cache(tmp_path, monkeypatch) -> None:
    registry = AgentRegistry()
    adapter = RefreshableAdapter()
    registry.register(adapter)
    with make_client(tmp_path, monkeypatch) as client:
        client.app.state.agent_registry = registry
        resp = client.post("/api/agents/refreshable/refresh")
        assert resp.status_code == 200
        assert resp.json()["name"] == "refreshable"
        assert adapter.invalidated is True


def test_agents_api_returns_fake_adapter_result(tmp_path, monkeypatch) -> None:
    registry = AgentRegistry()
    registry.register(FakeAdapter())
    with make_client(tmp_path, monkeypatch) as client:
        client.app.state.agent_registry = registry
        resp = client.get("/api/agents/fake")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "fake"
        assert body["integration_status"] == "ready"
        assert body["available"] is True
        assert body["version"] == "9.9"


def test_agents_api_survives_adapter_detection_error(tmp_path, monkeypatch) -> None:
    registry = AgentRegistry()
    registry.register(FailingAdapter())
    with make_client(tmp_path, monkeypatch) as client:
        client.app.state.agent_registry = registry
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"][0]["integration_status"] == "error"
        assert body["items"][0]["available"] is False
        assert "probe boom" in body["items"][0]["detail"]


def test_codex_adapter_detect_matches_local_codex_presence() -> None:
    info = asyncio.run(CodexAdapter(timeout_s=1.0).detect())
    if shutil.which("codex") is None:
        assert info.integration_status == "not_installed"
        assert info.available is False
    else:
        assert info.integration_status == "ready"
        assert info.available is True


def test_workbuddy_detect_without_runtime_returns_not_installed(monkeypatch) -> None:
    monkeypatch.setattr(workbuddy_module, "resolve_workbuddy_runtime", lambda _configured: None)
    info = asyncio.run(workbuddy_module.WorkBuddyAdapter(timeout_s=0.5).detect())
    assert info.integration_status == "not_installed"
    assert info.available is False


def test_workbuddy_spawn_passes_cli_acp_args(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_spawn(command, *, args=None, cwd, env, on_update=None, on_permission=None, logs_dir=None, stderr_log_name="workbuddy-acp-stderr.log"):
        captured["command"] = command
        captured["args"] = args
        captured["cwd"] = cwd
        captured["env"] = env
        captured["stderr_log_name"] = stderr_log_name
        return None

    monkeypatch.setattr(workbuddy_module.AcpClient, "spawn", fake_spawn)
    runtime = workbuddy_module.WorkBuddyRuntime(
        cli=Path("/tmp/deskmate-workbuddy-cli"),
        runner=Path("/tmp/deskmate-workbuddy-runner"),
        electron=True,
    )
    adapter = workbuddy_module.WorkBuddyAdapter()
    asyncio.run(adapter._spawn(runtime, logs_dir=None))
    assert captured["command"] == str(runtime.runner)
    assert captured["args"] == [str(runtime.cli), "--acp"]
    assert captured["env"]["ELECTRON_RUN_AS_NODE"] == "1"
    assert captured["stderr_log_name"] == "workbuddy-acp-stderr.log"


def test_workbuddy_configured_command_name_uses_path(monkeypatch) -> None:
    runtime = workbuddy_module.WorkBuddyRuntime(
        cli=Path("/fake/bin/cli/codebuddy"),
        runner=Path("/fake/bin/WorkBuddy"),
        electron=True,
    )
    resolved_paths: list[str] = []

    def fake_runtime_from_path(value: str) -> workbuddy_module.WorkBuddyRuntime | None:
        if value == "workbuddy":
            return None
        if value == "/fake/bin/workbuddy":
            resolved_paths.append(value)
            return runtime
        return None

    monkeypatch.setattr(workbuddy_module, "_runtime_from_path", fake_runtime_from_path)
    monkeypatch.setattr(workbuddy_module.shutil, "which", lambda _: "/fake/bin/workbuddy")
    result = workbuddy_module.resolve_workbuddy_runtime("workbuddy")
    assert result is runtime
    assert resolved_paths == ["/fake/bin/workbuddy"]


def test_agents_api_set_default_writes_local_overlay(tmp_path, monkeypatch) -> None:
    """页面「设为默认」写入 agents.local.yaml，压过 agents.yaml 的默认值。"""
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.put("/api/agents/codex/config", json={"set_default": True})
        assert resp.status_code == 200
        assert client.get("/api/agents").json()["default_executor"] == "codex"
        local = tmp_path / "deskmate-home" / "config" / "agents.local.yaml"
        assert "default_executor: codex" in local.read_text(encoding="utf-8")

        assert client.put("/api/agents/workbuddy/config", json={"set_default": True}).status_code == 200
        assert client.get("/api/agents/config").json()["default_executor"] == "workbuddy"


def test_agents_api_rejects_unfit_default_executor(tmp_path, monkeypatch) -> None:
    """未接入真实执行的条目与窄场景浏览器执行器都不能当兜底默认。"""
    with make_client(tmp_path, monkeypatch) as client:
        for name in ("claude-code", "browser"):
            resp = client.put(f"/api/agents/{name}/config", json={"set_default": True})
            assert resp.status_code == 400
            assert "不能设为默认执行器" in resp.json()["detail"]
        assert client.get("/api/agents/config").json()["default_executor"] == DEFAULT_EXECUTOR


def test_agents_api_enable_and_disable_executor(tmp_path, monkeypatch) -> None:
    """停用保留展示但不参与执行；默认执行器必须先切换才能停用。"""
    with make_client(tmp_path, monkeypatch) as client:
        assert client.put("/api/agents/workbuddy/config", json={"set_default": True}).status_code == 200
        resp = client.put("/api/agents/workbuddy/config", json={"enabled": False})
        assert resp.status_code == 400
        assert "当前默认执行器" in resp.json()["detail"]

        assert client.put("/api/agents/codex/config", json={"enabled": False}).status_code == 200
        body = client.get("/api/agents").json()
        items = {item["name"]: item for item in body["items"]}
        assert len(items) == 7
        assert items["codex"]["enabled"] is False
        assert "codex" not in client.get("/api/health").json()["capabilities"]["agents"]["ready"]

        resp = client.put("/api/agents/codex/config", json={"set_default": True})
        assert resp.status_code == 400
        assert "已停用" in resp.json()["detail"]

        assert client.put("/api/agents/codex/config", json={"enabled": True}).status_code == 200
        items = {item["name"]: item for item in client.get("/api/agents").json()["items"]}
        assert items["codex"]["enabled"] is True
        assert client.put("/api/agents/codex/config", json={"set_default": True}).status_code == 200
        assert client.get("/api/agents/config").json()["default_executor"] == "codex"


def test_agents_api_command_update_keeps_other_overrides(tmp_path, monkeypatch) -> None:
    """只改启停不应顺手清掉已保存的命令路径。"""
    with make_client(tmp_path, monkeypatch) as client:
        client.put("/api/agents/codex/config", json={"command": "/tmp/deskmate-codex-test"})
        assert client.put("/api/agents/workbuddy/config", json={"set_default": True}).status_code == 200
        assert client.put("/api/agents/codex/config", json={"enabled": False}).status_code == 200
        config = client.get("/api/agents/config").json()
        codex = next(item for item in config["items"] if item["name"] == "codex")
        assert codex["config"]["codex_command"] == "/tmp/deskmate-codex-test"
        assert codex["enabled"] is False
