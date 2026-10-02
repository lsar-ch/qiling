"""本地任务存储。"""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from deskmate_contracts.task import Task


class TaskStore:
    def __init__(
        self,
        root: Path,
        max_items: int = 200,
        stale_hours: float = 24.0,
    ) -> None:
        self._max_items = max_items
        self._stale_hours = stale_hours
        self._dir = root / "tasks"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items: "OrderedDict[str, Task]" = OrderedDict()
        self._load()
        self._prune_stale()

    def _load(self) -> None:
        for path in sorted(self._dir.glob("*.json")):
            try:
                task = Task.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            self._items[task.task_id] = task

    def put(self, task: Task) -> Task:
        task.updated_at = datetime.now(timezone.utc).isoformat()
        self._items[task.task_id] = task
        self._items.move_to_end(task.task_id)
        self._prune_stale()
        while len(self._items) > self._max_items:
            old_id, _ = self._items.popitem(last=False)
            old_path = self._dir / f"{old_id}.json"
            if old_path.exists():
                old_path.unlink()
        self._save(task)
        return task

    def _prune_stale(self) -> None:
        """回收长期停在 queued 的任务，避免常开监听只增不减地灌满任务台。"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._stale_hours)
        for task_id, task in list(self._items.items()):
            if task.status != "queued":
                continue
            try:
                updated = datetime.fromisoformat(task.updated_at)
            except ValueError:
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated >= cutoff:
                continue
            del self._items[task_id]
            path = self._dir / f"{task_id}.json"
            if path.exists():
                path.unlink()

    def _save(self, task: Task) -> None:
        path = self._dir / f"{task.task_id}.json"
        path.write_text(task.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, task_id: str) -> Task | None:
        task = self._items.get(task_id)
        if task is not None:
            return task
        path = self._dir / f"{task_id}.json"
        if not path.exists():
            return None
        try:
            task = Task.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None
        self._items[task.task_id] = task
        return task

    def list_recent(self, limit: int = 50) -> list[Task]:
        items = list(self._items.values())
        if len(items) < limit:
            for path in sorted(self._dir.glob("*.json")):
                if path.stem in self._items:
                    continue
                try:
                    items.append(Task.model_validate(json.loads(path.read_text(encoding="utf-8"))))
                except Exception:
                    continue
        # 最近任务台要「新的在上」，与 AgentRunStore.list_recent 一致。
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[:limit]

    def values(self) -> Iterable[Task]:
        return self._items.values()
