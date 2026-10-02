"""技能扩展管理 API（P1：只读）。

启用/停用、用户新增与 MCP 端点按 docs/EXTENSION-SKELETON-PLAN.md 分期开放。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi import UploadFile, File
from pydantic import BaseModel

from app.agents import office_tools

router = APIRouter(prefix="/api", tags=["extensions"])


def _registry(request: Request):
    return request.app.state.skill_registry


@router.get("/office-tools")
def list_office_tools() -> dict:
    """办公引擎清单：探测本机是否已装，供「技能扩展」页展示与安装。"""
    try:
        tools = office_tools.list_tools()
    except office_tools.OfficeToolError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"tools": [item.model_dump(mode="json") for item in tools]}


@router.post("/office-tools/{name}/install")
def install_office_tool(name: str) -> dict:
    """按目录声明安装办公引擎（pip 类型真装；link 类型提示走下载页）。"""
    try:
        ok, message = office_tools.install(name)
        tools = office_tools.list_tools()
    except office_tools.OfficeToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": ok, "message": message, "tools": [item.model_dump(mode="json") for item in tools]}


@router.get("/skills")
def list_skills(request: Request) -> dict:
    return {"skills": [item.model_dump(mode="json") for item in _registry(request).list()]}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str, request: Request) -> dict:
    detail = _registry(request).detail(skill_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return detail.model_dump(mode="json")


class TogglePayload(BaseModel):
    enabled: bool


@router.post("/skills/{skill_id}/toggle")
def toggle_skill(skill_id: str, payload: TogglePayload, request: Request) -> dict:
    try:
        info = _registry(request).set_enabled(skill_id, payload.enabled)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return info.model_dump(mode="json")


class DirectoryPayload(BaseModel):
    path: str


@router.post("/skills/register-directory")
def register_skill_directory(payload: DirectoryPayload, request: Request) -> dict:
    try:
        info = _registry(request).register_directory(Path(payload.path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return info.model_dump(mode="json")


@router.post("/skills/upload")
async def upload_skill(request: Request, file: UploadFile = File(...)) -> dict:
    data = await file.read()
    try:
        info = _registry(request).install_zip(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return info.model_dump(mode="json")


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, request: Request) -> dict:
    try:
        _registry(request).remove(skill_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": skill_id}


# ── MCP 服务器管理 ─────────────────────────────────────────
def _mcp(request: Request):
    return request.app.state.mcp_manager


@router.get("/mcp-servers")
def list_mcp_servers(request: Request) -> dict:
    return {
        "servers": [
            item.model_dump(mode="json") for item in _mcp(request).list_servers()
        ]
    }


class McpServerPayload(BaseModel):
    id: str
    transport: str = "stdio"
    access: str = "read"
    enabled: bool = False
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None


@router.post("/mcp-servers")
def add_mcp_server(payload: McpServerPayload, request: Request) -> dict:
    try:
        _mcp(request).add_or_update_server(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": payload.id}


class McpTogglePayload(BaseModel):
    enabled: bool


@router.post("/mcp-servers/{server_id}/toggle")
async def toggle_mcp_server(
    server_id: str,
    payload: McpTogglePayload,
    request: Request,
) -> dict:
    try:
        await _mcp(request).set_enabled(server_id, payload.enabled)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": server_id, "enabled": payload.enabled}


@router.delete("/mcp-servers/{server_id}")
async def delete_mcp_server(server_id: str, request: Request) -> dict:
    try:
        await _mcp(request).remove_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": server_id}


@router.post("/mcp-servers/{server_id}/test")
async def test_mcp_server(server_id: str, request: Request) -> dict:
    try:
        tools = await _mcp(request).test_connection(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": server_id,
        "tools": [
            {"name": item.name, "description": item.description} for item in tools
        ],
    }


@router.get("/mcp-servers/{server_id}/tools")
async def get_mcp_tools(server_id: str, request: Request) -> dict:
    try:
        tools = await _mcp(request).list_tools(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": server_id,
        "tools": [
            {
                "name": item.name,
                "description": item.description,
                "input_schema": item.input_schema,
            }
            for item in tools
        ],
    }


class ToolApprovalPayload(BaseModel):
    decision: str  # approved | rejected


@router.post("/mcp-tool-approvals/{approval_id}")
async def decide_tool_approval(
    approval_id: str,
    payload: ToolApprovalPayload,
    request: Request,
) -> dict:
    """复用 awaiting_approval 语义：对话内 MCP 写类工具调用在此授权。"""
    pending = getattr(request.app.state, "tool_approvals", {})
    future = pending.get(approval_id)
    if future is None:
        raise HTTPException(status_code=404, detail="审批不存在或已超时")
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision 只能是 approved/rejected")
    if not future.done():
        future.set_result(payload.decision)
    return {"approval_id": approval_id, "decision": payload.decision}
