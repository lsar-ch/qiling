"""
记忆存储：SQLite + 向量索引。

参考 Soul-of-Waifu 的四级记忆架构：
1. 心理状态（当前情绪/偏好）
2. 关系档案（用户画像）
3. 事件归档（对话历史）
4. 个人日记（重要事件笔记）
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryStore:
    """对话记忆存储。"""

    def __init__(self, db_path: str = "./data/memory/chat_history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()
        logger.info(f"MemoryStore initialized: {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                embedding_id TEXT
            );

            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                summary TEXT NOT NULL,
                covers_messages INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp);
            CREATE INDEX IF NOT EXISTS idx_conversations_role ON conversations(role);
        """)
        conn.commit()
        logger.debug("Database schema initialized")

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> int:
        """添加一条对话消息。"""
        conn = self._get_conn()
        meta = json.dumps(metadata or {}, ensure_ascii=False)
        cur = conn.execute(
            """INSERT INTO conversations (timestamp, role, content, metadata)
               VALUES (?, ?, ?, ?)""",
            (datetime.now().isoformat(), role, content, meta),
        )
        conn.commit()
        msg_id = cur.lastrowid
        logger.debug(f"Added message #{msg_id}: [{role}] {content[:50]}...")
        return msg_id

    def add_summary(self, summary: str, covers: int = 10) -> None:
        """添加对话摘要。"""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO summaries (created_at, summary, covers_messages)
               VALUES (?, ?, ?)""",
            (datetime.now().isoformat(), summary, covers),
        )
        conn.commit()
        logger.debug(f"Added summary covering {covers} messages")

    def get_recent(
        self,
        limit: int = 20,
        role_filter: str | None = None,
    ) -> list[dict]:
        """获取最近的对话消息。"""
        conn = self._get_conn()
        if role_filter:
            rows = conn.execute(
                """SELECT role, content, metadata, timestamp
                   FROM conversations
                   WHERE role = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (role_filter, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT role, content, metadata, timestamp
                   FROM conversations
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "timestamp": row["timestamp"],
            }
            for row in rows
        ][::-1]  # 按时间正序返回

    def get_summaries(self, limit: int = 5) -> list[dict]:
        """获取最近的对话摘要。"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT summary, covers_messages, created_at
               FROM summaries
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "summary": row["summary"],
                "covers": row["covers_messages"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def cleanup_old(self, retention_days: int = 90) -> int:
        """清理过期消息。"""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        cur = conn.execute(
            "DELETE FROM conversations WHERE timestamp < ?",
            (cutoff,),
        )
        conn.commit()
        deleted = cur.rowcount
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old messages (>{retention_days} days)")
        return deleted

    def get_stats(self) -> dict:
        """获取记忆库统计信息。"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE timestamp LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        return {
            "total_messages": total,
            "today_messages": today_count,
            "db_path": str(self.db_path),
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
