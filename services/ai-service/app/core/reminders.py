"""主动提醒：备忘录/任务提醒的存储、解析与调度。

- 规则解析只处理明确时间短语，避免误报；复杂语义后续再上 LLM 抽取。
- 到点后发布 reminder.triggered，由挂件气泡 + 语音消费。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.reminder import Reminder, ReminderRepeat

logger = logging.getLogger(__name__)

_REPEAT_DELTAS: dict[ReminderRepeat, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

_MINUTE_PATTERN = re.compile(r"(\d{1,3})\s*分钟(?:后|以后)?")
_HOUR_PATTERN = re.compile(r"(\d{1,2})\s*小时(?:后|以后)?")
_TOMORROW_PATTERN = re.compile(r"明天(?:早上|上午|中午|下午|晚上)?\s*(\d{1,2})[:：](\d{1,2})?")
_TODAY_PATTERN = re.compile(r"今天(?:早上|上午|中午|下午|晚上)?\s*(\d{1,2})[:：](\d{1,2})?")
_CLOCK_PATTERN = re.compile(r"(?:^|[^\d])(\d{1,2})[:：](\d{2})(?:[^\d]|$)")


def _local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _combine_time(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def parse_reminder_message(message: str, now: datetime | None = None) -> tuple[str, str] | None:
    """从用户消息提取「文本, ISO 提醒时间」；提取不到返回 None。"""
    text = message.strip()
    if not text or not any(keyword in text for keyword in ("提醒", "记得")):
        return None
    now = now or _local_now()
    hour_match = _HOUR_PATTERN.search(text)
    if hour_match:
        remind_at = now + timedelta(hours=int(hour_match.group(1)))
        return text[:500], remind_at.isoformat(timespec="seconds")
    minute_match = _MINUTE_PATTERN.search(text)
    if minute_match:
        remind_at = now + timedelta(minutes=int(minute_match.group(1)))
        return text[:500], remind_at.isoformat(timespec="seconds")
    tomorrow = _TOMORROW_PATTERN.search(text)
    if tomorrow:
        hour = int(tomorrow.group(1))
        minute = int(tomorrow.group(2) or "0")
        remind_at = _combine_time(now + timedelta(days=1), hour, minute)
        return text[:500], remind_at.isoformat(timespec="seconds")
    today = _TODAY_PATTERN.search(text)
    if today:
        hour = int(today.group(1))
        minute = int(today.group(2) or "0")
        remind_at = _combine_time(now, hour, minute)
        if remind_at <= now:
            remind_at += timedelta(days=1)
        return text[:500], remind_at.isoformat(timespec="seconds")
    clock = _CLOCK_PATTERN.search(text)
    if clock and ("今天" in text or "提醒" in text or "记得" in text):
        hour = int(clock.group(1))
        minute = int(clock.group(2))
        remind_at = _combine_time(now, hour, minute)
        if remind_at <= now:
            remind_at += timedelta(days=1)
        return text[:500], remind_at.isoformat(timespec="seconds")
    return None


class ReminderStore:
    """提醒持久化：每提醒一个 JSON 文件，与 TaskStore 同风格。"""

    def __init__(self, root: Path, max_items: int = 200) -> None:
        self._max_items = max_items
        self._dir = root / "reminders"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items: "OrderedDict[str, Reminder]" = OrderedDict()
        self._load()

    def _load(self) -> None:
        for path in sorted(self._dir.glob("*.json")):
            try:
                reminder = Reminder.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            self._items[reminder.reminder_id] = reminder

    def _save(self, reminder: Reminder) -> None:
        path = self._dir / f"{reminder.reminder_id}.json"
        path.write_text(reminder.model_dump_json(indent=2), encoding="utf-8")

    def put(self, reminder: Reminder) -> Reminder:
        reminder.updated_at = datetime.now(timezone.utc).isoformat()
        self._items[reminder.reminder_id] = reminder
        self._items.move_to_end(reminder.reminder_id)
        while len(self._items) > self._max_items:
            old_id, _ = self._items.popitem(last=False)
            (self._dir / f"{old_id}.json").unlink(missing_ok=True)
        self._save(reminder)
        return reminder

    def get(self, reminder_id: str) -> Reminder | None:
        reminder = self._items.get(reminder_id)
        if reminder is not None:
            return reminder
        path = self._dir / f"{reminder_id}.json"
        if not path.is_file():
            return None
        try:
            reminder = Reminder.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None
        self._items[reminder.reminder_id] = reminder
        return reminder

    def delete(self, reminder_id: str) -> bool:
        reminder = self._items.pop(reminder_id, None)
        path = self._dir / f"{reminder_id}.json"
        existed = reminder is not None or path.is_file()
        path.unlink(missing_ok=True)
        return existed

    def list_pending(self, limit: int = 200) -> list[Reminder]:
        return [
            reminder
            for reminder in self._items.values()
            if reminder.status == "pending"
        ][:limit]

    def list_recent(self, limit: int = 50) -> list[Reminder]:
        items = list(self._items.values())
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]


class ReminderEngine:
    """后台轮询：到点触发提醒，重复提醒自动顺延。"""

    def __init__(self, store: ReminderStore, hub) -> None:
        self._store = store
        self._hub = hub

    def start(self, interval_s: float = 15.0) -> None:
        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval_s)
                try:
                    await self._sweep()
                except Exception:
                    logger.exception("reminder sweep failed")

        asyncio.create_task(_loop())

    async def _sweep(self) -> None:
        now = datetime.now(timezone.utc)
        for reminder in self._store.list_pending():
            try:
                remind_at = datetime.fromisoformat(reminder.remind_at)
            except ValueError:
                continue
            if remind_at.timestamp() > now.timestamp():
                continue
            await self._fire(reminder)

    async def _fire(self, reminder: Reminder) -> None:
        bubble = f"⏰ 提醒：{reminder.text}"
        speak_text = f"提醒你一下，{reminder.text}"
        await self._hub.publish(
            EventEnvelope(
                event_type="reminder.triggered",  # type: ignore[arg-type]
                source="system",
                payload={
                    "kind": reminder.kind,
                    "reminder_id": reminder.reminder_id,
                    "text": reminder.text,
                    "bubble": bubble,
                    "speak_text": speak_text,
                },
            )
        )
        if reminder.repeat != "none":
            delta = _REPEAT_DELTAS.get(reminder.repeat)
            if delta is not None:
                remind_at = datetime.fromisoformat(reminder.remind_at) + delta
                reminder.remind_at = remind_at.isoformat(timespec="seconds")
                self._store.put(reminder)
                return
        reminder.status = "done"
        self._store.put(reminder)
