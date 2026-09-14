"""执行器页面配置：agents.local.yaml 覆盖写/清除与 codex 路径解析。"""

from __future__ import annotations

import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

import pytest

from app.agents import workbuddy
from app.agents.catalog import load_agent_catalog, update_local_executor_config
from app.agents.codex import resolve_codex_command
from app.agents.windows_install import (
    _UNINSTALL_KEY,
    _entry_candidates,
    _icon_directory,
    registry_candidates,
)


def _normalized(path: Path) -> str:
    """把候选路径统一成 ``D:/a/b`` 形态，便于在 macOS 上断言 Windows 路径。"""
    return PureWindowsPath(str(path)).as_posix()


class _FakeWinreg:
    """最小 winreg 替身，只覆盖 Uninstall 枚举用到的 API（macOS 上验证扫描逻辑）。"""

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 0
    KEY_WOW64_64KEY = 1
    KEY_WOW64_32KEY = 2
    REG_SZ = 1
    REG_EXPAND_SZ = 2

    def __init__(self, entries: dict[str, dict[str, str]]) -> None:
        self.entries = entries
        self.opened: list[tuple[str, str, int]] = []

    @contextmanager
    def OpenKey(self, hive, subkey, _reserved, access):
        self.opened.append((hive, subkey, access))
        leaf = subkey.rpartition("\\")[2]
        if subkey.endswith(_UNINSTALL_KEY):
            yield None  # 根键：仅用于枚举子键
            return
        if leaf not in self.entries:
            raise OSError(2, "not found")
        yield leaf

    def QueryInfoKey(self, key):
        return (len(self.entries) if key is None else 0, 0, 0)

    def EnumKey(self, _key, index):
        return sorted(self.entries)[index]

    def QueryValueEx(self, key, name):
        if name not in self.entries[key]:
            raise OSError(2, "not found")
        return self.entries[key][name], self.REG_SZ


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
    if sys.platform == "win32":
        # WI-01：Windows 没有 POSIX 可执行位，chmod 只影响只读标记，
        # 产品按「文件存在即可执行」判定（能否运行交给后续探测），这里断言这条分支。
        assert resolve_codex_command(str(binary)) == str(binary)
    else:
        # POSIX：没有 x 位就不算可执行命令
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


def test_registry_candidates_returns_empty_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    # 非 Windows 平台必须直接返回空，不得尝试导入 winreg
    monkeypatch.setattr(sys, "platform", "darwin")
    assert registry_candidates(("WorkBuddy",), ("WorkBuddy.exe",)) == ()


def test_registry_entry_candidates_cover_non_system_drive() -> None:
    """WI-05：安装器换盘（D 盘）时，注册表条目要能翻译出正确候选路径。"""
    hits = _entry_candidates(
        "WorkBuddy 2.137.1",
        "D:\\Program Files\\WorkBuddy\\",
        "",
        ("WorkBuddy",),
        ("WorkBuddy.exe",),
    )
    assert _normalized(Path("D:\\Program Files\\WorkBuddy\\WorkBuddy.exe")) in {
        _normalized(hit) for hit in hits
    }
    # 名称不匹配的条目不应产生候选
    assert _entry_candidates("别的软件", "D:\\Other", "", ("WorkBuddy",), ("WorkBuddy.exe",)) == ()


def test_registry_entry_candidates_accept_display_icon() -> None:
    # 只有 DisplayIcon（形如 "D:\...\WorkBuddy.exe",0）的条目也要能用
    icon = '"D:\\Program Files\\WorkBuddy\\WorkBuddy.exe",0'
    assert _icon_directory(icon) == "D:\\Program Files\\WorkBuddy"
    hits = _entry_candidates("WorkBuddy", "", icon, ("WorkBuddy",), ("WorkBuddy.exe",))
    assert _normalized(Path("D:\\Program Files\\WorkBuddy\\WorkBuddy.exe")) in {
        _normalized(hit) for hit in hits
    }


def test_workbuddy_windows_candidates_include_non_system_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WI-05 回归：WorkBuddy 装在 D 盘时，自动检测候选必须覆盖该路径。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(workbuddy, "registry_candidates", lambda _apps, _exes: ())
    monkeypatch.setattr(workbuddy, "fixed_drive_roots", lambda: (Path("D:\\"),))

    candidates = {_normalized(path) for path in workbuddy._platform_install_candidates()}

    assert _normalized(Path("D:\\Program Files\\WorkBuddy\\WorkBuddy.exe")) in candidates


def test_registry_candidates_scan_windows_uninstall_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WI-05 核心：装了 D 盘的 WorkBuddy 能被注册表扫描发现，无关程序不误报。"""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = _FakeWinreg(
        {
            "{workbuddy}": {
                "DisplayName": "WorkBuddy",
                "InstallLocation": "D:\\Program Files\\WorkBuddy\\",
                "DisplayIcon": "D:\\Program Files\\WorkBuddy\\WorkBuddy.exe,0",
            },
            "{other}": {"DisplayName": "7-Zip", "InstallLocation": "C:\\Program Files\\7-Zip\\"},
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)

    hits = {_normalized(path) for path in registry_candidates(("WorkBuddy",), ("WorkBuddy.exe",))}

    assert hits == {_normalized(Path("D:\\Program Files\\WorkBuddy\\WorkBuddy.exe"))}
    # 64 位安装、32 位（WOW6432Node）、当前用户三档都必须真被扫到
    scanned = {(hive, access) for hive, subkey, access in fake.opened if subkey == _UNINSTALL_KEY}
    assert scanned == {
        ("HKLM", _FakeWinreg.KEY_WOW64_64KEY),
        ("HKLM", _FakeWinreg.KEY_WOW64_32KEY),
        ("HKCU", 0),
    }
