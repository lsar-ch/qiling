"""Agent 探测 API。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agents.catalog import (
    AgentCatalog,
    default_catalog_path,
    load_agent_catalog,
    update_local_default_executor,
    update_local_executor_config,
    update_local_executor_enabled,
)
from app.agents.factory import rebuild_agent_registry
from app.agents.registry import AgentRegistry

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentConfigUpdate(BaseModel):
    """执行器配置更新：命令路径覆盖 + 启停 + 设为默认。"""

    command: str | None = None
    internet_environment: str | None = None  # workbuddy 专用：internal / ioa / selfhosted / null(海外)
    enabled: bool | None = None             # None = 不改启停
    set_default: bool | None = None         # True = 把该执行器设为兜底默认


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.agent_registry


def _catalog(request: Request) -> AgentCatalog:
    return request.app.state.agent_catalog


def _can_be_default(registry: AgentRegistry, name: str) -> bool:
    """能否当兜底默认：既要能真实执行，也要不是窄场景执行器。"""
    adapter = registry.get(name)
    if adapter is None:
        return False
    return bool(adapter.executable and getattr(adapter, "default_eligible", True))


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


@router.post("/{name}/refresh")
async def refresh_agent(name: str, request: Request) -> dict:
    registry = _registry(request)
    adapter = registry.get(name)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    invalidate = getattr(adapter, "invalidate_probe", None)
    if callable(invalidate):
        invalidate()
    agent = await registry.detect(name)
    return agent.model_dump(mode="json")


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
    catalog_path = default_catalog_path()
    fields = payload.model_fields_set

    if fields & {"command", "internet_environment"}:
        if name not in {"codex", "workbuddy"}:
            raise HTTPException(
                status_code=400,
                detail="当前仅 codex 与 workbuddy 支持页面配置命令路径；其余执行器将在后续版本开放。",
            )
        config_updates: dict = {}
        if "command" in fields:
            command = (payload.command or "").strip() or None
            config_updates[f"{name}_command"] = command
        if name == "workbuddy" and "internet_environment" in fields:
            # 空字符串视为 null（海外模式）
            env_val = (payload.internet_environment or "").strip() or None
            config_updates["internet_environment"] = env_val
        update_local_executor_config(catalog_path, name, config_updates)

    if payload.enabled is not None:
        if not payload.enabled and load_agent_catalog().default_executor == name:
            raise HTTPException(
                status_code=400,
                detail=f"{name} 是当前默认执行器，请先切换默认再停用。",
            )
        update_local_executor_enabled(catalog_path, name, payload.enabled)

    if payload.set_default:
        entry = next(
            (item for item in load_agent_catalog().executors if item.name == name),
            None,
        )
        if entry is None or not entry.enabled:
            raise HTTPException(
                status_code=400,
                detail=f"{name} 已停用，不能设为默认执行器。",
            )
        if not _can_be_default(registry, name):
            raise HTTPException(
                status_code=400,
                detail=f"{name} 尚未接入真实执行，不能设为默认执行器。",
            )
        update_local_default_executor(catalog_path, name)

    catalog = load_agent_catalog()
    rebuild_agent_registry(registry, catalog)
    request.app.state.agent_catalog = catalog
    agent = await registry.detect(name)
    return agent.model_dump(mode="json")
