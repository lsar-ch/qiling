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
from app.agents.registry import AgentRegistry
from app.config import load_settings
from app.main import create_app
from deskmate_contracts.agent import AgentInfo


PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
        assert body["default_executor"] == "codex"
        items = {item["name"]: item for item in body["items"]}
        assert len(items) == 6
        assert set(items) == {
            "codex",
            "claude-code",
            "qwen-code",
            "kimi-cli",
            "reasonix",
            "workbuddy",
        }
        claude_status, claude_available = _expected_pending_status(["claude"])
        assert items["claude-code"]["integration_status"] == claude_status
        assert items["claude-code"]["available"] is claude_available
        assert items["claude-code"]["enabled"] is True
        workbuddy_status, workbuddy_available = _expected_pending_status(["workbuddy", "wb"])
        assert items["workbuddy"]["integration_status"] == workbuddy_status
        assert items["workbuddy"]["available"] is workbuddy_available

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
        assert body["default_executor"] == "codex"
        assert len(body["items"]) == 6
        assert {item["name"] for item in body["items"]} == {
            "codex",
            "claude-code",
            "qwen-code",
            "kimi-cli",
            "reasonix",
            "workbuddy",
        }
        assert all(item["enabled"] is True for item in body["items"])


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
