"""记忆契约（对应 docs/V1-MEMORY.md）。

L2/L3/Persona 文档与条目的对外表示；内部 Markdown 文件才是真相源。
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MemoryLayer = Literal["L2", "L3", "persona"]
L3Slot = Literal["profile", "preferences", "progress", "recent"]


class MemoryEntrySummary(BaseModel):
    """单条记忆的对外表示。"""

    entry_id: str = Field(default_factory=lambda: f"m_{uuid4().hex[:8]}")
    section: str
    text: str
    refs: list[str] = Field(default_factory=list)  # 引用的 L1 trace id

    model_config = {"extra": "forbid"}


class MemorySection(BaseModel):
    """Markdown 文档中的一个小节。"""

    title: str
    entries: list[MemoryEntrySummary] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class MemoryDoc(BaseModel):
    """记忆文档的结构化表示。"""

    layer: MemoryLayer
    key: str
    title: str
    raw_markdown: str = ""
    sections: list[MemorySection] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class DocOverview(BaseModel):
    """记忆页「文档概览」条目。"""

    layer: MemoryLayer
    key: str                     # L2: surface；L3: slot；persona: 角色名
    title: str = ""
    entry_count: int = 0
    updated_at: str | None = None

    model_config = {"extra": "forbid"}


class SearchHit(BaseModel):
    """记忆检索命中。"""

    entry_id: str
    layer: MemoryLayer
    key: str
    section: str
    text: str
    refs: list[str] = Field(default_factory=list)
    score: float = 0.0

    model_config = {"extra": "forbid"}


class MemoryBlock(BaseModel):
    source: str
    text: str
    chars: int

    model_config = {"extra": "forbid"}


class CompiledMemory(BaseModel):
    built_at: str
    budget: int
    blocks: list[MemoryBlock] = Field(default_factory=list)
    text: str = ""

    model_config = {"extra": "forbid"}
