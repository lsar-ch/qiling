"""本地工作台便签与待办存储。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from qiling_contracts.workbench import WorkbenchNote, WorkbenchTodo

Item = TypeVar("Item", WorkbenchNote, WorkbenchTodo)
_ID_PATTERN = re.compile(r"^(note|todo)_[a-f0-9]{12}$")


class WorkbenchDataStore:
    def __init__(self, root: Path, model: type[Item], id_field: str, max_items: int = 500) -> None:
        self._id_field = id_field
        self._max_items = max_items
        self._dir = root / "workbench" / f"{id_field.removesuffix('_id')}s"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, Item] = {}
        for path in sorted(self._dir.glob("*.json")):
            try:
                item = model.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            self._items[getattr(item, id_field)] = item

    def get(self, item_id: str) -> Item | None:
        if not _ID_PATTERN.fullmatch(item_id):
            return None
        return self._items.get(item_id)

    def list_recent(self, limit: int = 100) -> list[Item]:
        return sorted(self._items.values(), key=lambda item: item.updated_at, reverse=True)[:limit]

    def put(self, item: Item) -> Item:
        item_id = getattr(item, self._id_field)
        if not _ID_PATTERN.fullmatch(item_id):
            raise ValueError("工作台数据 ID 不合法")
        if item_id not in self._items and len(self._items) >= self._max_items:
            raise ValueError("工作台条目数量已达上限")
        item.updated_at = datetime.now(timezone.utc).isoformat()
        (self._dir / f"{item_id}.json").write_text(
            item.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._items[item_id] = item
        return item

    def delete(self, item_id: str) -> bool:
        if not _ID_PATTERN.fullmatch(item_id):
            return False
        item = self._items.pop(item_id, None)
        path = self._dir / f"{item_id}.json"
        existed = item is not None or path.is_file()
        path.unlink(missing_ok=True)
        return existed


def new_workbench_stores(root: Path) -> tuple[WorkbenchDataStore, WorkbenchDataStore]:
    return (
        WorkbenchDataStore(root, WorkbenchNote, "note_id"),
        WorkbenchDataStore(root, WorkbenchTodo, "todo_id"),
    )
