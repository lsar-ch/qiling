"""Agent 探测 API。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agents.catalog import (
    AgentCatalog,
    default_catalog_path,
    load_agent_catalog,
    update_local_executor_config,
)
from app.agents.factory import rebuild_agent_registry
from app.agents.registry import AgentRegistry

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentConfigUpdate(BaseModel):
    """执行器配置更新（最小版：codex 命令/路径覆盖）。"""

    command: str | None = None


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.agent_registry


def _catalog(request: Request) -> AgentCatalog:
    return request.app.state.agent_catalog


@router.get("")
async def list_agents(request: Request) -> dict:
    items = await _registry(request).detect_all()
    return {
        "items": [agent.model_dump(mode="json") for agent in items],
        "default_executor": _registry(request).default_executor,
    }


@router.get("/config")
async def agent_config(request: Request) -> dict:
    catalog = _catalog(request)
    return {
        "default_executor": catalog.default_executor,
        "items": [asdict(entry) for entry in catalog.executors],
    }


@router.get("/{name}")
async def get_agent(name: str, request: Request) -> dict:
    registry = _registry(request)
    if registry.get(name) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    agent = await registry.detect(name)
    return agent.model_dump(mode="json")


@router.put("/{name}/config")
async def update_agent_config(name: str, payload: AgentConfigUpdate, request: Request) -> dict:
    registry = _registry(request)
    if registry.get(name) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if name != "codex":
        raise HTTPException(
            status_code=400,
            detail="当前仅 codex 支持页面配置；其余执行器将在后续版本开放。",
        )
    command = (payload.command or "").strip() or None
    update_local_executor_config(default_catalog_path(), name, {"codex_command": command})
    catalog = load_agent_catalog()
    rebuild_agent_registry(registry, catalog)
    request.app.state.agent_catalog = catalog
    agent = await registry.detect(name)
    return agent.model_dump(mode="json")
