"""久坐 / 长时间工作提醒引擎。

桌面挂件定时上报系统空闲秒数（widget.activity），本模块据此判断：
- sedentary：连续空闲达到阈值，提醒起身活动；
- long_work：连续活跃工作达到阈值，提醒休息。
冷却期内不重复提醒。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from qiling_contracts.events import EventEnvelope

logger = logging.getLogger(__name__)

_ACTIVE_IDLE_SECONDS = 120.0


class WellnessEngine:
    def __init__(
        self,
        hub,
        *,
        enabled: bool = True,
        sedentary_minutes: int = 40,
        long_work_minutes: int = 90,
        cooldown_minutes: int = 30,
    ) -> None:
        self._hub = hub
        self._enabled = enabled
        self._sedentary_seconds = max(0, sedentary_minutes) * 60
        self._long_work_seconds = max(0, long_work_minutes) * 60
        self._cooldown_seconds = max(1, cooldown_minutes) * 60
        self._idle_seconds = 0.0
        self._work_started_at: datetime | None = None
        self._last_reminded: dict[str, datetime] = {}

    def ingest_activity(self, idle_seconds: float) -> None:
        self._idle_seconds = max(0.0, idle_seconds)
        now = datetime.now(timezone.utc)
        if idle_seconds < _ACTIVE_IDLE_SECONDS:
            if self._work_started_at is None:
                self._work_started_at = now
        else:
            self._work_started_at = None

    def start(self, interval_s: float = 30.0) -> None:
        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval_s)
                try:
                    await self._sweep()
                except Exception:
                    logger.exception("wellness sweep failed")

        asyncio.create_task(_loop())

    async def _sweep(self) -> None:
        if not self._enabled:
            return
        now = datetime.now(timezone.utc)
        if self._idle_seconds >= self._sedentary_seconds:
            await self._maybe_fire("sedentary", now, "坐得有点久啦，起来活动一下，喝口水吧。")
            return
        if self._work_started_at is not None:
            elapsed = (now - self._work_started_at).total_seconds()
            if elapsed >= self._long_work_seconds:
                await self._maybe_fire("long_work", now, "已经连续工作很久了，休息几分钟再继续吧。")

    async def _maybe_fire(self, kind: str, now: datetime, message: str) -> None:
        last = self._last_reminded.get(kind)
        if last is not None and (now - last).total_seconds() < self._cooldown_seconds:
            return
        self._last_reminded[kind] = now
        await self._hub.publish(
            EventEnvelope(
                event_type="reminder.triggered",  # type: ignore[arg-type]
                source="system",
                payload={
                    "kind": kind,
                    "bubble": message,
                    "speak_text": message,
                },
            )
        )
        if kind == "long_work":
            self._work_started_at = now
