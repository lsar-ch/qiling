"""会话持久化：data/conversations/<id>.json（原子写入）。

Step 7 接入记忆后，会话内容会再沉淀到 L1 trace / session 摘要。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from deskmate_contracts.conversation import Conversation, ConversationMessage


class ConversationStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "conversations"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
        self._dir_lock = asyncio.Lock()

    def _lock_for(self, conversation_id: str) -> asyncio.Lock:
        lock = self._locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[conversation_id] = lock
        return lock

    def _path(self, conversation_id: str) -> Path:
        return self._dir / f"{conversation_id}.json"

    async def _read(self, conversation_id: str) -> Conversation | None:
        path = self._path(conversation_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Conversation.model_validate(data)
        except Exception:
            return None

    async def _atomic_write(self, conversation: Conversation) -> None:
        path = self._path(conversation.conversation_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            conversation.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    async def get(self, conversation_id: str) -> Conversation | None:
        async with self._dir_lock:
            return await self._read(conversation_id)

    async def list_recent(self, limit: int = 30) -> list[Conversation]:
        items: list[Conversation] = []
        for path in self._dir.glob("*.json"):
            if path.name.endswith(".json.tmp"):
                continue
            try:
                conv = Conversation.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue
            items.append(conv)
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return items[:limit]

    async def append_message(
        self,
        conversation_id: str | None,
        role: str,
        content: str,
        *,
        modality: str = "text",
        model_profile_id: str | None = None,
    ) -> Conversation:
        conversation_id = conversation_id or ""
        async with self._lock_for(conversation_id):
            conversation = (
                await self._read(conversation_id) if conversation_id else None
            )
            now = datetime.now(timezone.utc).isoformat()
            if conversation is None:
                conversation = Conversation(
                    title=(content[:24] + ("…" if len(content) > 24 else ""))
                    if role == "user"
                    else "新对话",
                    created_at=now,
                    updated_at=now,
                )
                conversation_id = conversation.conversation_id
            if model_profile_id is not None:
                conversation.model_profile_id = model_profile_id or None
            conversation.messages.append(
                ConversationMessage(
                    role=role,  # type: ignore[arg-type]
                    content=content,
                    modality=modality,
                    created_at=now,
                )
            )
            conversation.updated_at = now
            await self._atomic_write(conversation)
            return conversation
