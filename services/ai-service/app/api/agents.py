"""Agent 探测 API。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from app.agents.catalog import AgentCatalog
from app.agents.registry import AgentRegistry

router = APIRouter(prefix="/api/agents", tags=["agents"])


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
