"""本地设置与角色卡接口。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import PerformanceMode, load_settings
from app.llm import create_provider
from app.speech.factory import build_speech_stack

router = APIRouter(prefix="/api", tags=["settings"])


class PersonaPayload(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=40)
    kind: str = "assistant"
    description: str = ""
    personality: list[str] = Field(default_factory=list)
    backstory: str = ""
    language: str = "zh-CN"
    reply_style: str = ""
    avatar: str = ""
    voice: dict[str, Any] = Field(default_factory=dict)
    activation: dict[str, Any] = Field(default_factory=dict)


class SettingsUpdate(BaseModel):
    active_persona_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$")
    ui_language: str | None = None
    ui_theme: str | None = None
    permission_level: str | None = None
    memory_mode: str | None = None
    performance_mode: PerformanceMode | None = None
    obsidian_vault_path: str | None = None
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    voice_enabled: bool | None = None
    activation_enabled: bool | None = None
    activation_default_state: str | None = None
    voice_speed: float | None = Field(default=None, ge=0.5, le=2.0)
    voice_pitch: float | None = Field(default=None, ge=0.5, le=2.0)
    voice_volume: float | None = Field(default=None, ge=0.0, le=2.0)
    voice_emotion: str | None = None
    voice_instruction: str | None = None
    dashscope_api_key: str | None = None
    minimax_api_key: str | None = None


def _settings_path(request: Request) -> Path:
    return request.app.state.settings.local_settings_path


def _read_overrides(request: Request) -> dict[str, Any]:
    path = _settings_path(request)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_overrides(request: Request, value: dict[str, Any]) -> None:
    path = _settings_path(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _persona_dir(request: Request) -> Path:
    path = request.app.state.settings.personas_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _persona_from_file(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _public_settings(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "active_persona_id": settings.active_persona_id,
        "performance_mode": settings.performance_mode,
        "ui": {"language": settings.ui_language, "theme": settings.ui_theme},
        "permission_level": settings.permission_level,
        "memory": {
            "mode": settings.memory_mode,
            "budget_chars": settings.memory_budget_chars,
            "obsidian_vault_path": settings.obsidian_vault_path,
            "obsidian_configured": settings.memory_mode == "obsidian_linked"
            and Path(settings.obsidian_vault_path).expanduser().is_dir(),
        },
        "llm": {
            "provider": settings.llm_provider,
            "base_url": settings.llm_base_url or "",
            "model": settings.llm_model,
            "api_key_configured": bool(settings.llm_api_key),
        },
        "voice": {
            "enabled": settings.voice_enabled,
            "stt_provider": settings.stt_provider,
            "stt_model": settings.stt_model,
            "tts_provider": settings.tts_provider,
            "tts_model": settings.tts_model,
            "tts_voice": settings.tts_voice,
            "speed": settings.voice_speed,
            "pitch": settings.voice_pitch,
            "volume": settings.voice_volume,
            "emotion": settings.voice_emotion or "",
            "instruction": settings.voice_instruction or "",
            "activation_enabled": settings.activation_enabled,
            "activation_default_state": settings.activation_default_state,
            "interruption_enabled": settings.interruption_enabled,
            "auto_barge_in": settings.auto_barge_in,
            "dashscope_configured": bool(settings.dashscope_api_key),
            "minimax_configured": bool(settings.minimax_api_key),
        },
    }


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return _public_settings(request)


@router.put("/settings")
def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, Any]:
    current = _read_overrides(request)
    data = payload.model_dump(exclude_unset=True)
    if "active_persona_id" in data:
        persona_path = _persona_dir(request) / f"{data['active_persona_id']}.yaml"
        if not persona_path.is_file():
            raise HTTPException(status_code=404, detail="角色卡不存在")
        current["active_persona_id"] = data.pop("active_persona_id")
    ui = current.setdefault("ui", {})
    for key in ("ui_language", "ui_theme"):
        if key in data:
            ui[key.removeprefix("ui_")] = data.pop(key)
    for key in (
        "permission_level",
        "performance_mode",
        "llm_provider",
        "llm_base_url",
        "llm_model",
        "llm_api_key",
        "voice_enabled",
        "activation_enabled",
        "activation_default_state",
        "voice_speed",
        "voice_pitch",
        "voice_volume",
        "voice_emotion",
        "voice_instruction",
        "dashscope_api_key",
        "minimax_api_key",
    ):
        if key in data:
            current[key] = data[key]
    memory = current.setdefault("memory", {})
    for key in ("memory_mode", "obsidian_vault_path"):
        if key in data:
            memory[key.removeprefix("memory_")] = data[key]
    _write_overrides(request, current)
    _reload_runtime(request)
    # Step 9.5: 角色切换后广播 PersonaPresentation
    if switched_persona_id is not None:
        await request.app.state.presentation_bridge.broadcast(
            switched_persona_id,
            request.app.state.event_hub,
        )
    return _public_settings(request)


@router.get("/model-profiles")
def list_model_profiles(request: Request) -> dict[str, Any]:
    root = request.app.state.settings.repo_root
    profiles = ensure_initial_profiles(root, request.app.state.settings)
    _reload_runtime(request)
    return {
        "items": [public_model_profile(profile) for profile in profiles],
        "categories": [
            {"id": category, "label": label}
            for category, label in CATEGORY_LABELS.items()
        ],
    }


@router.post("/model-profiles")
def create_model_profile(payload: ModelProfile, request: Request) -> dict[str, Any]:
    root = request.app.state.settings.repo_root
    profiles = load_model_profiles(root)
    if find_model_profile(profiles, payload.id) is not None:
        raise HTTPException(status_code=409, detail="模型档案 ID 已存在")
    if payload.is_default and payload.enabled:
        profiles = [
            profile.model_copy(update={"is_default": False})
            if profile.category == payload.category
            else profile
            for profile in profiles
        ]
    elif not payload.enabled:
        payload = payload.model_copy(update={"is_default": False})
    if payload.enabled and not any(
        profile.category == payload.category and profile.enabled and profile.is_default
        for profile in profiles
    ):
        payload = payload.model_copy(update={"is_default": True})
    profiles.append(payload)
    save_model_profiles(root, profiles)
    _reload_runtime(request)
    return public_model_profile(payload)


@router.put("/model-profiles/{profile_id}")
def update_model_profile(
    profile_id: str,
    payload: ModelProfile,
    request: Request,
) -> dict[str, Any]:
    if payload.id != profile_id:
        raise HTTPException(status_code=400, detail="模型档案 ID 不一致")
    root = request.app.state.settings.repo_root
    profiles = load_model_profiles(root)
    existing = find_model_profile(profiles, profile_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="模型档案不存在")
    if "api_key" not in payload.model_fields_set:
        payload = payload.model_copy(update={"api_key": existing.api_key})
    if not payload.enabled:
        payload = payload.model_copy(update={"is_default": False})
    if payload.is_default:
        profiles = [
            profile.model_copy(update={"is_default": False})
            if profile.category == payload.category and profile.id != profile_id
            else profile
            for profile in profiles
        ]
    profiles = [payload if profile.id == profile_id else profile for profile in profiles]
    if not any(
        profile.category == payload.category and profile.enabled and profile.is_default
        for profile in profiles
    ):
        replacement = next(
            (profile for profile in profiles if profile.category == payload.category and profile.enabled),
            None,
        )
        if replacement is not None:
            profiles = [
                profile.model_copy(update={"is_default": True})
                if profile.id == replacement.id
                else profile.model_copy(update={"is_default": False})
                if profile.category == payload.category
                else profile
                for profile in profiles
            ]
    save_model_profiles(root, profiles)
    _reload_runtime(request)
    saved = find_model_profile(profiles, profile_id)
    assert saved is not None
    return public_model_profile(saved)


@router.delete("/model-profiles/{profile_id}")
def delete_model_profile(profile_id: str, request: Request) -> dict[str, Any]:
    root = request.app.state.settings.repo_root
    profiles = load_model_profiles(root)
    existing = find_model_profile(profiles, profile_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="模型档案不存在")
    for path in _persona_dir(request).glob("*.yaml"):
        persona = _persona_from_file(path)
        llm = persona.get("llm") if isinstance(persona.get("llm"), dict) else {}
        if llm.get("profile_id") == profile_id:
            raise HTTPException(status_code=409, detail=f"角色「{persona.get('name') or path.stem}」正在使用该模型档案")
    profiles = [profile for profile in profiles if profile.id != profile_id]
    if existing.is_default and not default_profile(profiles, (existing.category,)):
        replacement = next(
            (profile for profile in profiles if profile.category == existing.category and profile.enabled),
            None,
        )
        if replacement is not None:
            profiles = [
                profile.model_copy(update={"is_default": True})
                if profile.id == replacement.id
                else profile
                for profile in profiles
            ]
    save_model_profiles(root, profiles)
    _reload_runtime(request)
    return {"deleted": True, "profile_id": profile_id}


@router.post("/model-profiles/{profile_id}/test")
async def test_saved_model_profile(profile_id: str, request: Request) -> dict[str, Any]:
    profiles = load_model_profiles(request.app.state.settings.repo_root)
    profile = find_model_profile(profiles, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型档案不存在")
    return await test_model_profile(profile, request.app.state.settings.llm_api_key)


@router.get("/personas")
def list_personas(request: Request) -> dict[str, Any]:
    items = []
    for path in sorted(_persona_dir(request).glob("*.yaml")):
        persona = _persona_from_file(path)
        if persona:
            items.append(persona)
    return {"items": items}


@router.post("/personas")
def create_persona(payload: PersonaPayload, request: Request) -> dict[str, Any]:
    path = _persona_dir(request) / f"{payload.id}.yaml"
    if path.exists():
        raise HTTPException(status_code=409, detail="角色卡已存在")
    path.write_text(
        yaml.safe_dump(payload.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return payload.model_dump()


@router.put("/personas/{persona_id}")
def update_persona(persona_id: str, payload: PersonaPayload, request: Request) -> dict[str, Any]:
    if persona_id != payload.id:
        raise HTTPException(status_code=400, detail="角色卡 ID 不一致")
    path = _persona_dir(request) / f"{persona_id}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="角色卡不存在")
    path.write_text(
        yaml.safe_dump(payload.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return payload.model_dump()
