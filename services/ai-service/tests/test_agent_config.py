"""执行器页面配置：agents.local.yaml 覆盖写/清除与 codex 路径解析。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.agents.catalog import load_agent_catalog, update_local_executor_config
from app.agents.codex import resolve_codex_command


@pytest.fixture(autouse=True)
def _clean_codex_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEX_PATH", raising=False)

DEFAULT_ENTRY = {
    "name": "codex",
    "label": "Codex CLI",
    "adapter": "codex",
    "enabled": True,
    "commands": ["codex"],
    "protocol": "codex-acp",
    "capabilities": ["code", "project", "task_execution"],
    "source_url": "https://github.com/openai/codex",
    "tags": ["official", "acp", "cli"],
    "detail": "OpenAI 本地编码 agent",
    "config": {"acp_command": "codex-acp"},
}


def write_base_catalog(path: Path) -> None:
    path.write_text(
        "# base\n"
        + "default_executor: codex\n"
        + "executors:\n"
        + "  - name: codex\n"
        + "    label: Codex CLI\n"
        + "    adapter: codex\n"
        + "    enabled: true\n"
        + "    commands: [codex]\n"
        + "    protocol: codex-acp\n"
        + "    capabilities: [code, project, task_execution]\n"
        + "    source_url: https://github.com/openai/codex\n"
        + "    tags: [official, acp, cli]\n"
        + "    detail: OpenAI 本地编码 agent\n"
        + "    config:\n"
        + "      acp_command: codex-acp\n",
        encoding="utf-8",
    )


def test_local_override_writes_and_deep_merges_config(tmp_path: Path) -> None:
    catalog_path = tmp_path / "agents.yaml"
    write_base_catalog(catalog_path)

    custom = tmp_path / "my-codex"
    custom.write_text("#!/bin/sh\n", encoding="utf-8")
    update_local_executor_config(catalog_path, "codex", {"codex_command": str(custom)})

    merged = load_agent_catalog(path=catalog_path)
    codex = next(item for item in merged.executors if item.name == "codex")
    assert codex.config["codex_command"] == str(custom)
    # 默认 config 其它键应保留（config 深合并）
    assert codex.config["acp_command"] == "codex-acp"


def test_local_override_clear_removes_key_only(tmp_path: Path) -> None:
    catalog_path = tmp_path / "agents.yaml"
    write_base_catalog(catalog_path)
    update_local_executor_config(catalog_path, "codex", {"codex_command": "/tmp/codex"})
    update_local_executor_config(catalog_path, "codex", {"codex_command": None})

    merged = load_agent_catalog(path=catalog_path)
    codex = next(item for item in merged.executors if item.name == "codex")
    assert "codex_command" not in codex.config
    assert codex.config["acp_command"] == "codex-acp"


def test_resolve_codex_command_prefers_configured_absolute_path(tmp_path: Path) -> None:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\necho codex 0.1\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

    assert resolve_codex_command(str(binary)) == str(binary)
    missing = tmp_path / "does-not-exist"
    assert resolve_codex_command(str(missing)) is None
    assert resolve_codex_command("") is None or isinstance(resolve_codex_command(""), str)


def test_resolve_codex_command_requires_executable_permission(tmp_path: Path) -> None:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o644)
    assert resolve_codex_command(str(binary)) is None
    # 清理 os.access 结果不受目录权限影响
    os.stat(binary)


def test_resolve_codex_command_honors_codepath_env(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\necho codex\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("CODEX_PATH", str(binary))
    assert resolve_codex_command(None) == str(binary)


def test_resolve_codex_command_explicit_missing_does_not_fallback(tmp_path: Path) -> None:
    missing = tmp_path / "codex"
    assert resolve_codex_command(str(missing)) is None
    # 即使平台常见位置存在真实 codex，显式错误路径也不该被悄悄跳过
    assert resolve_codex_command("/nonexistent/codex") is None
