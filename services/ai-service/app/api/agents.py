"""Agent 探测 API。"""

from __future__ import annotations

import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agents.catalog import (
    AgentCatalog,
    add_local_executor,
    default_catalog_path,
    load_agent_catalog,
    update_local_default_executor,
    update_local_executor_config,
    update_local_executor_enabled,
)
from app.agents.factory import rebuild_agent_registry
from app.agents.registry import AgentRegistry
from app.agents.secret_store import SecretStore, SecretStoreError

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentConfigUpdate(BaseModel):
    """执行器配置更新：命令路径覆盖 + 启停 + 设为默认。"""

    command: str | None = None
    internet_environment: str | None = None  # workbuddy 专用：internal / ioa / selfhosted / null(海外)
    api_key: str | None = None              # workbuddy / acp-cli 通用：自备 API Key，空串=清除
    enabled: bool | None = None             # None = 不改启停
    set_default: bool | None = None         # True = 把该执行器设为兜底默认


class AgentLoginRequest(BaseModel):
    method_id: str
    api_key: str | None = None


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


def _api_key_configured(entry_name: str, config: dict) -> bool:
    if str(config.get(f"{entry_name}_api_key") or "").strip():
        return True
    try:
        return SecretStore().exists(entry_name)
    except SecretStoreError:
        return False


@router.get("")
async def list_agents(request: Request) -> dict:
    items = await _registry(request).detect_all()
    return {
        "items": [agent.model_dump(mode="json") for agent in items],
        "default_executor": _registry(request).default_executor,
    }


@router.get("/config")
async def agent_config(request: Request) -> dict:
    """执行器目录 + 配置。密钥只回传「是否已配置」，明文不出接口。"""
    catalog = _catalog(request)
    items: list[dict] = []
    for entry in catalog.executors:
        item = asdict(entry)
        config = dict(item.get("config") or {})
        configured = _api_key_configured(entry.name, config)
        config.pop(f"{entry.name}_api_key", None)
        item["config"] = config
        item["api_key_configured"] = configured
        items.append(item)
    return {"default_executor": catalog.default_executor, "items": items}


class CustomAgentCreate(BaseModel):
    """用户自行添加的 ACP 执行器：给启动命令就能接入。"""

    name: str
    label: str | None = None
    command: str
    api_key_env: str | None = None  # 该 CLI 读取凭据用的环境变量名
    api_key: str | None = None


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")


@router.post("/custom")
async def add_custom_agent(payload: CustomAgentCreate, request: Request) -> dict:
    """按需安装：把用户填的 ACP 执行器写进 agents.local.yaml 并立即可用。"""
    name = payload.name.strip().lower()
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="名称只能用 2-31 位小写字母、数字与连字符。")
    command = (payload.command or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="启动命令不能为空。")

    catalog = _catalog(request)
    if any(entry.name == name for entry in catalog.executors):
        raise HTTPException(status_code=409, detail=f"执行器 {name} 已存在。")

    key_env = (payload.api_key_env or "").strip()
    api_key = (payload.api_key or "").strip()
    if api_key and not key_env:
        raise HTTPException(
            status_code=400,
            detail="填了 API Key 就必须同时填「凭据环境变量名」，否则该 CLI 读不到它。",
        )
    if key_env and not _ENV_RE.match(key_env):
        raise HTTPException(status_code=400, detail="环境变量名需形如 MY_AGENT_API_KEY。")

    config: dict = {"acp_command": command}
    if key_env:
        config["api_key_env"] = key_env
    add_local_executor(
        default_catalog_path(),
        {
            "name": name,
            "label": (payload.label or name).strip(),
            "adapter": "acp-cli",
            "enabled": True,
            "commands": [command.split()[0]],
            "protocol": "acp",
            "capabilities": ["task_execution"],
            "source_url": None,
            "tags": ["custom", "acp", "cli"],
            "detail": f"用户自定义 ACP 执行器：{command}",
            "config": config,
        },
    )
    if api_key:
        update_local_executor_config(default_catalog_path(), name, {f"{name}_api_key": api_key})

    fresh = load_agent_catalog()
    rebuild_agent_registry(
        _registry(request), fresh, getattr(request.app.state, "llm_provider", None)
    )
    request.app.state.agent_catalog = fresh
    agent = await _registry(request).detect(name)
    return agent.model_dump(mode="json")


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


@router.post("/{name}/login")
async def login_agent(name: str, payload: AgentLoginRequest, request: Request) -> dict:
    adapter = _registry(request).get(name)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if name == "workbuddy":
        api_key = (payload.api_key or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先粘贴 WorkBuddy API Key。")
        validate = getattr(adapter, "validate_api_key", None)
        if not callable(validate):
            raise HTTPException(status_code=400, detail="WorkBuddy 不支持页面登录。")
        try:
            await validate(api_key)
            SecretStore().store(name, api_key)
        except SecretStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        update_local_executor_config(default_catalog_path(), name, {f"{name}_api_key": None})
        catalog = load_agent_catalog()
        rebuild_agent_registry(_registry(request), catalog, getattr(request.app.state, "llm_provider", None))
        request.app.state.agent_catalog = catalog
        agent = await _registry(request).detect(name)
        return agent.model_dump(mode="json")
    login = getattr(adapter, "authenticate", None)
    if not callable(login):
        raise HTTPException(status_code=400, detail=f"{name} 不支持页面登录。")
    try:
        await login(payload.method_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    agent = await _registry(request).detect(name)
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

    if fields & {"command", "internet_environment", "api_key"}:
        # ACP 主线：凡走 ACP 的执行器都允许填启动命令与自备凭据，
        # 厂商差异只体现在 config 的 acp_command / api_key_env。
        entry = next((item for item in _catalog(request).executors if item.name == name), None)
        adapter = entry.adapter if entry is not None else ""
        if adapter not in {"codex", "workbuddy", "acp-cli"}:
            raise HTTPException(
                status_code=400,
                detail=f"{name} 不是 ACP 执行器，暂不支持页面配置命令与凭据。",
            )
        config_updates: dict = {}
        if "command" in fields:
            command = (payload.command or "").strip() or None
            config_updates[f"{name}_command"] = command
        if name == "workbuddy" and "internet_environment" in fields:
            # 空字符串视为 null（海外模式）
            env_val = (payload.internet_environment or "").strip() or None
            config_updates["internet_environment"] = env_val
        if "api_key" in fields:
            declares_env = bool(str((entry.config or {}).get("api_key_env") or "").strip())
            if adapter not in {"workbuddy", "codex", "acp-cli"} or (
                adapter == "acp-cli" and not declares_env
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"{name} 未声明 api_key_env，请改用该 CLI 自身的登录方式。",
                )
            key = (payload.api_key or "").strip()
            if name == "workbuddy":
                if key:
                    raise HTTPException(
                        status_code=400,
                        detail="WorkBuddy API Key 必须通过登录向导完成真实探测后保存。",
                    )
                SecretStore().delete(name)
                config_updates[f"{name}_api_key"] = None
            else:
                # 空字符串视为清除：删掉后回落系统环境里已有的同名变量。
                config_updates[f"{name}_api_key"] = key or None
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
    rebuild_agent_registry(registry, catalog, getattr(request.app.state, "llm_provider", None))
    request.app.state.agent_catalog = catalog
    agent = await registry.detect(name)
    return agent.model_dump(mode="json")
