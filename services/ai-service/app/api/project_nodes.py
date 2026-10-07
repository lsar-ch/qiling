"""项目节点 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from qiling_contracts.project import ProjectNode, ProjectNodeKind, ProjectNodeStatus

from app.api.chat import resolve_project_dir

router = APIRouter(prefix="/api/projects", tags=["project-nodes"])


class ProjectNodePayload(BaseModel):
    project: str = Field(min_length=1, max_length=4096)
    title: str = Field(min_length=1, max_length=200)
    kind: ProjectNodeKind = "node"
    status: ProjectNodeStatus = "planned"
    parent_id: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    decision: str | None = None
    blocker: str | None = None
    next_step: str | None = None
    source: str | None = None


def _project_path(value: str) -> str:
    resolved = resolve_project_dir(value)
    if resolved is None:
        raise HTTPException(status_code=400, detail="项目目录不存在或不是目录")
    return str(resolved)


@router.get("/nodes")
def list_nodes(project: str, request: Request) -> dict:
    return {
        "items": [
            node.model_dump(mode="json")
            for node in request.app.state.project_node_store.list_project(_project_path(project))
        ]
    }


@router.post("/nodes")
def create_node(payload: ProjectNodePayload, request: Request) -> dict:
    node = ProjectNode(project=_project_path(payload.project), **payload.model_dump(exclude={"project"}))
    request.app.state.project_node_store.put(node)
    return node.model_dump(mode="json")


@router.put("/nodes/{node_id}")
def update_node(node_id: str, payload: ProjectNodePayload, request: Request) -> dict:
    existing = request.app.state.project_node_store.get(node_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="项目节点不存在")
    project = _project_path(payload.project)
    if project != existing.project:
        raise HTTPException(status_code=400, detail="不能跨项目移动节点")
    node = ProjectNode(
        node_id=node_id,
        project=project,
        created_at=existing.created_at,
        **payload.model_dump(exclude={"project"}),
    )
    request.app.state.project_node_store.put(node)
    return node.model_dump(mode="json")


@router.delete("/nodes/{node_id}")
def delete_node(node_id: str, request: Request) -> dict:
    if not request.app.state.project_node_store.delete(node_id):
        raise HTTPException(status_code=404, detail="项目节点不存在")
    return {"deleted": True, "node_id": node_id}
