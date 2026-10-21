"""本机安全存储：执行器凭据不写入明文配置文件。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class SecretStoreError(RuntimeError):
    """安全存储不可用或读写失败。"""


class SecretStore:
    """按执行器名存取凭据，macOS 用 Keychain，Windows 用 DPAPI。"""

    _SERVICE = "app.qiling.desktop"

    @staticmethod
    def _account(name: str) -> str:
        return f"executor:{name}"

    @staticmethod
    def _binary(name: str) -> str:
        path = shutil.which(name)
        if not path:
            raise SecretStoreError(f"未找到系统命令：{name}")
        return path

    def store(self, name: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise SecretStoreError("凭据不能为空。")
        try:
            if sys.platform == "darwin":
                subprocess.run(
                    [
                        self._binary("security"),
                        "add-generic-password",
                        "-U",
                        "-a",
                        self._account(name),
                        "-s",
                        self._SERVICE,
                        "-w",
                        value,
                    ],
                    text=True,
                    check=True,
                    capture_output=True,
                )
            elif sys.platform == "win32":
                self._store_windows(name, value)
            else:
                raise SecretStoreError("当前平台没有可用的本机安全存储。")
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretStoreError(f"无法写入本机安全存储：{exc}") from exc

    def read(self, name: str) -> str | None:
        try:
            if sys.platform == "darwin":
                result = subprocess.run(
                    [
                    self._binary("security"),
                        "find-generic-password",
                        "-a",
                        self._account(name),
                        "-s",
                        self._SERVICE,
                        "-w",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode != 0:
                    return None
                return result.stdout.strip() or None
            if sys.platform == "win32":
                return self._read_windows(name)
            return None
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretStoreError(f"无法读取本机安全存储：{exc}") from exc

    def exists(self, name: str) -> bool:
        return self.read(name) is not None

    def delete(self, name: str) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.run(
                    [
                        self._binary("security"),
                        "delete-generic-password",
                        "-a",
                        self._account(name),
                        "-s",
                        self._SERVICE,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            elif sys.platform == "win32":
                path = self._windows_path(name)
                if path.exists():
                    path.unlink()
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretStoreError(f"无法删除本机安全存储：{exc}") from exc

    @staticmethod
    def _windows_path(name: str) -> Path:
        return Path.home() / ".qiling" / "secrets" / f"{name}.dpapi"

    @classmethod
    def _store_windows(cls, name: str, value: str) -> None:
        path = cls._windows_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        script = (
            "$secure = ConvertTo-SecureString $env:QILING_SECRET_VALUE -AsPlainText -Force; "
            "$encrypted = ConvertFrom-SecureString $secure; "
            "[IO.File]::WriteAllText($env:QILING_SECRET_PATH, $encrypted)"
        )
        env = {**os.environ, "QILING_SECRET_VALUE": value, "QILING_SECRET_PATH": str(path)}
        subprocess.run(
            [cls._binary("powershell"), "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            text=True,
            check=True,
            capture_output=True,
        )

    @classmethod
    def _read_windows(cls, name: str) -> str | None:
        path = cls._windows_path(name)
        if not path.is_file():
            return None
        script = (
            "$secure = ConvertTo-SecureString ([IO.File]::ReadAllText($env:QILING_SECRET_PATH)); "
            "$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); "
            "try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } "
            "finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }"
        )
        env = {**os.environ, "QILING_SECRET_PATH": str(path)}
        result = subprocess.run(
            [cls._binary("powershell"), "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip() or None
