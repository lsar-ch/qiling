"""项目节点本地存储。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from qiling_contracts.project import ProjectNode


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectNodeStore:
    def __init__(self, root: Path, max_items: int = 500) -> None:
        self._max_items = max_items
        self._dir = root / "project_nodes"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, ProjectNode] = {}
        self._load()

    def _load(self) -> None:
        for path in sorted(self._dir.glob("*.json")):
            try:
                node = ProjectNode.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            self._items[node.node_id] = node

    def put(self, node: ProjectNode) -> ProjectNode:
        node.updated_at = _now()
        self._items[node.node_id] = node
        while len(self._items) > self._max_items:
            oldest = min(self._items.values(), key=lambda item: item.updated_at)
            self._items.pop(oldest.node_id, None)
            (self._dir / f"{oldest.node_id}.json").unlink(missing_ok=True)
        (self._dir / f"{node.node_id}.json").write_text(
            node.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return node

    def get(self, node_id: str) -> ProjectNode | None:
        return self._items.get(node_id)

    def list_project(self, project: str) -> list[ProjectNode]:
        return sorted(
            (node for node in self._items.values() if node.project == project),
            key=lambda node: (node.created_at, node.node_id),
        )

    def summary(self, project: str) -> str:
        """项目进度摘要，供对话上下文继承；无节点返回空串。"""
        nodes = self.list_project(project)
        if not nodes:
            return ""
        done = sum(1 for n in nodes if n.status == "completed")
        lines = [f"进度：{done}/{len(nodes)} 节点已完成"]
        for n in nodes:
            if n.status == "in_progress":
                lines.append(f"进行中：{n.title}")
            elif n.status == "blocked":
                lines.append(f"阻塞：{n.title}（{n.blocker or '原因待查'}）")
        nxt = next(
            (n.next_step for n in nodes if n.status in ("in_progress", "planned") and n.next_step),
            None,
        )
        if nxt:
            lines.append(f"下一步：{nxt}")
        for n in [x for x in nodes if x.kind == "decision"][-3:]:
            lines.append(f"决策：{n.title}")
        return "\n".join(lines)

    def delete(self, node_id: str) -> bool:
        node = self._items.pop(node_id, None)
        if node is None:
            return False
        (self._dir / f"{node_id}.json").unlink(missing_ok=True)
        return True
