"""安全存储后端的平台分支测试。"""

from __future__ import annotations

from app.agents import secret_store


def test_macos_secret_store_uses_security_commands(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "secret-value\n"
        stderr = ""

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(secret_store.sys, "platform", "darwin")
    monkeypatch.setattr(secret_store.subprocess, "run", fake_run)
    store = secret_store.SecretStore()

    store.store("workbuddy", "secret-value")
    assert calls[0][-1] == "secret-value"
    assert store.read("workbuddy") == "secret-value"
    store.delete("workbuddy")
    assert calls[-1][0].endswith("/security")
