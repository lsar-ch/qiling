"""Markdown/JSONL 本地记忆实现。

V1 以文件为真相源：L1 事件写 JSONL，L2/L3/persona 写 Markdown；检索索引可重建。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from qiling_contracts.memory import (
    CompiledMemory,
    DocOverview,
    MemoryBlock,
    MemoryDoc,
    MemoryEntrySummary,
    MemoryLayer,
    MemorySection,
    SearchHit,
)

SURFACES = ("conversation", "task", "kb", "project", "partner")
L3_SLOTS = ("profile", "preferences", "progress", "recent")
ENTRY_RE = re.compile(r"^-\s+(?P<text>.*?)\s*<!--(?P<id>m_[A-Za-z0-9_\-]+)-->")
REF_RE = re.compile(r"\[\^(?P<n>\d+)\]")
FOOTNOTE_RE = re.compile(r"^\[\^(?P<n>\d+)\]:\s*(?P<ref>.+)$")
MIRROR_TS_RE = re.compile(r"更新时间[:：]\s*(.+?)\s*$")

MIRROR_ROOT_NAME = "栖灵"
MIRROR_DIR_NAME = "记忆"
MIRROR_ARCHIVE_DIR = "档案"
MIRROR_SNAPSHOT_DIR = "快照"
MIRROR_README_FILE = "README.md"
MIRROR_SNAPSHOT_FILE = "记忆快照.md"


def mirror_dir_for(vault_root: Path | None) -> Path | None:
    """把 vault 根目录映射到 栖灵 写入镜像目录；根无效时返回 None。"""
    if vault_root is None:
        return None
    root = Path(vault_root).expanduser()
    if not root.is_dir():
        return None
    return root / MIRROR_ROOT_NAME / MIRROR_DIR_NAME


def _atomic_write(path: Path, text: str) -> None:
    """原子写入（同目录临时文件 + replace），失败清理临时文件并上抛。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".qiling-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_mirror_status(vault_root: Path | None) -> dict:
    """读取镜像目录磁盘状态（无副作用、容错）。"""
    mirror = mirror_dir_for(vault_root)
    if mirror is None or not mirror.is_dir():
        return {"mirror_dir_exists": False, "last_sync": None, "doc_files": 0}
    last_sync = None
    try:
        readme = mirror / MIRROR_README_FILE
        if readme.is_file():
            text = readme.read_text(encoding="utf-8")
            match = MIRROR_TS_RE.search(text)
            if match:
                last_sync = match.group(1)
        docs = [
            p
            for p in mirror.rglob("*.md")
            if not (p.parent == mirror and p.name == MIRROR_README_FILE)
        ]
        if last_sync is None and docs:
            newest = max(p.stat().st_mtime for p in docs)
            last_sync = datetime.fromtimestamp(newest, timezone.utc).isoformat()
    except OSError:
        return {"mirror_dir_exists": True, "last_sync": last_sync, "doc_files": 0}
    return {"mirror_dir_exists": True, "last_sync": last_sync, "doc_files": len(docs)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _title_for(layer: str, key: str) -> str:
    titles = {
        "conversation": "对话事实",
        "task": "任务事实",
        "kb": "知识库事实",
        "project": "项目进度与决策",
        "partner": "角色互动事实",
        "profile": "用户画像",
        "preferences": "用户偏好",
        "progress": "项目进度",
        "recent": "近期上下文",
    }
    if layer == "persona":
        return f"角色档案：{key}"
    return titles.get(key, key)


class MemoryService:
    def __init__(self, root: Path, *, persona_dir: Path | None = None) -> None:
        self.root = root
        self.persona_dir = persona_dir
        self._vault_mirror_root: Path | None = None
        self.root.mkdir(parents=True, exist_ok=True)
        for surface in SURFACES:
            (self.root / "trace" / surface).mkdir(parents=True, exist_ok=True)
        for folder in ("L2", "L3", "persona", "session", "compiled", "meta"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()
        self.rebuild_index()

    def _ensure_defaults(self) -> None:
        for surface in SURFACES:
            self._doc_path("L2", surface).touch(exist_ok=True)
            path = self._doc_path("L2", surface)
            if path.stat().st_size == 0:
                path.write_text(f"# {_title_for('L2', surface)}\n\n", encoding="utf-8")
        for slot in L3_SLOTS:
            self._doc_path("L3", slot).touch(exist_ok=True)
            path = self._doc_path("L3", slot)
            if path.stat().st_size == 0:
                path.write_text(f"# {_title_for('L3', slot)}\n\n", encoding="utf-8")

    def _doc_path(self, layer: str, key: str) -> Path:
        safe = key.replace("/", "_")
        if layer == "L2":
            return self.root / "L2" / f"{safe}.md"
        if layer == "L3":
            return self.root / "L3" / f"{safe}.md"
        if layer == "persona":
            return self.root / "persona" / f"{safe}.md"
        raise ValueError(f"unknown memory layer: {layer}")

    def _read_text(self, layer: str, key: str) -> str:
        path = self._doc_path(layer, key)
        if not path.exists():
            return f"# {_title_for(layer, key)}\n\n"
        return path.read_text(encoding="utf-8")

    def _write_text(self, layer: str, key: str, text: str) -> None:
        path = self._doc_path(layer, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text.rstrip() + "\n", encoding="utf-8")
        tmp.replace(path)
        self.rebuild_index()
        self._sync_vault_mirror(only=(layer, key))

    def parse_doc(self, layer: str, key: str) -> MemoryDoc:
        raw = self._read_text(layer, key)
        lines = raw.splitlines()
        title = _title_for(layer, key)
        footnotes: dict[str, str] = {}
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip() or title
            match = FOOTNOTE_RE.match(line.strip())
            if match:
                footnotes[match.group("n")] = match.group("ref").strip()

        sections: list[MemorySection] = []
        current: MemorySection | None = None
        for line in lines:
            if line.startswith("## "):
                current = MemorySection(title=line[3:].strip(), entries=[])
                sections.append(current)
                continue
            match = ENTRY_RE.match(line.strip())
            if match:
                if current is None:
                    current = MemorySection(title="默认", entries=[])
                    sections.append(current)
                ref_ids = [footnotes[n] for n in REF_RE.findall(match.group("text")) if n in footnotes]
                clean_text = REF_RE.sub("", match.group("text")).strip()
                current.entries.append(
                    MemoryEntrySummary(
                        entry_id=match.group("id"),
                        section=current.title,
                        text=clean_text,
                        refs=ref_ids,
                    )
                )
        return MemoryDoc(layer=layer, key=key, title=title, raw_markdown=raw, sections=sections)

    def overview(self) -> list[DocOverview]:
        items: list[DocOverview] = []
        for layer, keys in (("L3", L3_SLOTS), ("L2", SURFACES)):
            for key in keys:
                path = self._doc_path(layer, key)
                doc = self.parse_doc(layer, key)
                items.append(
                    DocOverview(
                        layer=layer,
                        key=key,
                        title=doc.title,
                        entry_count=sum(len(s.entries) for s in doc.sections),
                        updated_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                        if path.exists()
                        else None,
                    )
                )
        for path in sorted((self.root / "persona").glob("*.md")):
            key = path.stem
            doc = self.parse_doc("persona", key)
            items.append(
                DocOverview(
                    layer="persona",
                    key=key,
                    title=doc.title,
                    entry_count=sum(len(s.entries) for s in doc.sections),
                    updated_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                )
            )
        return items

    def record_event(
        self,
        surface: str,
        kind: str,
        payload: dict,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> str:
        if surface not in SURFACES:
            raise ValueError(f"unknown memory surface: {surface}")
        trace_id = f"{surface}:evt_{uuid4().hex[:12]}"
        item = {
            "id": trace_id,
            "ts": _now(),
            "surface": surface,
            "kind": kind,
            "payload": payload,
            "session_id": session_id,
            "turn_id": turn_id,
        }
        path = self.root / "trace" / surface / f"{_date()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._sync_vault_mirror(rewrite_archives=False)
        return trace_id

    def upsert_entry(self, layer: str, key: str, section: str, text: str, refs: list[str]) -> str:
        doc = self.parse_doc(layer, key)
        normalized = " ".join(text.split()).strip()
        for sec in doc.sections:
            for entry in sec.entries:
                if sec.title == section and " ".join(entry.text.split()).strip() == normalized:
                    merged = list(dict.fromkeys([*entry.refs, *refs]))
                    if merged != entry.refs:
                        self._replace_entry_refs(layer, key, entry.entry_id, merged)
                    return entry.entry_id

        raw = doc.raw_markdown.rstrip() or f"# {_title_for(layer, key)}"
        lines = raw.splitlines()
        section_idx = next((i for i, line in enumerate(lines) if line.strip() == f"## {section}"), None)
        if section_idx is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend([f"## {section}"])
            section_idx = len(lines) - 1
        insert_at = len(lines)
        for i in range(section_idx + 1, len(lines)):
            if lines[i].startswith("## ") or lines[i].startswith("[^1]:"):
                insert_at = i
                break
        entry_id = f"m_{uuid4().hex[:10]}"
        ref_tokens, footnotes = self._make_footnotes(lines, refs)
        lines.insert(insert_at, f"- {text.strip()} {ref_tokens} <!--{entry_id}-->")
        if footnotes:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(footnotes)
        self._write_text(layer, key, "\n".join(lines))
        return entry_id

    def _make_footnotes(self, lines: list[str], refs: list[str]) -> tuple[str, list[str]]:
        existing: dict[str, str] = {}
        max_n = 0
        for line in lines:
            match = FOOTNOTE_RE.match(line.strip())
            if match:
                existing[match.group("ref")] = match.group("n")
                max_n = max(max_n, int(match.group("n")))
        tokens: list[str] = []
        footnotes: list[str] = []
        for ref in refs:
            if not ref:
                continue
            n = existing.get(ref)
            if n is None:
                max_n += 1
                n = str(max_n)
                existing[ref] = n
                footnotes.append(f"[^{n}]: {ref}")
            tokens.append(f"[^{n}]")
        return "".join(tokens), footnotes

    def _replace_entry_refs(self, layer: str, key: str, entry_id: str, refs: list[str]) -> None:
        doc = self.parse_doc(layer, key)
        target = next((e for s in doc.sections for e in s.entries if e.entry_id == entry_id), None)
        if target is None:
            return
        lines = [line for line in doc.raw_markdown.splitlines() if not FOOTNOTE_RE.match(line.strip())]
        ref_tokens, footnotes = self._make_footnotes(lines, refs)
        for idx, line in enumerate(lines):
            if f"<!--{entry_id}-->" in line:
                lines[idx] = f"- {target.text} {ref_tokens} <!--{entry_id}-->"
                break
        if footnotes:
            lines.append("")
            lines.extend(footnotes)
        self._write_text(layer, key, "\n".join(lines))

    def overwrite_doc(self, layer: str, key: str, markdown: str) -> None:
        self._write_text(layer, key, markdown)

    def delete_entry(self, entry_id: str) -> bool:
        for overview in self.overview():
            doc = self.parse_doc(overview.layer, overview.key)
            if not any(entry.entry_id == entry_id for sec in doc.sections for entry in sec.entries):
                continue
            lines = [line for line in doc.raw_markdown.splitlines() if f"<!--{entry_id}-->" not in line]
            used = set()
            for line in lines:
                used.update(REF_RE.findall(line))
            lines = [line for line in lines if not (FOOTNOTE_RE.match(line.strip()) and FOOTNOTE_RE.match(line.strip()).group("n") not in used)]
            self._write_text(overview.layer, overview.key, "\n".join(lines))
            return True
        return False

    def write_session_summary(self, conversation_id: str, user_text: str, assistant_text: str) -> None:
        path = self.root / "session" / f"{_date()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {_date()} 会话纪要\n\n", encoding="utf-8")
        snippet = assistant_text.strip().replace("\n", " ")[:180]
        user = user_text.strip().replace("\n", " ")[:120]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"## {datetime.now().strftime('%H:%M')} · {conversation_id}\n")
            fh.write(f"- 用户：{user}\n")
            fh.write(f"- 结果：{snippet}\n\n")

    def list_sessions(self, limit: int = 20) -> list[dict]:
        items = []
        for path in sorted((self.root / "session").glob("*.md"), reverse=True)[:limit]:
            items.append({"date": path.stem, "markdown": path.read_text(encoding="utf-8")})
        return items

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        q = query.strip().lower()
        if not q:
            return []
        hits: list[SearchHit] = []
        for overview in self.overview():
            doc = self.parse_doc(overview.layer, overview.key)
            for section in doc.sections:
                for entry in section.entries:
                    text = entry.text.lower()
                    score = 0.0
                    if q in text:
                        score += 10
                    score += sum(1 for token in re.split(r"\s+", q) if token and token in text)
                    if score <= 0 and any(ch in text for ch in q if "\u4e00" <= ch <= "\u9fff"):
                        score = 1
                    if score > 0:
                        hits.append(
                            SearchHit(
                                entry_id=entry.entry_id,
                                layer=overview.layer,
                                key=overview.key,
                                section=section.title,
                                text=entry.text,
                                refs=entry.refs,
                                score=score,
                            )
                        )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def recall_context(
        self,
        *,
        query: str = "",
        budget_chars: int = 4000,
        surfaces: list[str] | None = None,
        persona_id: str | None = None,
    ) -> CompiledMemory:
        blocks: list[MemoryBlock] = []

        persona_text = self._persona_context(persona_id)
        self._append_block(blocks, "persona", persona_text, budget_chars)
        for slot in ("profile", "preferences", "progress", "recent"):
            self._append_block(blocks, f"L3.{slot}", self._doc_plain_text("L3", slot), budget_chars)
        for surface in surfaces or ["conversation", "project"]:
            self._append_block(blocks, f"L2.{surface}", self._doc_plain_text("L2", surface), budget_chars)
        sessions = self.list_sessions(limit=1)
        if sessions:
            self._append_block(blocks, "session", sessions[0]["markdown"], budget_chars)
        if query.strip():
            search_text = "\n".join(f"- {hit.text}" for hit in self.search(query, limit=5))
            self._append_block(blocks, "search", search_text, budget_chars)

        text_parts: list[str] = []
        used = 0
        kept: list[MemoryBlock] = []
        for block in blocks:
            if not block.text.strip():
                continue
            remain = budget_chars - used
            if remain <= 0:
                break
            block_text = block.text.strip()
            if len(block_text) > remain:
                block_text = block_text[:remain].rstrip()
            kept_block = MemoryBlock(source=block.source, text=block_text, chars=len(block_text))
            kept.append(kept_block)
            text_parts.append(f"## {block.source}\n{block_text}")
            used += len(block_text)
        compiled_text = "\n\n".join(text_parts).strip()
        compiled = CompiledMemory(built_at=_now(), budget=budget_chars, blocks=kept, text=compiled_text)
        path = self.root / "compiled" / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(compiled_text + ("\n" if compiled_text else ""), encoding="utf-8")
        return compiled

    def _append_block(self, blocks: list[MemoryBlock], source: str, text: str, budget: int) -> None:
        stripped = text.strip()
        if stripped:
            blocks.append(MemoryBlock(source=source, text=stripped[:budget], chars=len(stripped[:budget])))

    def _doc_plain_text(self, layer: str, key: str) -> str:
        doc = self.parse_doc(layer, key)
        lines: list[str] = []
        for section in doc.sections:
            for entry in section.entries:
                lines.append(f"- {section.title}：{entry.text}")
        return "\n".join(lines)

    def _persona_context(self, persona_id: str | None) -> str:
        if not persona_id or self.persona_dir is None:
            return ""
        path = self.persona_dir / f"{persona_id}.yaml"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return ""
        parts = [
            f"名称：{data.get('name', '')}",
            f"类型：{data.get('kind', '')}",
            f"简介：{data.get('description', '')}",
            "性格：" + "、".join(str(x) for x in data.get("personality", []) if str(x).strip()),
            f"回复风格：{data.get('reply_style', '')}",
        ]
        backstory = str(data.get("backstory") or "").strip()
        if backstory:
            parts.append(f"背景：{backstory[:500]}")
        return "\n".join(p for p in parts if p.split("：", 1)[-1].strip())

    def rebuild_index(self) -> None:
        path = self.root / "index.db"
        with sqlite3.connect(path) as conn:
            conn.execute(
                "create table if not exists memory_entries "
                "(entry_id text primary key, layer text, key text, section text, text text, refs text)"
            )
            conn.execute("delete from memory_entries")
            for layer, keys in (("L2", SURFACES), ("L3", L3_SLOTS), ("persona", tuple(p.stem for p in (self.root / "persona").glob("*.md")))):
                for key in keys:
                    doc = self.parse_doc(layer, key)
                    for section in doc.sections:
                        for entry in section.entries:
                            conn.execute(
                                "insert or replace into memory_entries values (?, ?, ?, ?, ?, ?)",
                                (entry.entry_id, layer, key, section.title, entry.text, json.dumps(entry.refs, ensure_ascii=False)),
                            )
            conn.commit()

    def set_vault_mirror(self, vault_root: Path | None) -> None:
        """启用/停用 vault 写入镜像；有效目录启用并立即全量同步，任何失败静默降级。"""
        self._vault_mirror_root = None
        if vault_root is None:
            return
        mirror = mirror_dir_for(vault_root)
        if mirror is None:
            return
        try:
            mirror.mkdir(parents=True, exist_ok=True)
            self._vault_mirror_root = mirror
            self._sync_vault_mirror()
        except OSError:
            self._vault_mirror_root = None

    def _sync_vault_mirror(self, *, only: tuple[str, str] | None = None, rewrite_archives: bool = True) -> bool:
        """把本地记忆增量镜像到 vault。异常静默吞掉，返回是否成功。"""
        mirror = self._vault_mirror_root
        if mirror is None:
            return True
        try:
            archive_dir = mirror / MIRROR_ARCHIVE_DIR
            snapshot_dir = mirror / MIRROR_SNAPSHOT_DIR
            archive_dir.mkdir(parents=True, exist_ok=True)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            if rewrite_archives:
                if only is not None:
                    layer, key = only
                    archive_paths = [(archive_dir / f"{self._mirror_filename(layer, key)}.md", self._read_text(layer, key))]
                else:
                    archive_paths = [
                        (archive_dir / f"{self._mirror_filename(layer, key)}.md", self._read_text(layer, key))
                        for layer, key in self._mirror_docs()
                    ]
                for path, text in archive_paths:
                    _atomic_write(path, text)
            _atomic_write(snapshot_dir / MIRROR_SNAPSHOT_FILE, self._mirror_snapshot_text())
            _atomic_write(mirror / MIRROR_README_FILE, self._mirror_readme_text())
            return True
        except OSError:
            return False

    def _mirror_docs(self) -> list[tuple[str, str]]:
        docs: list[tuple[str, str]] = []
        for layer, keys in (
            ("L2", SURFACES),
            ("L3", L3_SLOTS),
            ("persona", sorted(p.stem for p in (self.root / "persona").glob("*.md"))),
        ):
            docs.extend((layer, key) for key in keys)
        return docs

    def _mirror_filename(self, layer: str, key: str) -> str:
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", key).strip(" .") or "_"
        return f"{layer}-{safe}"

    def _mirror_snapshot_text(self) -> str:
        parts = ["# 记忆快照", "", f"> 生成时间：{_now()}（UTC）", ""]
        for layer, key in self._mirror_docs():
            doc = self.parse_doc(layer, key)
            lines = doc.raw_markdown.splitlines()
            if lines and lines[0].startswith("# "):
                lines = lines[1:]
            parts.append(f"## {doc.title}（{layer} · {key}）")
            parts.append("")
            body = "\n".join(lines).strip("\n")
            if body:
                parts.append(body)
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def _mirror_readme_text(self) -> str:
        return "\n".join(
            [
                "# 栖灵 记忆镜像",
                "",
                "本目录由 栖灵 自动维护：将本地记忆（L2/L3/persona）整理为只读镜像副本。",
                "请勿手动编辑本目录；本地记忆变化后会自动增量同步，本地删除不会改动此副本。",
                "",
                f"更新时间：{_now()}",
                "",
            ]
        )
