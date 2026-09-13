"""进程内事件总线（Step 1/2 实现）。

- WS /api/events 向前端/挂件广播 EventEnvelope。
- 新订阅者会先收到最近 H 条历史事件（重连恢复）。
- 可选 on_publish 钩子（如更新挂件状态注册表）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from deskmate_contracts.events import EventEnvelope

logger = logging.getLogger(__name__)

_QUEUE_MAX = 200
_HISTORY_MAX = 50


class EventHub:
    def __init__(
        self,
        on_publish: Callable[[EventEnvelope], None] | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._subscribers: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._next_id = 0
        self._history: list[dict[str, Any]] = []
        self._on_publish = on_publish

    async def subscribe(self) -> tuple[int, asyncio.Queue[dict[str, Any]]]:
        async with self._lock:
            self._next_id += 1
            sub_id = self._next_id
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
            self._subscribers[sub_id] = queue
            for item in list(self._history):
                if queue.full():
                    break
                queue.put_nowait(item)
            return sub_id, queue

    async def unsubscribe(self, sub_id: int) -> None:
        async with self._lock:
            self._subscribers.pop(sub_id, None)

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        """返回最近 limit 条已广播事件（按时间从新到旧），供健康检查展示。"""
        return list(reversed(self._history[-limit:]))

    async def publish(self, envelope: EventEnvelope) -> None:
        """分发给所有订阅者；队列满丢弃最旧；写入历史；触发状态钩子。

        钩子必须先于序列化执行：expression / presentation 由钩子在发布时补全，
        若先序列化再跑钩子，广播出去的载荷会缺少这些字段。
        """
        if self._on_publish is not None:
            try:
                self._on_publish(envelope)
            except Exception:  # 状态钩子失败不影响广播
                logger.exception("widget state hook failed")
        data = envelope.to_ws_dict()
        async with self._lock:
            self._history.append(data)
            if len(self._history) > _HISTORY_MAX:
                self._history = self._history[-_HISTORY_MAX:]
            subs = list(self._subscribers.values())
        for queue in subs:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning("event queue full, dropped %s", envelope.event_type)
