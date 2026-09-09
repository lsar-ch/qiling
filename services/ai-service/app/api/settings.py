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
    request.app.state.settings = load_settings()
    request.app.state.speech = build_speech_stack(request.app.state.settings)
    request.app.state.llm_provider = create_provider(request.app.state.settings)
    request.app.state.echo_mode = request.app.state.settings.llm_provider == "echo"
    vault = Path(request.app.state.settings.obsidian_vault_path).expanduser()
    if request.app.state.settings.memory_mode == "obsidian_linked" and vault.is_dir():
        request.app.state.memory.set_vault_mirror(vault)
    else:
        request.app.state.memory.set_vault_mirror(None)
    return _public_settings(request)


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
