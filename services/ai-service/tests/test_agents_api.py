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
from qiling_contracts.agent import AgentInfo


PROJECT_ROOT = Path(__file__).resolve().parents[3]
# 默认执行器以仓库 config/agents.yaml 为准，切换默认值时不必改测试。
DEFAULT_EXECUTOR = yaml.safe_load(
    (PROJECT_ROOT / "config" / "agents.yaml").read_text(encoding="utf-8")
)["default_executor"]


def prepare_home(tmp_path, monkeypatch) -> None:
    home = tmp_path / "qiling-home"
    monkeypatch.setenv("QILING_HOME", str(home))
    (home / "config" / "personas").mkdir(parents=True)
    (home / "data").mkdir(parents=True)
    (home / "config").joinpath("settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (home / "config").joinpath("system_prompt.md").write_text(
        "你是 栖灵。",
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
        assert len(items) == 8
        assert set(items) == {
            "codex",
            "claude-code",
            "qwen-code",
            "kimi-cli",
            "reasonix",
            "workbuddy",
            "browser",
            "local-office",
        }
        # ACP 主线：claude-code 已接通用 ACP 执行器，启动命令是 npx 分发的
        # claude-agent-acp。被动健康检查只看命令是否存在，不拉起子进程（npx 会联网）。
        assert items["claude-code"]["adapter"] == "acp-cli"
        # 按需安装：可选执行器默认停用，用户在「我的智能体」页按需添加。
        assert items["claude-code"]["enabled"] is False
        if shutil.which("npx") is not None:
            assert items["claude-code"]["available"] is True
            assert items["claude-code"]["integration_status"] == "ready"
        else:
            assert items["claude-code"]["available"] is False
            assert items["claude-code"]["integration_status"] == "not_installed"
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
        enabled = {item["name"] for item in body["items"] if item["enabled"]}
        assert enabled == {"codex", "browser"}


def test_workbuddy_command_config_is_persisted_and_detected(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        updated = client.put(
            "/api/agents/workbuddy/config",
            json={"command": "/tmp/qiling-workbuddy-test"},
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["name"] == "workbuddy"
        assert body["adapter"] == "workbuddy"
        assert body["integration_status"] == "not_installed"
        assert body["available"] is False

        config = client.get("/api/agents/config").json()
        workbuddy = next(item for item in config["items"] if item["name"] == "workbuddy")
        assert workbuddy["config"]["workbuddy_command"] == "/tmp/qiling-workbuddy-test"


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
        cli=Path("/tmp/qiling-workbuddy-cli"),
        runner=Path("/tmp/qiling-workbuddy-runner"),
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
        local = tmp_path / "qiling-home" / "config" / "agents.local.yaml"
        assert "default_executor: codex" in local.read_text(encoding="utf-8")

        # workbuddy 默认停用，先启用再设为默认。
        assert client.put(
            "/api/agents/workbuddy/config", json={"enabled": True, "set_default": True}
        ).status_code == 200
        assert client.get("/api/agents/config").json()["default_executor"] == "workbuddy"


def test_agents_api_rejects_unfit_default_executor(tmp_path, monkeypatch) -> None:
    """未接入真实执行的条目与窄场景浏览器执行器都不能当兜底默认。

    claude-code 自 2026-10-01 起走通用 ACP 执行器（可执行、可当默认），
    所以用仍是 pending 的 reasonix 代替它验证「未接入不可当默认」。
    """
    with make_client(tmp_path, monkeypatch) as client:
        for name in ("reasonix", "browser"):
            resp = client.put(f"/api/agents/{name}/config", json={"set_default": True})
            assert resp.status_code == 400
            assert "不能设为默认执行器" in resp.json()["detail"]
        assert client.get("/api/agents/config").json()["default_executor"] == DEFAULT_EXECUTOR


def test_agents_api_enable_and_disable_executor(tmp_path, monkeypatch) -> None:
    """停用保留展示但不参与执行；默认执行器必须先切换才能停用。"""
    with make_client(tmp_path, monkeypatch) as client:
        assert client.put(
            "/api/agents/workbuddy/config", json={"enabled": True, "set_default": True}
        ).status_code == 200
        resp = client.put("/api/agents/workbuddy/config", json={"enabled": False})
        assert resp.status_code == 400
        assert "当前默认执行器" in resp.json()["detail"]

        assert client.put("/api/agents/codex/config", json={"enabled": False}).status_code == 200
        body = client.get("/api/agents").json()
        items = {item["name"]: item for item in body["items"]}
        assert len(items) == 8
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
        client.put("/api/agents/codex/config", json={"command": "/tmp/qiling-codex-test"})
        assert client.put(
            "/api/agents/workbuddy/config", json={"enabled": True, "set_default": True}
        ).status_code == 200
        assert client.put("/api/agents/codex/config", json={"enabled": False}).status_code == 200
        config = client.get("/api/agents/config").json()
        codex = next(item for item in config["items"] if item["name"] == "codex")
        assert codex["config"]["codex_command"] == "/tmp/qiling-codex-test"
        assert codex["enabled"] is False

# --- WorkBuddy 授权链路（2026-09-16 实测报文：kind 与 optionId 不同名）---

# session/request_permission 真实下发的 options（探针 /tmp/wb-probe-traffic.jsonl）
WB_PERMISSION_OPTIONS = [
    {"kind": "allow_always", "name": "Always Allow", "optionId": "allow_always"},
    {"kind": "allow_once", "name": "Allow", "optionId": "allow"},
    {"kind": "reject_once", "name": "Reject", "optionId": "reject"},
]


def test_workbuddy_mode_map_uses_real_cli_values() -> None:
    """映射值必须是 CLI session/new 真实下发的 value，否则 set_config_option 会被拒。"""
    assert workbuddy_module.WorkBuddyAdapter._MODE_TO_WB == {
        "read-only": "plan",
        "agent": "default",
        "agent-full-access": "bypassPermissions",
    }


def test_workbuddy_apply_permission_mode_value() -> None:
    sent: list[dict] = []

    class FakeClient:
        async def request(self, method, params, timeout_s=None):
            sent.append(params)

    adapter = workbuddy_module.WorkBuddyAdapter()
    asyncio.run(adapter._apply_permission_mode(FakeClient(), "sess_x", "read-only"))
    asyncio.run(adapter._apply_permission_mode(FakeClient(), "sess_x", "agent"))
    asyncio.run(adapter._apply_permission_mode(FakeClient(), "sess_x", "agent-full-access"))
    assert [item["value"] for item in sent] == ["plan", "default", "bypassPermissions"]


def test_workbuddy_unknown_mode_falls_back_to_always_ask() -> None:
    """未知模式兜底 default：宁可转 UI 授权，也不静默放行。"""
    sent: list[dict] = []

    class FakeClient:
        async def request(self, method, params, timeout_s=None):
            sent.append(params)

    adapter = workbuddy_module.WorkBuddyAdapter()
    asyncio.run(adapter._apply_permission_mode(FakeClient(), "sess_x", "not-a-mode"))
    assert sent[0]["value"] == "default"


def test_workbuddy_option_id_matches_by_kind() -> None:
    """kind=allow_once 的真实 optionId 是 "allow"；按 optionId 猜会静默升级成永久放行。"""
    find = workbuddy_module._option_id_for_kind
    assert find(WB_PERMISSION_OPTIONS, "allow_once", "allow_always") == "allow"
    assert find(WB_PERMISSION_OPTIONS, "reject_once", "reject_always") == "reject"
    assert find(WB_PERMISSION_OPTIONS, "reject_always", "reject_once") == "reject"
    # Codex 惯例：optionId 与 kind 同名，共用同一套逻辑不能回归
    codex_style = [{"optionId": "allow_once"}, {"optionId": "reject_once"}]
    assert find(codex_style, "allow_once", "allow_always") == "allow_once"
    assert find(codex_style, "reject_once", "reject_always") == "reject_once"
    assert find([], "allow_once") is None


def test_workbuddy_approve_resolves_kind_option_id() -> None:
    adapter = workbuddy_module.WorkBuddyAdapter()

    async def decide(decision: str, options: list[dict]) -> dict:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict] = loop.create_future()
        adapter._permission_futures["task_wb"] = future
        adapter._pending_permissions["task_wb"] = {"options": options}
        await adapter.approve("task_wb", decision)
        return future.result()

    assert asyncio.run(decide("approved", WB_PERMISSION_OPTIONS)) == {
        "outcome": "selected",
        "optionId": "allow",
    }
    assert asyncio.run(decide("rejected", WB_PERMISSION_OPTIONS)) == {
        "outcome": "selected",
        "optionId": "reject",
    }
    # 无可选项时按 cancelled 收口（ACP 没有 "rejected" 这种 outcome）
    assert asyncio.run(decide("rejected", [])) == {"outcome": "cancelled"}


def test_workbuddy_full_access_auto_approves_without_ui() -> None:
    """全权限模式无人值守：直接按 kind 放行，不进 awaiting_approval。"""
    adapter = workbuddy_module.WorkBuddyAdapter()
    updates: list[tuple] = []

    async def on_update(kind, payload):
        updates.append((kind, payload))

    handler = adapter._make_permission_handler("task_wb_full", "agent-full-access", on_update)
    outcome = asyncio.run(
        handler({"options": WB_PERMISSION_OPTIONS, "toolCall": {"rawInput": {"command": "ls"}}})
    )
    assert outcome == {"outcome": "selected", "optionId": "allow"}
    assert updates == []
    assert "task_wb_full" not in adapter._pending_permissions


def test_workbuddy_agent_mode_forwards_permission_to_ui() -> None:
    """agent(default) 模式必须把授权转给界面，而不是自己决定。"""
    adapter = workbuddy_module.WorkBuddyAdapter()
    updates: list[tuple] = []

    async def on_update(kind, payload):
        updates.append((kind, payload))

    handler = adapter._make_permission_handler("task_wb_agent", "agent", on_update)

    async def scenario() -> dict:
        pending = asyncio.create_task(
            handler({"options": WB_PERMISSION_OPTIONS, "toolCall": {"rawInput": {"command": "ls"}}})
        )
        await asyncio.sleep(0.01)
        await adapter.approve("task_wb_agent", "approved")
        return await pending

    assert asyncio.run(scenario()) == {"outcome": "selected", "optionId": "allow"}
    assert [kind for kind, _ in updates] == ["permission_request"]


def test_workbuddy_internet_env_not_forced_by_default(monkeypatch) -> None:
    """网络环境交给 WorkBuddy 自身持久化状态：未显式配置时不得注入。

    该值填错会 401 endpoint mismatch（CLI 自带文档），是 P1 refusal 的嫌疑之一。
    """
    from app.agents.catalog import AgentCatalogEntry

    runtime = workbuddy_module.WorkBuddyRuntime(
        cli=Path("/tmp/workbuddy-cli"),
        runner=Path("/tmp/workbuddy-app"),
        electron=True,
    )
    monkeypatch.delenv("CODEBUDDY_INTERNET_ENVIRONMENT", raising=False)

    default_env = workbuddy_module.WorkBuddyAdapter()._child_env(runtime)
    assert "CODEBUDDY_INTERNET_ENVIRONMENT" not in default_env

    configured = workbuddy_module.WorkBuddyAdapter(
        catalog_entry=AgentCatalogEntry(
            name="workbuddy",
            label="WorkBuddy",
            adapter="workbuddy",
            enabled=True,
            commands=["workbuddy"],
            protocol="acp",
            capabilities=["task"],
            source_url=None,
            tags=[],
            detail="",
            config={"internet_environment": "ioa"},
        )
    )
    assert configured._child_env(runtime)["CODEBUDDY_INTERNET_ENVIRONMENT"] == "ioa"


def test_workbuddy_api_key_is_injected_and_never_returned(tmp_path, monkeypatch) -> None:
    """自备 API Key：落库 → 注入子进程 env → 明文永不出接口。

    WorkBuddy CLI 2.147.0 起凭据落盘加密，解封用的 protector key 只下发给桌面端自己的
    子进程，外部进程拉起的 CLI 读不到（at-rest-failures 记 missing-key），2026-10-01
    在 macOS 与 Windows 双端复现。唯一通道是把 Key 经 env 传给子进程。
    """
    runtime = workbuddy_module.WorkBuddyRuntime(
        cli=Path("/tmp/qiling-workbuddy-cli"),
        runner=Path("/tmp/qiling-workbuddy-runner"),
        electron=True,
    )
    with make_client(tmp_path, monkeypatch) as client:
        saved = client.put(
            "/api/agents/workbuddy/config",
            json={"api_key": "wb-test-secret"},
        )
        assert saved.status_code == 200

        listed = client.get("/api/agents/config")
        assert "wb-test-secret" not in listed.text, "明文密钥不得出现在配置接口里"
        workbuddy = next(item for item in listed.json()["items"] if item["name"] == "workbuddy")
        assert workbuddy["api_key_configured"] is True

        adapter = client.app.state.agent_registry.get("workbuddy")
        assert adapter is not None
        assert adapter._child_env(runtime)["CODEBUDDY_API_KEY"] == "wb-test-secret"

        # 空串 = 清除，回落到系统环境里的 CODEBUDDY_API_KEY
        cleared = client.put("/api/agents/workbuddy/config", json={"api_key": ""})
        assert cleared.status_code == 200
        listed = client.get("/api/agents/config").json()
        workbuddy = next(item for item in listed["items"] if item["name"] == "workbuddy")
        assert workbuddy["api_key_configured"] is False
        assert "CODEBUDDY_API_KEY" not in client.app.state.agent_registry.get("workbuddy")._child_env(runtime)

        # 其余执行器沿用自身登录态，不接受这个字段
        rejected = client.put("/api/agents/codex/config", json={"api_key": "nope"})
        assert rejected.status_code == 400


def test_workbuddy_exec_probe_flags_refusal(monkeypatch) -> None:
    """真实 prompt 探测：能建会话但被 refusal 时不能算 ready。

    账号为空时 session/new 照样成功，只有 session/prompt 才回 refusal——这正是
    P1「WorkBuddy 拒绝执行该任务」的形态，握手探针看不出来。
    """
    runtime = workbuddy_module.WorkBuddyRuntime(
        cli=Path("/tmp/qiling-workbuddy-cli"),
        runner=Path("/tmp/qiling-workbuddy-runner"),
        electron=True,
    )

    def probe_with(stop_reason: str, meta: dict | None = None):
        class FakeClient:
            async def request(self, method, params, timeout_s=None):
                if method == "session/new":
                    return {"sessionId": "sess_probe"}
                if method == "session/prompt":
                    return {"stopReason": stop_reason, "_meta": meta or {}}
                return {}

            async def close(self):
                return None

        async def fake_spawn(*args, **kwargs):
            return FakeClient()

        monkeypatch.setattr(workbuddy_module.AcpClient, "spawn", fake_spawn)
        adapter = workbuddy_module.WorkBuddyAdapter()
        asyncio.run(adapter._run_exec_probe(runtime))
        return adapter

    # 完全没凭据：CLI 只回一句 Authentication required → 引导去申请 Key
    refused = probe_with("refusal")
    assert refused._exec_probe[1] == "auth_required"
    assert "申请" in refused._exec_probe[2]
    assert "订阅" in refused._exec_probe[2]

    # 带了 Key 但被拒：报错里会带 401 与 auth-type → 引导去核对订阅/换 Key
    rejected = probe_with(
        "refusal",
        {
            "codebuddy.ai/errorMessage": (
                '{"code":-32000,"message":"Authentication required",'
                '"data":{"statusCode":401,"details":"401 Authentication required '
                '(auth-type:cli-external-link,token-type:ApiKey)"}}'
            )
        },
    )
    assert rejected._exec_probe[1] == "auth_required"
    assert "拒绝了这把 API Key" in rejected._exec_probe[2]
    assert rejected._exec_probe[2] != refused._exec_probe[2], "两种失败形态的引导必须不同"

    healthy = probe_with("end_turn")
    assert healthy._exec_probe[1] == "ready"


def test_workbuddy_exec_probe_is_off_the_request_path(monkeypatch) -> None:
    """探测必须后台跑：健康检查只有 3~5s 超时，真实 prompt 要十几秒。"""
    runtime = workbuddy_module.WorkBuddyRuntime(
        cli=Path("/tmp/qiling-workbuddy-cli"),
        runner=Path("/tmp/qiling-workbuddy-runner"),
        electron=True,
    )

    class FakeClient:
        async def request(self, method, params, timeout_s=None):
            if method == "session/new":
                return {"sessionId": "sess_probe"}
            if method == "session/prompt":
                return {"stopReason": "end_turn"}
            return {}

        async def close(self):
            return None

    async def fake_spawn(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(workbuddy_module.AcpClient, "spawn", fake_spawn)

    async def check():
        adapter = workbuddy_module.WorkBuddyAdapter()
        status, detail = adapter._exec_verdict(runtime)
        # 还没有结论：立刻返回，绝不 await 真实探测
        assert (status, detail) == (None, None)
        assert adapter._exec_task is not None
        await adapter._exec_task
        return adapter

    adapter = asyncio.run(check())
    assert adapter._exec_probe[1] == "ready"
    status, detail = adapter._exec_verdict(runtime)
    assert status == "ready" and detail


def test_workbuddy_probe_uses_dedicated_workdir_not_home(monkeypatch) -> None:
    """探测不能拿用户主目录当 CLI workspace：Windows 主目录可能极大，白扫一遍且暴露隐私。"""
    captured: dict[str, object] = {}

    class FakeClient:
        async def request(self, method, params, timeout_s=None):
            if method == "session/new":
                captured["session_cwd"] = params["cwd"]
                return {"sessionId": "sess_probe"}
            if method == "session/prompt":
                return {"stopReason": "end_turn"}
            return {}

        async def close(self):
            return None

    async def fake_spawn(
        command,
        *,
        args=None,
        cwd,
        env,
        on_update=None,
        on_permission=None,
        logs_dir=None,
        stderr_log_name="workbuddy-acp-stderr.log",
    ):
        captured["process_cwd"] = cwd
        return FakeClient()

    monkeypatch.setattr(workbuddy_module.AcpClient, "spawn", fake_spawn)
    runtime = workbuddy_module.WorkBuddyRuntime(
        cli=Path("/tmp/qiling-workbuddy-cli"),
        runner=Path("/tmp/qiling-workbuddy-runner"),
        electron=True,
    )
    adapter = workbuddy_module.WorkBuddyAdapter()
    asyncio.run(adapter._run_exec_probe(runtime))

    workdir = workbuddy_module._probe_workdir()
    assert captured["process_cwd"] == workdir
    assert captured["session_cwd"] == workdir
    assert workdir != str(Path.home())
    assert Path(workdir).is_dir()


def test_acp_cli_executor_config_accepts_command_and_key(tmp_path, monkeypatch) -> None:
    """ACP 主线：通用执行器可在页面覆盖启动命令并自备凭据，明文不出接口。"""
    with make_client(tmp_path, monkeypatch) as client:
        saved = client.put(
            "/api/agents/qwen-code/config",
            json={"command": "qwen --acp", "api_key": "qwen-test-secret"},
        )
        assert saved.status_code == 200

        listed = client.get("/api/agents/config")
        assert "qwen-test-secret" not in listed.text, "明文密钥不得出现在配置接口里"
        entry = next(item for item in listed.json()["items"] if item["name"] == "qwen-code")
        assert entry["config"]["qwen-code_command"] == "qwen --acp"
        assert entry["api_key_configured"] is True

        # 没声明 api_key_env、也不消费 Key 的执行器仍拒绝该字段
        rejected = client.put("/api/agents/browser/config", json={"api_key": "nope"})
        assert rejected.status_code == 400
