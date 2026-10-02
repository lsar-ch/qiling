"""办公引擎目录：探测、安装分支与 API。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import office_tools
from app.config import load_settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_catalog_lists_expected_tools() -> None:
    names = {tool.name for tool in office_tools.list_tools()}
    assert {"builtin-writer", "docxtpl", "pandoc", "typst", "marp", "libreoffice"} <= names


def test_builtin_tool_is_always_detected_and_never_needs_installing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_pip(*args, **kwargs):
        raise AssertionError("内置工具不应触发 pip 安装")

    monkeypatch.setattr(office_tools.subprocess, "run", no_pip)
    tool = office_tools.find_tool("builtin-writer")
    assert office_tools.detect(tool) is True
    ok, message = office_tools.install("builtin-writer")
    assert ok is True
    assert "已安装" in message


def test_detection_by_python_module_and_command() -> None:
    assert office_tools.detect({"name": "x", "detect": {"kind": "python-module", "value": "json"}}) is True
    missing = {"name": "x", "detect": {"kind": "python-module", "value": "no_such_pkg_9f3a"}}
    assert office_tools.detect(missing) is False
    ghost = {"name": "x", "detect": {"kind": "command", "value": "no-such-cmd-9f3a"}}
    assert office_tools.detect(ghost) is False


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(office_tools.OfficeToolError):
        office_tools.find_tool("not-in-catalog")


def test_link_and_already_installed_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """用临时目录验证 link 分支与「已装即短路」，避免测试触发真实 pip 安装。"""
    catalog = tmp_path / "office_tools.yaml"
    catalog.write_text(
        "version: 1\n"
        "tools:\n"
        "  - name: linky\n"
        "    label: Link Tool\n"
        "    install: {kind: link}\n"
        "    detect: {kind: command, value: no-such-cmd-9f3a}\n"
        "  - name: pippy\n"
        "    label: Pip Tool\n"
        "    install: {kind: pip, package: json}\n"
        "    detect: {kind: python-module, value: json}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DESKMATE_OFFICE_TOOLS_CONFIG", str(catalog))

    assert {tool.name for tool in office_tools.list_tools()} == {"linky", "pippy"}

    ok, message = office_tools.install("linky")
    assert ok is False and "下载页" in message

    ok, message = office_tools.install("pippy")
    assert ok is True and "已安装" in message


class _FakeProc:
    def __init__(self, returncode: int, out: str = "", err: str = "") -> None:
        self.returncode = returncode
        self.stdout = out
        self.stderr = err


def test_pip_install_reports_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """不真装依赖：只验证命令形态与退出码/超时的分支处理。"""
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return _FakeProc(0, out="Successfully installed docxtpl-0.20.0")

    monkeypatch.setattr(office_tools.subprocess, "run", fake_run)
    ok, message = office_tools._pip_install("docxtpl")
    assert ok is True and "已安装 docxtpl" in message
    assert calls[0][1:4] == ["-m", "pip", "install"]
    assert calls[0][-1] == "docxtpl"

    monkeypatch.setattr(
        office_tools.subprocess, "run", lambda *a, **k: _FakeProc(1, err="boom")
    )
    ok, message = office_tools._pip_install("docxtpl")
    assert ok is False and "安装失败" in message and "boom" in message

    def timed_out(*args, **kwargs):
        raise office_tools.subprocess.TimeoutExpired(cmd="pip", timeout=1)

    monkeypatch.setattr(office_tools.subprocess, "run", timed_out)
    ok, message = office_tools._pip_install("docxtpl")
    assert ok is False and "超时" in message


def test_office_tools_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "deskmate-home"
    monkeypatch.setenv("DESKMATE_HOME", str(home))
    (home / "config" / "personas").mkdir(parents=True)
    (home / "data").mkdir(parents=True)
    (home / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (home / "config" / "system_prompt.md").write_text("你是 DeskMate。", encoding="utf-8")
    for name in ("agents.yaml", "office_tools.yaml"):
        shutil.copyfile(PROJECT_ROOT / "config" / name, home / "config" / name)
    monkeypatch.delenv("DESKMATE_OFFICE_TOOLS_CONFIG", raising=False)

    with TestClient(create_app(load_settings())) as client:
        listed = client.get("/api/office-tools")
        assert listed.status_code == 200
        items = listed.json()["tools"]
        assert any(item["name"] == "builtin-writer" and item["installed"] for item in items)

        installed = client.post("/api/office-tools/builtin-writer/install")
        assert installed.status_code == 200
        assert installed.json()["ok"] is True

        missing = client.post("/api/office-tools/nope/install")
        assert missing.status_code == 404


def test_convert_requires_libreoffice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "a.docx"
    source.write_bytes(b"x")
    monkeypatch.setattr(office_tools.shutil, "which", lambda name: None)
    with pytest.raises(office_tools.OfficeToolError) as exc:
        office_tools.convert(source, "pdf")
    assert "LibreOffice" in str(exc.value)


def test_convert_rejects_same_format_and_unknown_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(b"%PDF-")
    monkeypatch.setattr(office_tools.shutil, "which", lambda name: "/fake/soffice")
    with pytest.raises(office_tools.OfficeToolError):
        office_tools.convert(source, "pdf")   # 源文件已是目标格式
    with pytest.raises(office_tools.OfficeToolError):
        office_tools.convert(source, "doc")   # 未登记的目标格式


def test_convert_invokes_soffice_headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"x")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        (tmp_path / "report.pdf").write_bytes(b"%PDF-")
        return _FakeProc(0, out="convert ok")

    monkeypatch.setattr(
        office_tools.shutil, "which",
        lambda name: "/fake/soffice" if name == "soffice" else None,
    )
    monkeypatch.setattr(office_tools.subprocess, "run", fake_run)

    produced = office_tools.convert(source, "pdf")
    assert produced == tmp_path / "report.pdf"
    assert "--headless" in calls[0]
    assert calls[0][calls[0].index("--convert-to") + 1] == "pdf"
    assert calls[0][-1] == str(source)


def test_convert_markdown_target_routes_to_pandoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"x")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        (tmp_path / "report.md").write_text("# t\n", encoding="utf-8")
        return _FakeProc(0)

    monkeypatch.setattr(
        office_tools.shutil, "which",
        lambda name: "/fake/pandoc" if name == "pandoc" else None,
    )
    monkeypatch.setattr(office_tools.subprocess, "run", fake_run)

    produced = office_tools.convert(source, "markdown")
    assert produced == tmp_path / "report.md"
    assert calls[0][0] == "/fake/pandoc"
    assert calls[0][1] == str(source) and calls[0][2] == "-o"


def test_convert_markdown_source_without_pandoc_reports_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "readme.md"
    source.write_text("# t\n", encoding="utf-8")
    monkeypatch.setattr(office_tools.shutil, "which", lambda name: None)
    with pytest.raises(office_tools.OfficeToolError) as exc:
        office_tools.convert(source, "word")
    assert "Pandoc" in str(exc.value)
