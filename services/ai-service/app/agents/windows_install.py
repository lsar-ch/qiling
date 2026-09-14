"""Windows 安装位置探测：注册表「添加或删除程序」+ 非系统盘兜底。

背景（WI-05）：Windows 安装器普遍允许换盘安装（实测 WorkBuddy 装在
``D:\\Program Files\\WorkBuddy``），而仅靠 ``ProgramFiles`` / ``LOCALAPPDATA``
环境变量拼出的候选路径全部指向 C 盘，自动发现必然落空。

本模块只在 ``sys.platform == "win32"`` 时返回结果，其它平台一律返回空，
调用方不必再写平台分支。依赖全部来自标准库（``winreg`` / ``ctypes``）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PureWindowsPath

_UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

_DRIVE_FIXED = 3


def registry_candidates(
    app_names: tuple[str, ...], exe_names: tuple[str, ...]
) -> tuple[Path, ...]:
    """从注册表已安装条目里取候选可执行文件路径（跨盘通用，不猜盘符）。

    ``app_names`` 匹配 ``DisplayName``（大小写不敏感的子串匹配），
    ``exe_names`` 是 ``InstallLocation`` / ``DisplayIcon`` 目录下的目标 exe。
    返回路径**不保证存在**，由调用方按各自的可执行性规则过滤。
    """
    hits: list[Path] = []
    for display_name, install_location, display_icon in _installed_entries():
        hits.extend(
            _entry_candidates(
                display_name, install_location, display_icon, app_names, exe_names
            )
        )
    return tuple(hits)


def fixed_drive_roots() -> tuple[Path, ...]:
    """本机固定磁盘根目录（如 ``D:\\``）。只取 DRIVE_FIXED，避开光盘与断连网络盘。"""
    if sys.platform != "win32":
        return ()
    import ctypes

    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    roots = []
    for index in range(26):
        if not mask >> index & 1:
            continue
        root = f"{chr(ord('A') + index)}:\\"
        if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == _DRIVE_FIXED:
            roots.append(Path(root))
    return tuple(roots)


def _installed_entries() -> tuple[tuple[str, str, str], ...]:
    """读取「添加或删除程序」条目：``(DisplayName, InstallLocation, DisplayIcon)``。"""
    if sys.platform != "win32":
        return ()
    import winreg

    def read(key, name: str) -> str:
        try:
            value, kind = winreg.QueryValueEx(key, name)
        except OSError:
            return ""
        if not isinstance(value, str):
            return ""
        text = value.strip()
        # REG_EXPAND_SZ 里可能写着 %ProgramFiles% 之类的变量
        return os.path.expandvars(text) if kind == winreg.REG_EXPAND_SZ else text

    def subkeys(hive, flags: int) -> list[str]:
        try:
            with winreg.OpenKey(hive, _UNINSTALL_KEY, 0, winreg.KEY_READ | flags) as key:
                return [
                    winreg.EnumKey(key, index)
                    for index in range(winreg.QueryInfoKey(key)[0])
                ]
        except OSError:
            return []

    # 64 位安装、32 位（WOW6432Node）安装、当前用户安装各扫一遍
    entries = []
    for hive, flags in (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ):
        for name in subkeys(hive, flags):
            subkey = f"{_UNINSTALL_KEY}\\{name}"
            try:
                with winreg.OpenKey(
                    hive, subkey, 0, winreg.KEY_READ | flags
                ) as key:
                    entries.append(
                        (
                            read(key, "DisplayName"),
                            read(key, "InstallLocation"),
                            read(key, "DisplayIcon"),
                        )
                    )
            except OSError:
                continue
    return tuple(entries)


def _entry_candidates(
    display_name: str,
    install_location: str,
    display_icon: str,
    app_names: tuple[str, ...],
    exe_names: tuple[str, ...],
) -> tuple[Path, ...]:
    """把一条已安装记录翻译成候选 exe 路径（纯函数，便于跨平台测试）。"""
    lowered = display_name.lower()
    if not lowered or not any(name.lower() in lowered for name in app_names):
        return ()
    directories = [
        directory
        for directory in (
            _clean(install_location),
            _icon_directory(display_icon),
        )
        if directory
    ]
    return tuple(Path(directory) / exe for directory in directories for exe in exe_names)


def _icon_directory(value: str) -> str:
    """解析 ``DisplayIcon``：形如 ``"D:\\...\\WorkBuddy.exe",0``，取所在目录。"""
    text = _clean(value)
    head, _, tail = text.rpartition(",")
    if head and tail.strip().isdigit():
        text = _clean(head)
    # 注册表里存的恒为 Windows 路径，解析不依赖宿主平台
    directory = PureWindowsPath(text).parent if text else PureWindowsPath()
    return "" if str(directory) in ("", ".") else str(directory)


def _clean(value: str) -> str:
    return value.strip().strip('"').strip()
