"""办公引擎目录：探测本机可用性、按需安装、把已装引擎用于转换。

DeskMate 只做三件事：读 ``config/office_tools.yaml``、探测本机是否已装、按
``install.kind`` 安装或跳转下载页；装好的引擎由这里统一调用（目前是 LibreOffice 转换）。
工具本体不随 DeskMate 分发（内置渲染器除外），
以此避开包体膨胀与许可证问题 —— 与「技能扩展」页的插件模式一致。

安装方式（``install.kind``）：
- ``builtin``：随 AI 服务内置，无需安装；
- ``pip``：在本服务虚拟环境执行 ``pip install``，装完即可调用；
- ``link``：打开官方下载页由用户自行安装，回来后点「重新检测」。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from app.config import repo_root
from deskmate_contracts import OfficeToolInfo

_INSTALL_TIMEOUT_S = 600
_OUTPUT_TAIL_CHARS = 1500


class OfficeToolError(RuntimeError):
    """目录缺失/解析失败，或请求了未登记的工具。"""


def catalog_path() -> Path:
    """办公引擎目录路径（支持 ``DESKMATE_OFFICE_TOOLS_CONFIG`` 覆盖）。"""
    configured = os.environ.get("DESKMATE_OFFICE_TOOLS_CONFIG")
    return Path(configured) if configured else repo_root() / "config" / "office_tools.yaml"


def load_tools(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or catalog_path()
    if not target.exists():
        raise OfficeToolError(f"办公引擎目录不存在：{target}")
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    tools = data.get("tools")
    if not isinstance(tools, list) or not tools:
        raise OfficeToolError(f"办公引擎目录为空或格式错误：{target}")
    return tools


def detect(tool: dict[str, Any]) -> bool:
    """探测工具是否已安装：内置恒真，模块看 import，命令行看 PATH。"""
    spec = tool.get("detect") or {}
    kind = spec.get("kind", "command")
    value = spec.get("value") or tool.get("name", "")
    if kind == "builtin":
        return True
    if kind == "python-module":
        try:
            return importlib.util.find_spec(value) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            return False
    return shutil.which(value) is not None


def to_info(tool: dict[str, Any]) -> OfficeToolInfo:
    install = tool.get("install") or {}
    name = tool["name"]
    return OfficeToolInfo(
        name=name,
        label=tool.get("label") or name,
        detail=tool.get("detail") or "",
        homepage=tool.get("homepage"),
        license=tool.get("license") or "",
        powers=[str(item) for item in tool.get("powers") or []],
        install_kind=install.get("kind", "link"),
        installed=detect(tool),
    )


def list_tools() -> list[OfficeToolInfo]:
    return [to_info(tool) for tool in load_tools()]


def find_tool(name: str) -> dict[str, Any]:
    for tool in load_tools():
        if tool.get("name") == name:
            return tool
    raise OfficeToolError(f"未登记的办公引擎：{name}")


def install(name: str) -> tuple[bool, str]:
    """按目录声明安装工具，返回 ``(是否成功, 说明)``。

    只有 ``pip`` 类型会真正执行安装；``link`` 类型交给前端打开下载页。
    """
    tool = find_tool(name)
    if detect(tool):
        return True, "已安装，无需重复安装。"
    install_spec = tool.get("install") or {}
    kind = install_spec.get("kind", "link")
    if kind == "builtin":
        return True, "内置组件，无需安装。"
    if kind == "pip":
        package = install_spec.get("package")
        if not package:
            return False, "目录缺少 pip 包名，无法安装。"
        return _pip_install(str(package))
    return False, "需自行安装：请打开下载页，装好后回到本页点「重新检测」。"


def _pip_install(package: str) -> tuple[bool, str]:
    # install.sh 不参与：只在服务自身的虚拟环境里装，包名来自目录文件而非用户输入。
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", package]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"安装超时（>{_INSTALL_TIMEOUT_S}s）：{package}"
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    tail = output[-_OUTPUT_TAIL_CHARS:]
    if proc.returncode != 0:
        return False, f"安装失败（退出码 {proc.returncode}）：\n{tail}"
    return True, f"已安装 {package}，可直接调用。\n{tail}"


# ── 调用：把已装引擎用于转换（Pandoc 管 Markdown，LibreOffice 管其余）────
_CONVERT_FORMATS = {"pdf": "pdf", "word": "docx", "excel": "xlsx", "ppt": "pptx", "markdown": "md"}
_PANDOC_SOURCE_SUFFIXES = {".md", ".markdown"}
_CONVERT_TIMEOUT_S = 300


def soffice_binary() -> str | None:
    """LibreOffice 可执行文件；``soffice`` / ``libreoffice`` 任一在 PATH 即算装了。"""
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert(source: Path, target_kind: str, outdir: Path | None = None) -> Path:
    """用已装引擎把办公文件转成目标格式，返回产物路径。

    涉及 Markdown 的转换走 Pandoc（md <-> docx/pptx/md），其余走 LibreOffice；
    引擎没装、目标格式不支持或转换失败时抛 ``OfficeToolError``，由调用方转成可读提示。
    产物落在源文件同目录（``outdir`` 可覆盖）。
    """
    fmt = _CONVERT_FORMATS.get(target_kind)
    if fmt is None:
        raise OfficeToolError(f"不支持的目标格式：{target_kind}")
    if source.suffix.lower() == f".{fmt}":
        raise OfficeToolError(f"源文件已经是 {fmt}，无需转换。")
    if engine_for(source, target_kind) == "pandoc":
        return _pandoc_convert(source, fmt, outdir)
    return _libreoffice_convert(source, fmt, outdir)


def engine_for(source: Path, target_kind: str) -> str:
    """这次转换会用哪个引擎：Markdown 相关走 Pandoc，其余 LibreOffice。"""
    if target_kind == "markdown" or source.suffix.lower() in _PANDOC_SOURCE_SUFFIXES:
        return "pandoc"
    return "libreoffice"


def pandoc_binary() -> str | None:
    """Pandoc 可执行文件（在 PATH 即算装了）。"""
    return shutil.which("pandoc")


def _output_path(source: Path, fmt: str, outdir: Path | None) -> Path:
    destination = Path(outdir) if outdir else source.parent
    destination.mkdir(parents=True, exist_ok=True)
    return destination / f"{source.stem}.{fmt}"


def _pandoc_convert(source: Path, fmt: str, outdir: Path | None = None) -> Path:
    binary = pandoc_binary()
    if binary is None:
        raise OfficeToolError("未检测到 Pandoc：请到「技能扩展 → 办公工具」安装后重试。")
    target = _output_path(source, fmt, outdir)
    command = [binary, str(source), "-o", str(target)]
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=_CONVERT_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        raise OfficeToolError(f"Pandoc 转换超时（>{_CONVERT_TIMEOUT_S}s）") from None
    except OSError as exc:
        raise OfficeToolError(f"Pandoc 启动失败：{exc}") from exc
    if proc.returncode != 0 or not target.exists():
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-_OUTPUT_TAIL_CHARS:]
        raise OfficeToolError(f"Pandoc 转换失败：{tail or '未知错误'}")
    return target


def _libreoffice_convert(source: Path, fmt: str, outdir: Path | None = None) -> Path:
    binary = soffice_binary()
    if binary is None:
        raise OfficeToolError("未检测到 LibreOffice：请到「技能扩展 → 办公工具」安装后重试。")
    destination = Path(outdir) if outdir else source.parent
    destination.mkdir(parents=True, exist_ok=True)
    # 独立 profile，避免和用户正在用的 LibreOffice 实例抢锁。
    with tempfile.TemporaryDirectory(prefix="deskmate-lo-profile-") as profile:
        command = [
            binary,
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--convert-to",
            fmt,
            "--outdir",
            str(destination),
            str(source),
        ]
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=_CONVERT_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            raise OfficeToolError(f"LibreOffice 转换超时（>{_CONVERT_TIMEOUT_S}s）") from None
        except OSError as exc:
            raise OfficeToolError(f"LibreOffice 启动失败：{exc}") from exc
    target = destination / f"{source.stem}.{fmt}"
    if proc.returncode != 0 or not target.exists():
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-_OUTPUT_TAIL_CHARS:]
        raise OfficeToolError(f"LibreOffice 转换失败：{tail or '未知错误'}")
    return target
