"""
记忆检索器：语义搜索 + 历史上下文组装。

参考 Soul-of-Waifu 四级记忆架构，实现：
1. 短期上下文（最近对话）
2. 长期检索（语义相似度搜索）
3. 摘要注入（大段历史的压缩表示）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryContext:
    """组装好的对话上下文。"""
    recent_messages: list[dict]       # 最近 N 条对话
    relevant_memories: list[dict]     # 语义检索到的相关记忆
    summaries: list[dict]             # 历史摘要
    user_profile: dict[str, Any]      # 用户画像（可扩展）

    def to_messages(self, llm_client=None) -> list[dict]:
        """转换为 LLM 可用的消息列表。"""
        messages = []

        # 注入摘要作为上下文
        for summary in self.summaries:
            messages.append({
                "role": "system",
                "content": f"[历史摘要] {summary['summary']}（覆盖约 {summary['covers']} 条消息）",
            })

        # 注入相关记忆
        for mem in self.relevant_memories:
            messages.append({
                "role": "system",
                "content": f"[相关记忆] {mem['content']}",
            })

        # 最近对话
        for msg in self.recent_messages:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        return messages


class MemoryRetriever:
    """记忆检索器。"""

    def __init__(self, store, embedding_model: str | None = None):
        self.store = store
        self.embedding_model = embedding_model
        self._embedder = None

    def _get_embedder(self):
        """延迟加载嵌入模型。"""
        if self._embedder is not None:
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer
            model_name = self.embedding_model or "all-MiniLM-L6-v2"
            self._embedder = SentenceTransformer(model_name)
            logger.info(f"Embedding model loaded: {model_name}")
        except ImportError:
            logger.warning("sentence-transformers not installed, semantic search disabled")
        return self._embedder

    def retrieve_context(
        self,
        query: str,
        recent_limit: int = 10,
        memory_limit: int = 3,
    ) -> MemoryContext:
        """检索与当前查询相关的记忆上下文。"""
        # 1. 获取最近对话
        recent = self.store.get_recent(limit=recent_limit)

        # 2. 获取历史摘要
        summaries = self.store.get_summaries(limit=5)

        # 3. 语义检索（如果嵌入模型可用）
        relevant = []
        embedder = self._get_embedder()
        if embedder is not None:
            relevant = self._semantic_search(query, limit=memory_limit)

        return MemoryContext(
            recent_messages=recent,
            relevant_memories=relevant,
            summaries=summaries,
            user_profile={},
        )

    def _semantic_search(self, query: str, limit: int = 3) -> list[dict]:
        """基于语义相似度的记忆检索。"""
        import numpy as np
        conn = self.store._get_conn()
        embedder = self._get_embedder()

        # 获取所有消息（简化版，生产环境应做分页和向量索引）
        rows = conn.execute(
            "SELECT content, timestamp FROM conversations ORDER BY timestamp DESC LIMIT 200"
        ).fetchall()

        if not rows:
            return []

        # 计算嵌入
        texts = [row["content"] for row in rows]
        query_emb = embedder.encode([query])[0]
        docs_emb = embedder.encode(texts)

        # 余弦相似度
        similarities = np.dot(docs_emb, query_emb) / (
            np.linalg.norm(docs_emb, axis=1) * np.linalg.norm(query_emb)
        )

        # 取 top-k
        top_indices = np.argsort(similarities)[::-1][:limit]
        results = []
        for idx in top_indices:
            if similarities[idx] > 0.3:  # 相似度阈值
                row = rows[idx]
                results.append({
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "similarity": float(similarities[idx]),
                })

        logger.debug(f"Semantic search: {len(results)} results for '{query[:30]}...'")
        return results
