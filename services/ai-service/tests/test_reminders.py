"""主动提醒：时间解析、存储与触发事件。"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deskmate_contracts.reminder import Reminder
from app.config import load_settings
from app.core.reminders import ReminderEngine, ReminderStore, parse_reminder_message
from app.core.wellness import WellnessEngine
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FakeHub:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, envelope) -> None:
        self.events.append(envelope.model_dump(mode="json"))


def _fixed_now() -> datetime:
    return datetime(2026, 9, 22, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))


@pytest.mark.parametrize(
    ("message", "expect_seconds"),
    [
        ("10分钟后提醒我喝水", 600),
        ("1小时后记得开会", 3600),
        ("明天 9:00 提醒我交周报", 23 * 3600),
        ("今天 12:00 提醒我吃饭", 2 * 3600),
        ("随便聊聊", None),
    ],
)
def test_parse_reminder_message(message: str, expect_seconds: int | None) -> None:
    now = _fixed_now()
    parsed = parse_reminder_message(message, now)
    if expect_seconds is None:
        assert parsed is None
        return
    assert parsed is not None
    remind_at = datetime.fromisoformat(parsed[1])
    assert (remind_at - now).total_seconds() == expect_seconds


def test_reminder_store_roundtrip(tmp_path) -> None:
    store = ReminderStore(tmp_path)
    reminder = Reminder(kind="memo", text="喝水", remind_at="2099-01-01T00:00:00+08:00")
    store.put(reminder)
    assert store.get(reminder.reminder_id) is not None
    assert any(item.status == "pending" for item in store.list_pending())
    assert store.delete(reminder.reminder_id) is True
    assert store.get(reminder.reminder_id) is None


def test_reminder_engine_fires_due_event(tmp_path) -> None:
    hub = FakeHub()
    store = ReminderStore(tmp_path)
    due = Reminder(kind="memo", text="喝水", remind_at="2000-01-01T00:00:00+00:00")
    store.put(due)
    engine = ReminderEngine(store, hub)
    asyncio.run(engine._sweep())
    assert len(hub.events) == 1
    assert hub.events[0]["event_type"] == "reminder.triggered"
    assert store.get(due.reminder_id).status == "done"


def test_wellness_sedentary_and_long_work(tmp_path) -> None:
    hub = FakeHub()
    wellness = WellnessEngine(
        hub,
        sedentary_minutes=1,
        long_work_minutes=1,
        cooldown_minutes=1,
    )
    wellness.ingest_activity(120)
    asyncio.run(wellness._sweep())
    assert any(item["payload"]["kind"] == "sedentary" for item in hub.events)

    hub.events.clear()
    wellness = WellnessEngine(
        hub,
        sedentary_minutes=60,
        long_work_minutes=0,
        cooldown_minutes=1,
    )
    wellness.ingest_activity(10)
    asyncio.run(wellness._sweep())
    assert any(item["payload"]["kind"] == "long_work" for item in hub.events)


def _prepare_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        """
id: default
name: 千问
kind: assistant
description: 默认角色
personality: [自然, 可靠]
backstory: ""
language: zh-CN
reply_style: 简洁
avatar: ""
""".strip(),
        encoding="utf-8",
    )


def test_reminder_api_crud(tmp_path, monkeypatch) -> None:
    _prepare_home(tmp_path, monkeypatch)
    with TestClient(create_app(load_settings())) as client:
        created = client.post(
            "/api/reminders",
            json={
                "kind": "memo",
                "text": "喝水",
                "remind_at": "2099-01-01T00:00:00+08:00",
                "repeat": "none",
            },
        ).json()["reminder"]
        reminder_id = created["reminder_id"]
        assert created["status"] == "pending"

        listed = client.get("/api/reminders").json()["items"]
        assert any(item["reminder_id"] == reminder_id for item in listed)

        updated = client.patch(f"/api/reminders/{reminder_id}", json={"status": "done"}).json()["reminder"]
        assert updated["status"] == "done"

        assert client.delete(f"/api/reminders/{reminder_id}").json()["deleted"] == reminder_id
        remaining = client.get("/api/reminders").json()["items"]
        assert not any(item["reminder_id"] == reminder_id for item in remaining)
