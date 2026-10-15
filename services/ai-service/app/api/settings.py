"""本地设置与角色卡接口。"""

from __future__ import annotations

import json
import re
import io
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from PIL import Image
from PIL import UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from qiling_contracts.events import EventEnvelope

from app.config import PerformanceMode, is_lite_mode, load_settings, obsidian_vault_dir
from app.core.persona_asset import NormalizedAvatar, normalize_avatar_image, png_bytes
from app.core.vrm_validator import validate_vrm, validate_vrma
from app.agents.factory import rebuild_agent_registry
from app.llm import create_provider
from app.model_profiles import (
    CATEGORY_LABELS,
    ModelProfile,
    default_profile,
    ensure_initial_profiles,
    find_model_profile,
    list_provider_models,
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
    catchphrases: list[str] = Field(default_factory=list)  # 口头禅
    flaws: list[str] = Field(default_factory=list)         # 缺点/反差
    likes: list[str] = Field(default_factory=list)         # 喜好清单
    dislikes: list[str] = Field(default_factory=list)      # 不喜清单

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
    preset: Literal["work", "companion", "service"] | None = None  # 预设底座；为空时只使用自定义档案
    motion_family: Literal["human", "animal", "anime"] | None = None  # 动作族：human | animal | anime
    art_style: Literal["realistic", "anime", "chibi", "pixel"] | None = None  # 画风，动作选择不依赖


class MotionsPayload(BaseModel):
    """动作实验室调参产物：2D 动作覆盖 + 3D VRMA 播放参数。"""

    actions: dict[str, dict[str, list[dict[str, Any]]]] | None = None
    vrm: dict[str, Any] | None = None
    # presentation.animations：调度节奏（idle 轮询间隔、过渡、呼吸/眨眼）。
    animations: dict[str, Any] | None = None


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
    voice_auto_speak: bool | None = None
    activation_enabled: bool | None = None
    activation_default_state: str | None = None
    voice_speed: float | None = Field(default=None, ge=0.5, le=2.0)
    voice_pitch: float | None = Field(default=None, ge=0.5, le=2.0)
    voice_volume: float | None = Field(default=None, ge=0.0, le=2.0)
    voice_emotion: str | None = None
    voice_instruction: str | None = None
    dashscope_api_key: str | None = None
    minimax_api_key: str | None = None
    setup_completed: bool | None = None


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
    # 换模型后让内置办公执行器立刻用上新 provider（就地重建，保留 registry 引用）
    rebuild_agent_registry(
        request.app.state.agent_registry,
        request.app.state.agent_catalog,
        request.app.state.llm_provider,
    )
    vault = obsidian_vault_dir(request.app.state.settings.obsidian_vault_path)
    if request.app.state.settings.memory_mode == "obsidian_linked" and vault is not None:
        request.app.state.memory.set_vault_mirror(vault)
    else:
        request.app.state.memory.set_vault_mirror(None)


def _voice_active(request: Request) -> bool:
    """语音当前是否真正可用。

    刻意与挂件侧的判据保持同源，避免两边漂移 ——
    Widget.tsx:1308 `if (!voiceStatus?.enabled || voiceStatus.activation?.enabled === false) → 停下监听`。
    其中 voice/status.enabled 来自 SpeechStack.voice_enabled（STT/TTS provider 均可用，
    未配云 key 时为 False），activation 来自设置项。
    """
    return bool(
        request.app.state.speech.voice_enabled
        and request.app.state.settings.activation_enabled
        and not is_lite_mode(request.app.state.settings)
    )


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


def _resolve_persona_asset(directory: Path, file_path: str) -> Path | None:
    """把角色资产目录内的相对路径解析成真实文件，拒绝越权读取。"""
    raw = file_path.replace("\\", "/").strip("/")
    if not raw or ".." in raw.split("/"):
        return None
    target = (directory / raw).resolve()
    try:
        target.relative_to(directory.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


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


def _setup_completed(request: Request) -> bool:
    return bool(_read_overrides(request).get("setup_completed", False))


def _public_settings(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "setup_completed": _setup_completed(request),
        "active_persona_id": settings.active_persona_id,
        "performance_mode": settings.performance_mode,
        "ui": {"language": settings.ui_language, "theme": settings.ui_theme},
        "permission_level": settings.permission_level,
        "memory": {
            "mode": settings.memory_mode,
            "budget_chars": settings.memory_budget_chars,
            "obsidian_vault_path": settings.obsidian_vault_path,
            "obsidian_default_path": settings.obsidian_default_path,
            "obsidian_configured": settings.memory_mode == "obsidian_linked"
            and obsidian_vault_dir(settings.obsidian_vault_path) is not None,
        },
        "llm": {
            "provider": settings.llm_provider,
            "base_url": settings.llm_base_url or "",
            "model": settings.llm_model,
            "api_key_configured": bool(settings.llm_api_key),
        },
        "voice": {
            "enabled": settings.voice_enabled,
            "auto_speak": settings.voice_auto_speak,
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
    llm = current.setdefault("llm", {})
    if not isinstance(llm, dict):
        llm = {}
        current["llm"] = llm
    for key in ("llm_provider", "llm_base_url", "llm_model", "llm_api_key"):
        if key in data:
            llm[key.removeprefix("llm_")] = data.pop(key)
    for key in (
        "permission_level",
        "performance_mode",
        "voice_enabled",
        "voice_auto_speak",
        "activation_enabled",
        "activation_default_state",
        "voice_speed",
        "voice_pitch",
        "voice_volume",
        "voice_emotion",
        "voice_instruction",
        "dashscope_api_key",
        "minimax_api_key",
        "setup_completed",
    ):
        if key in data:
            current[key] = data[key]
    memory = current.setdefault("memory", {})
    for key in ("memory_mode", "obsidian_vault_path"):
        if key in data:
            memory[key.removeprefix("memory_")] = data[key]
    voice_was_active = _voice_active(request)
    _write_overrides(request, current)
    _reload_runtime(request)
    # 语音由「可用」变为「不可用」（关总开关 / 关语音激活 / 移除云 key / 进轻量模式）时补发 speech.stopped。
    # 挂件自身是按 voice/status 渲染的，但挂件状态注册表只由事件推动：
    # 不补发会残留关闭前的 listening 快照，读 /api/widget/state 与实际不符。
    # 只在下降沿补发，避免每次保存设置都刷一条事件。
    if voice_was_active and not _voice_active(request):
        await request.app.state.event_hub.publish(
            EventEnvelope(
                event_type="speech.stopped",
                source="speech",
                payload={"reason": "voice_disabled_by_settings"},
            )
        )
    # Step 9.5: 角色切换后广播 PersonaPresentation
    if switched_persona_id is not None:
        await request.app.state.presentation_bridge.broadcast(
            switched_persona_id,
            request.app.state.event_hub,
        )
    return _public_settings(request)



@router.get("/setup/status")
def setup_status(request: Request) -> dict[str, Any]:
    """首次启动引导状态：是否已完成 + 还缺哪些关键配置。

    missing 只列影响核心可用的项（LLM 必填；语音可选）。
    复用 resolve_llm_provider 判断 LLM 是否真正配置，而非只看 key 是否存在。
    """
    from app.config import resolve_llm_provider

    settings = request.app.state.settings
    completed = _setup_completed(request)
    missing: list[str] = []
    if resolve_llm_provider(settings) == "echo":
        missing.append("llm")
    return {
        "completed": completed,
        "missing": missing,
        "llm_configured": resolve_llm_provider(settings) != "echo",
        "voice_configured": bool(settings.dashscope_api_key or settings.minimax_api_key),
    }


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


@router.get("/model-profiles/models")
async def list_models_for_profile(
    request: Request,
    base_url: str = "",
    api_key: str = "",
    profile_id: str = "",
) -> dict[str, Any]:
    """拉取供应商的可用模型列表，供设置页「模型名称」做下拉选择。

    优先用请求里带的 base_url / api_key（编辑态可能还没保存）；
    只传 profile_id 时退回该档案已存的地址与 Key。
    只读查询，不写配置。
    """
    settings = request.app.state.settings
    resolved_url = base_url.strip()
    resolved_key = api_key.strip()
    if profile_id:
        profile = find_model_profile(load_model_profiles(settings.repo_root), profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="模型档案不存在")
        resolved_url = resolved_url or profile.base_url
        resolved_key = resolved_key or (profile.api_key or "")
    return await list_provider_models(resolved_url, resolved_key, settings.llm_api_key)


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


@router.get("/personas/{persona_id}/asset-manifest")
def get_persona_asset_manifest(persona_id: str, request: Request) -> dict[str, Any]:
    """归一化后的素材清单。

    桌面挂件靠 `content_bbox` 推算贴边隐藏时该保留多少像素，
    避免把「某一版立绘的透明边距」写死成常量。
    """
    directory = _persona_asset_dir(request, persona_id)
    path = directory / "asset-manifest.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="角色素材清单不存在")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="角色素材清单不可读") from exc
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=500, detail="角色素材清单格式异常")
    return manifest


@router.get("/personas/{persona_id}/asset/{file_path:path}")
@router.head("/personas/{persona_id}/asset/{file_path:path}")
def get_persona_asset_file(persona_id: str, file_path: str, request: Request) -> Response:
    """角色资产目录内的文件（layers.json / layers/*.png 等），禁止路径穿越。"""
    directory = _persona_asset_dir(request, persona_id)
    target = _resolve_persona_asset(directory, file_path)
    if target is None:
        raise HTTPException(status_code=404, detail="角色资产不存在")
    return FileResponse(target)


@router.get("/motion-library/{variant}")
def list_motion_library(variant: str, request: Request) -> dict[str, Any]:
    """列出共享库里的片段基名（动作实验室下拉用）。新导出的 vrma 丢进库里就能直接预览。"""
    if variant not in _MOTION_VARIANTS:
        raise HTTPException(status_code=404, detail="动作库不存在")
    directory = request.app.state.settings.data_dir / "motion-library" / variant
    if not directory.is_dir():
        return {"clips": []}
    return {"clips": sorted(path.stem for path in directory.glob("*.vrma"))}


@router.get("/motion-library/{variant}/{file_path:path}")
@router.head("/motion-library/{variant}/{file_path:path}")
def get_motion_library_file(variant: str, file_path: str, request: Request) -> Response:
    """共享动作库（male / female）只读下发，所有同套角色共用，禁止路径穿越。"""
    if variant not in _MOTION_VARIANTS:
        raise HTTPException(status_code=404, detail="动作库不存在")
    directory = request.app.state.settings.data_dir / "motion-library" / variant
    target = _resolve_persona_asset(directory, file_path)
    if target is None:
        raise HTTPException(status_code=404, detail="动作不存在")
    return FileResponse(target)


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


# 3D 资产包导入：zip 内 model.vrm 必需，vrma/<trigger>.vrma 与 avatar 图片可选
_VRM_TRIGGERS = {
    "idle", "listening", "thinking", "speaking", "executing",
    "awaiting_approval", "success", "error", "click", "project", "hover",
}
# 共享动作库：同性别/同物种的角色共用一套，不落各自目录（动物线走 2D 表，不进这里）。
_MOTION_VARIANTS = {"male", "female"}
_IMPORT3D_MAX_BYTES = 300 * 1024 * 1024


@router.post("/personas/{persona_id}/import3d")
async def import_persona_3d(persona_id: str, request: Request) -> dict[str, Any]:
    """导入 3D 资产包（zip）：解压校验后落盘并广播，挂件即时切换。"""
    persona_path = _persona_dir(request) / f"{persona_id}.yaml"
    if not _PERSONA_ID.fullmatch(persona_id) or not persona_path.is_file():
        raise HTTPException(status_code=404, detail="角色卡不存在")
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="缺少 file 字段（zip 包）")
    data = await upload.read()
    if len(data) > _IMPORT3D_MAX_BYTES:
        raise HTTPException(status_code=413, detail="资产包超过 300MB 上限")

    model_bytes: bytes | None = None
    vrma_files: dict[str, bytes] = {}
    avatar_bytes: bytes | None = None
    avatar_suffix = ".png"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = PurePosixPath(info.filename)
                if any(part in ("..", "/", "") for part in name.parts):
                    raise HTTPException(status_code=400, detail=f"zip 内含非法路径: {info.name}")
                stem, suffix = name.stem.lower(), name.suffix.lower()
                if suffix == ".vrm":
                    if model_bytes is not None:
                        raise HTTPException(status_code=400, detail="zip 内只允许一个 .vrm 模型")
                    model_bytes = zf.read(info)
                elif suffix == ".vrma" and stem in _VRM_TRIGGERS:
                    vrma_files[stem] = zf.read(info)
                elif suffix in (".png", ".jpg", ".jpeg", ".webp") and stem.startswith("avatar"):
                    if avatar_bytes is None:
                        avatar_bytes = zf.read(info)
                        avatar_suffix = ".png" if suffix == ".png" else suffix
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="不是有效的 zip 包") from exc
    if model_bytes is None:
        raise HTTPException(status_code=400, detail="zip 内未找到 model.vrm")

    # 导入闸门：坏资产不进落盘，错误信息要能直接指导修复动作。
    report = validate_vrm(model_bytes)
    if not report.ok:
        raise HTTPException(
            status_code=400,
            detail="VRM 不符合项目规格，已拒绝导入：\n- " + "\n- ".join(report.errors),
        )
    bad_vrma = {
        stem: errors for stem, body in vrma_files.items()
        if (errors := validate_vrma(body))
    }
    if bad_vrma:
        detail = "\n".join(f"- {stem}.vrma：{'；'.join(errs)}"
                            for stem, errs in sorted(bad_vrma.items()))
        raise HTTPException(status_code=400, detail="VRMA 动作文件不可用：\n" + detail)

    directory = _persona_asset_dir(request, persona_id)
    (directory / "model.vrm").write_bytes(model_bytes)
    vrma_dir = directory / "vrma"
    vrma_dir.mkdir(parents=True, exist_ok=True)
    for old in vrma_dir.glob("*.vrma"):
        old.unlink()  # 导入为整体替换语义，避免残留旧动作
    for stem, body in vrma_files.items():
        (vrma_dir / f"{stem}.vrma").write_bytes(body)
    avatar_url: str | None = None
    if avatar_bytes is not None:
        (directory / f"avatar{avatar_suffix}").write_bytes(avatar_bytes)
        avatar_url = f"/api/personas/{persona_id}/avatar"

    raw = yaml.safe_load(persona_path.read_text(encoding="utf-8")) or {}
    raw["vrm"] = "model.vrm"
    raw["avatar_driver"] = "vrm_3d"
    if avatar_url:
        raw["avatar"] = avatar_url
    persona_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    await request.app.state.presentation_bridge.broadcast(
        persona_id, request.app.state.event_hub
    )
    return {
        "persona_id": persona_id,
        "vrm": "model.vrm",
        "vrma": sorted(vrma_files),
        "avatar": avatar_url,
        "warnings": report.warnings,
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


@router.delete("/personas/{persona_id}")
def delete_persona(persona_id: str, request: Request) -> dict[str, Any]:
    """删除角色卡：内置角色与正在启用的角色不可删，避免把自己锁死。

    只删 config/personas/<id>.yaml；data/persona-assets/<id>/ 保留（用户上传的原图不可再生）。
    """
    if persona_id == "default":
        raise HTTPException(status_code=400, detail="内置角色不能删除")
    if request.app.state.settings.active_persona_id == persona_id:
        raise HTTPException(status_code=409, detail="该角色正在启用中，请先切换到其它角色再删除")
    path = _persona_dir(request) / f"{persona_id}.yaml"
    if not _PERSONA_ID.fullmatch(persona_id) or not path.is_file():
        raise HTTPException(status_code=404, detail="角色卡不存在")
    path.unlink()
    return {"deleted": persona_id}


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


@router.get("/personas/{persona_id}/motions")
def get_persona_motions(persona_id: str, request: Request) -> dict[str, Any]:
    """读取角色的动作参数覆盖（动作实验室）。"""
    path = _persona_dir(request) / f"{persona_id}.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="角色卡不存在")
    raw = _persona_from_file(path)
    pres = raw.get("presentation") if isinstance(raw.get("presentation"), dict) else {}
    return {
        "actions": pres.get("actions"),
        "vrm": pres.get("vrm"),
        "animations": pres.get("animations"),
    }


@router.put("/personas/{persona_id}/motions")
async def update_persona_motions(persona_id: str, payload: MotionsPayload, request: Request) -> dict[str, Any]:
    """写入角色的动作参数覆盖（动作实验室调参保存）。"""
    path = _persona_dir(request) / f"{persona_id}.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="角色卡不存在")
    raw = _persona_from_file(path)
    if not isinstance(raw, dict):
        raw = {}
    pres = raw.get("presentation") if isinstance(raw.get("presentation"), dict) else {}
    data = payload.model_dump(exclude_unset=True)
    if "actions" in data:
        pres["actions"] = data["actions"]
    if "vrm" in data:
        pres["vrm"] = data["vrm"]
    if "animations" in data:
        # 合并而不是整体替换：实验室只知道自己展示的那几个键，替换会丢掉别的调参项。
        existing = pres.get("animations") if isinstance(pres.get("animations"), dict) else {}
        pres["animations"] = {**existing, **(data["animations"] or {})}
    raw["presentation"] = pres
    path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    await request.app.state.presentation_bridge.broadcast(
        persona_id, request.app.state.event_hub
    )
    return {
        "actions": pres.get("actions"),
        "vrm": pres.get("vrm"),
        "animations": pres.get("animations"),
    }
