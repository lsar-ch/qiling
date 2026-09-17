"""Step 5：本地记忆管理与 Obsidian 只读检索。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.memory.service import MemoryService, read_mirror_status

router = APIRouter(prefix="/api/memories", tags=["memory"])


class EntryPayload(BaseModel):
    section: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    refs: list[str] = Field(default_factory=list)


class DocPayload(BaseModel):
    markdown: str = Field(max_length=50000)


def memory(request: Request) -> MemoryService:
    return request.app.state.memory


@router.get("/overview")
def overview(request: Request) -> dict:
    return {"items": [item.model_dump(mode="json") for item in memory(request).overview()]}


@router.get("/docs/{layer}/{key}")
def read_doc(layer: str, key: str, request: Request) -> dict:
    if layer not in ("L2", "L3", "persona"):
        raise HTTPException(status_code=400, detail="记忆层级无效")
    return memory(request).parse_doc(layer, key).model_dump(mode="json")


@router.put("/docs/{layer}/{key}")
def overwrite_doc(layer: str, key: str, payload: DocPayload, request: Request) -> dict:
    if layer not in ("L2", "L3", "persona"):
        raise HTTPException(status_code=400, detail="记忆层级无效")
    memory(request).overwrite_doc(layer, key, payload.markdown)
    return memory(request).parse_doc(layer, key).model_dump(mode="json")


@router.post("/docs/{layer}/{key}/entries")
def upsert_entry(layer: str, key: str, payload: EntryPayload, request: Request) -> dict:
    if layer not in ("L2", "L3", "persona"):
        raise HTTPException(status_code=400, detail="记忆层级无效")
    entry_id = memory(request).upsert_entry(layer, key, payload.section, payload.text, payload.refs)
    return {"entry_id": entry_id, "doc": memory(request).parse_doc(layer, key).model_dump(mode="json")}


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, request: Request) -> dict:
    deleted = memory(request).delete_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    return {"deleted": True, "entry_id": entry_id}


@router.get("/search")
def search(request: Request, q: str = Query(min_length=1, max_length=200), limit: int = Query(10, ge=1, le=50)) -> dict:
    return {"items": [item.model_dump(mode="json") for item in memory(request).search(q, limit)]}


@router.get("/vault/status")
def vault_status(request: Request) -> dict:
    settings = request.app.state.settings
    linked = settings.memory_mode == "obsidian_linked"
    raw = (settings.obsidian_vault_path or "").strip()
    if not linked or not raw:
        return {"available": False, "path": None, "mirror_dir_exists": False, "last_sync": None, "doc_files": 0}
    root = Path(raw).expanduser()
    if not root.is_dir():
        return {"available": False, "path": raw, "mirror_dir_exists": False, "last_sync": None, "doc_files": 0}
    status = read_mirror_status(root)
    return {"available": True, "path": raw, **status}


@router.get("/obsidian/check")
def obsidian_check(
    request: Request,
    path: str = Query(min_length=1, max_length=1024),
) -> dict:
    """只读检测一个 Obsidian vault 路径：不启用镜像、不写任何文件。"""
    root = Path(path.strip()).expanduser()
    if not root.is_dir():
        return {"available": False, "path": str(root), "note_count": 0}
    note_count = sum(
        1
        for note in root.rglob("*.md")
        if note.relative_to(root).parts[0] != "DeskMate"
    )
    return {"available": True, "path": str(root), "note_count": note_count}


@router.get("/sessions")
def sessions(request: Request) -> dict:
    return {"items": memory(request).list_sessions()}


@router.get("/compiled")
def compiled(request: Request) -> dict:
    result = memory(request).recall_context(
        budget_chars=request.app.state.settings.memory_budget_chars,
        persona_id=request.app.state.settings.active_persona_id,
    )
    return result.model_dump(mode="json")


@router.get("/export")
def export_bundle(request: Request) -> dict:
    mem = memory(request)
    docs = [
        mem.parse_doc(item.layer, item.key).model_dump(mode="json")
        for item in mem.overview()
    ]
    return {
        "mode": request.app.state.settings.memory_mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overview": [item.model_dump(mode="json") for item in mem.overview()],
        "compiled": mem.recall_context(
            budget_chars=request.app.state.settings.memory_budget_chars,
            persona_id=request.app.state.settings.active_persona_id,
        ).model_dump(mode="json"),
        "docs": docs,
        "sessions": mem.list_sessions(),
    }


@router.get("/obsidian/search")
def obsidian_search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    if request.app.state.settings.memory_mode != "obsidian_linked":
        return {"available": False, "path": request.app.state.settings.obsidian_vault_path, "items": []}
    root = Path(request.app.state.settings.obsidian_vault_path).expanduser()
    if not root.is_dir():
        return {"available": False, "path": str(root), "items": []}
    query = q.casefold()
    items = []
    for path in sorted(root.rglob("*.md")):
        if path.relative_to(root).parts[0] == "DeskMate":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if query not in text.casefold() and query not in path.stem.casefold():
            continue
        lines = [line.strip() for line in text.splitlines() if query in line.casefold()]
        items.append({"path": str(path.relative_to(root)), "title": path.stem, "matches": lines[:3]})
        if len(items) >= limit:
            break
    return {"available": True, "path": str(root), "items": items}
