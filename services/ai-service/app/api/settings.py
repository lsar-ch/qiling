"""本地设置与角色卡接口。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from PIL import Image
from PIL import UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.config import PerformanceMode, load_settings
from app.core.persona_asset import NormalizedAvatar, normalize_avatar_image, png_bytes
from app.llm import create_provider
from app.model_profiles import (
    CATEGORY_LABELS,
    ModelProfile,
    default_profile,
    ensure_initial_profiles,
    find_model_profile,
    load_model_profiles,
    public_model_profile,
    save_model_profiles,
    test_model_profile,
)
from app.speech.factory import build_speech_stack

router = APIRouter(prefix="/api", tags=["settings"])
_PERSONA_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_AVATAR_TYPES = {
    "image/png": (".png", "PNG"),
    "image/jpeg": (".jpg", "JPEG"),
    "image/webp": (".webp", "WEBP"),
}
_MAX_AVATAR_BYTES = 15 * 1024 * 1024


class PersonaProfile(BaseModel):
    """六段式角色档案（借鉴 here：identity/personality/speech/relationship/preferences/boundaries）。

    Step 9.5 P1：MBTI 归入 personality 自由文本，不强制字段。
    各段均为可选自然语言描述；空段在生成系统提示词时跳过。
    """

    identity: str = ""        # 身份与世界认知
    personality: str = ""     # 性格特征（可含 MBTI）
    speech: str = ""          # 说话风格与措辞习惯
    relationship: str = ""    # 与用户的关系设定
    preferences: str = ""     # 喜好与工作偏好
    boundaries: str = ""      # 边界与禁忌

    model_config = {"extra": "forbid"}


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
    llm: dict[str, Any] = Field(default_factory=dict)
    profile: PersonaProfile | None = None  # 六段式档案（Step 9.5 P1；可选，旧角色卡兼容）


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


def _reload_runtime(request: Request) -> None:
    request.app.state.settings = load_settings()
    request.app.state.speech = build_speech_stack(request.app.state.settings)
    request.app.state.llm_provider = create_provider(request.app.state.settings)
    request.app.state.echo_mode = request.app.state.settings.llm_provider == "echo"
    vault = Path(request.app.state.settings.obsidian_vault_path).expanduser()
    if request.app.state.settings.memory_mode == "obsidian_linked" and vault.is_dir():
        request.app.state.memory.set_vault_mirror(vault)
    else:
        request.app.state.memory.set_vault_mirror(None)


def _persona_dir(request: Request) -> Path:
    path = request.app.state.settings.personas_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _persona_asset_dir(request: Request, persona_id: str) -> Path:
    if not _PERSONA_ID.fullmatch(persona_id):
        raise HTTPException(status_code=400, detail="角色卡 ID 不合法")
    path = request.app.state.settings.data_dir / "persona-assets" / persona_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _avatar_path(request: Request, persona_id: str) -> Path | None:
    directory = _persona_asset_dir(request, persona_id)
    for suffix in (".png", ".jpg", ".webp"):
        path = directory / f"avatar{suffix}"
        if path.is_file():
            return path
    return None


def _normalize_avatar(body: bytes, expected_format: str) -> NormalizedAvatar:
    try:
        from io import BytesIO

        with Image.open(BytesIO(body)) as image:
            if image.format != expected_format:
                raise ValueError("图片内容与文件类型不一致")
            image.load()
            return normalize_avatar_image(image.copy())
    except ValueError:
        raise
    except UnidentifiedImageError as exc:
        raise ValueError("无法读取图片") from exc
    except Exception as exc:
        raise ValueError("无法处理图片") from exc


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
async def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, Any]:
    current = _read_overrides(request)
    data = payload.model_dump(exclude_unset=True)
    switched_persona_id: str | None = None
    if "active_persona_id" in data:
        persona_path = _persona_dir(request) / f"{data['active_persona_id']}.yaml"
        if not persona_path.is_file():
            raise HTTPException(status_code=404, detail="角色卡不存在")
        switched_persona_id = data.pop("active_persona_id")
        current["active_persona_id"] = switched_persona_id
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


@router.get("/personas/{persona_id}/avatar")
def get_persona_avatar(persona_id: str, request: Request) -> Response:
    path = _avatar_path(request, persona_id)
    if path is None:
        raise HTTPException(status_code=404, detail="角色形象不存在")
    return FileResponse(path)


@router.put("/personas/{persona_id}/avatar")
async def upload_persona_avatar(persona_id: str, request: Request) -> dict[str, Any]:
    persona_path = _persona_dir(request) / f"{persona_id}.yaml"
    if not persona_path.is_file():
        raise HTTPException(status_code=404, detail="角色卡不存在")

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    metadata = _AVATAR_TYPES.get(content_type)
    if metadata is None:
        raise HTTPException(status_code=415, detail="仅支持 PNG、JPG 或 WebP 图片")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(body) > _MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="图片不能超过 15 MB")
    suffix, expected_format = metadata
    try:
        normalized = await run_in_threadpool(_normalize_avatar, body, expected_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    directory = _persona_asset_dir(request, persona_id)
    for old_suffix in (".png", ".jpg", ".webp"):
        (directory / f"original{old_suffix}").unlink(missing_ok=True)
    for old_suffix in (".jpg", ".webp"):
        (directory / f"avatar{old_suffix}").unlink(missing_ok=True)
    (directory / f"original{suffix}").write_bytes(body)
    path = directory / "avatar.png"
    normalized_body = png_bytes(normalized.image)
    path.write_bytes(normalized_body)
    output_width, output_height = normalized.image.size
    manifest = {
        "version": 2,
        "mode": "artwork",
        "main": f"/api/personas/{persona_id}/avatar",
        "width": output_width,
        "height": output_height,
        "original_width": normalized.original_size[0],
        "original_height": normalized.original_size[1],
        "content_width": normalized.content_size[0],
        "content_height": normalized.content_size[1],
        "content_bbox": list(normalized.content_bbox),
        "canvas": {
            "width": output_width,
            "height": output_height,
            "safe_margin": 48,
            "baseline": output_height - 48,
        },
        "content_type": content_type,
        "size": len(body),
        "output_size": len(normalized_body),
        "background_removed": normalized.background_removed,
        "processing": normalized.processing,
    }
    (directory / "asset-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "persona_id": persona_id,
        "avatar": f"/api/personas/{persona_id}/avatar",
        "size": len(body),
        "content_type": content_type,
        "width": output_width,
        "height": output_height,
        "background_removed": normalized.background_removed,
        "processing": normalized.processing,
    }


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
    existing = _persona_from_file(path)
    # 合并而非整体覆盖：保留前端尚未支持的字段（如 profile 六段式档案）
    merged = {**existing, **payload.model_dump(exclude_unset=True)}
    path.write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return payload.model_dump()
