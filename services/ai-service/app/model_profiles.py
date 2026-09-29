"""本地模型档案：统一管理文字、多模态、语音识别与语音合成模型。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

ModelProfileCategory = Literal["text", "multimodal", "stt", "tts"]
CHAT_PROFILE_CATEGORIES: tuple[ModelProfileCategory, ...] = ("text", "multimodal")

CATEGORY_LABELS: dict[str, str] = {
    "stt": "语音识别模型",
    "tts": "语音合成模型",
    "text": "通用文字模型",
    "multimodal": "多模态模型",
}


class ModelProfile(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    category: ModelProfileCategory
    provider: str = Field(min_length=1, max_length=40)
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    voice: str = ""
    enabled: bool = True
    is_default: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        return text or None

    @model_validator(mode="after")
    def validate_provider(self) -> "ModelProfile":
        allowed = {
            "text": {"openai_compatible", "echo"},
            "multimodal": {"openai_compatible"},
            "stt": {"dashscope"},
            "tts": {"minimax", "dashscope", "openai_compatible"},
        }
        if self.provider not in allowed[self.category]:
            raise ValueError(f"{CATEGORY_LABELS[self.category]}不支持供应商 {self.provider}")
        return self


def profiles_path(root: Path) -> Path:
    return root / "data" / "settings.local.json"


def _read_overrides(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(profiles_path(root).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_overrides(root: Path, value: dict[str, Any]) -> None:
    path = profiles_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_model_profiles(root: Path) -> list[ModelProfile]:
    raw = _read_overrides(root).get("model_profiles")
    if not isinstance(raw, list):
        return []
    items: list[ModelProfile] = []
    for value in raw:
        try:
            items.append(ModelProfile.model_validate(value))
        except ValueError:
            continue
    return items


def save_model_profiles(root: Path, profiles: list[ModelProfile]) -> None:
    overrides = _read_overrides(root)
    overrides["model_profiles"] = [profile.model_dump() for profile in profiles]
    _write_overrides(root, overrides)


def public_model_profile(profile: ModelProfile) -> dict[str, Any]:
    value = profile.model_dump(exclude={"api_key"})
    value["api_key_configured"] = bool(profile.api_key)
    return value


def find_model_profile(profiles: list[ModelProfile], profile_id: str | None) -> ModelProfile | None:
    if not profile_id:
        return None
    return next((profile for profile in profiles if profile.id == profile_id), None)


def default_profile(
    profiles: list[ModelProfile],
    categories: tuple[ModelProfileCategory, ...],
) -> ModelProfile | None:
    for category in categories:
        for profile in profiles:
            if profile.category == category and profile.enabled and profile.is_default:
                return profile
    return None


def profile_settings(settings: Any, profile: ModelProfile) -> Any:
    """基于现有 Settings 构造单次请求配置，不修改全局状态。"""
    return replace(
        settings,
        llm_provider="echo" if profile.provider == "echo" else "openai",
        llm_base_url=profile.base_url or settings.llm_base_url,
        llm_api_key=profile.api_key or settings.llm_api_key,
        llm_model=profile.model or settings.llm_model,
    )


def apply_default_profiles(settings: Any, overrides: dict[str, Any]) -> None:
    """把各分类默认档案应用到运行时配置；档案优先于开发环境 .env。"""
    raw = overrides.get("model_profiles")
    if not isinstance(raw, list):
        return
    profiles: list[ModelProfile] = []
    for value in raw:
        try:
            profiles.append(ModelProfile.model_validate(value))
        except ValueError:
            continue

    text = default_profile(profiles, ("text", "multimodal"))
    if text is not None:
        settings.llm_provider = "echo" if text.provider == "echo" else "openai"
        settings.llm_base_url = text.base_url or settings.llm_base_url
        settings.llm_api_key = text.api_key or settings.llm_api_key
        settings.llm_model = text.model or settings.llm_model

    stt = default_profile(profiles, ("stt",))
    if stt is not None:
        settings.stt_provider = stt.provider
        settings.stt_model = stt.model or settings.stt_model
        if stt.api_key:
            settings.dashscope_api_key = stt.api_key

    tts = default_profile(profiles, ("tts",))
    if tts is not None:
        settings.tts_provider = tts.provider
        settings.tts_model = tts.model or settings.tts_model
        # 角色卡显式绑定的音色优先：模型档案只提供引擎与默认音色。
        settings.tts_base_url = tts.base_url or settings.tts_base_url
        if not getattr(settings, "persona_voice", ""):
            settings.tts_voice = tts.voice or settings.tts_voice
        if tts.provider == "minimax" and tts.api_key:
            settings.minimax_api_key = tts.api_key
        if tts.provider == "dashscope" and tts.api_key:
            settings.dashscope_api_key = tts.api_key
        if tts.provider == "openai_compatible":
            settings.tts_api_key = tts.api_key or settings.tts_api_key


def ensure_initial_profiles(root: Path, settings: Any) -> list[ModelProfile]:
    """首次打开设置页时，把现有环境配置迁移为可编辑档案。"""
    overrides = _read_overrides(root)
    if "model_profiles" in overrides:
        return load_model_profiles(root)

    profiles: list[ModelProfile] = []
    if settings.llm_base_url or settings.llm_api_key:
        profiles.append(
            ModelProfile(
                id="text_default",
                name=settings.llm_model or "默认文字模型",
                category="text",
                provider="openai_compatible",
                base_url=settings.llm_base_url or "",
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                is_default=True,
            )
        )
    if settings.dashscope_api_key:
        profiles.append(
            ModelProfile(
                id="stt_default",
                name=settings.stt_model or "默认语音识别",
                category="stt",
                provider="dashscope",
                model=settings.stt_model,
                api_key=settings.dashscope_api_key,
                is_default=True,
            )
        )
    tts_provider = settings.tts_provider if settings.tts_provider in {"minimax", "dashscope"} else "minimax"
    tts_key = settings.minimax_api_key if tts_provider == "minimax" else settings.dashscope_api_key
    if tts_key:
        profiles.append(
            ModelProfile(
                id="tts_default",
                name=settings.tts_model or "默认语音合成",
                category="tts",
                provider=tts_provider,
                model=settings.tts_model,
                api_key=tts_key,
                voice=settings.tts_voice,
                is_default=True,
            )
        )
    save_model_profiles(root, profiles)
    return profiles


async def list_provider_models(
    base_url: str,
    api_key: str | None,
    fallback_key: str | None = None,
) -> dict[str, Any]:
    """向 OpenAI 兼容供应商拉取可用模型 ID 列表（GET /models）。

    只读查询，不写任何配置；供应商不支持或未配置时返回
    `available=False` + `reason`，由前端回退为手填模型名。
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {"available": False, "models": [], "reason": "请先填写 API 地址"}
    key = (api_key or "").strip() or (fallback_key or "").strip()
    if not key:
        return {"available": False, "models": [], "reason": "请先填写 API Key"}
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            return {
                "available": False,
                "models": [],
                "reason": f"获取失败：HTTP {response.status_code} {response.text[:120]}",
            }
        body = response.json()
    except Exception as exc:
        return {"available": False, "models": [], "reason": f"获取失败：{exc}"}

    raw = body.get("data") if isinstance(body, dict) else None
    if not isinstance(raw, list):
        return {"available": False, "models": [], "reason": "供应商返回格式不支持模型列表"}
    models: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        model_id = ""
        if isinstance(entry, dict):
            model_id = str(entry.get("id") or "").strip()
        elif isinstance(entry, str):
            model_id = entry.strip()
        if model_id and model_id not in seen:
            seen.add(model_id)
            models.append(model_id)
    models.sort()
    if not models:
        return {"available": False, "models": [], "reason": "供应商未返回任何模型"}
    return {"available": True, "models": models, "reason": None}


async def test_model_profile(profile: ModelProfile, fallback_key: str | None = None) -> dict[str, Any]:
    if profile.category not in CHAT_PROFILE_CATEGORIES:
        return {
            "ok": False,
            "message": f"{CATEGORY_LABELS[profile.category]}请在保存后通过语音链路检测",
        }
    if profile.provider == "echo" or not profile.base_url or not profile.model:
        return {"ok": False, "message": "请先填写 API 地址和模型名称"}
    key = profile.api_key or fallback_key
    if not key:
        return {"ok": False, "message": "请先填写 API Key"}
    url = f"{profile.base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    payload = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            return {"ok": False, "message": f"连接失败：HTTP {response.status_code} {response.text[:120]}"}
        return {"ok": True, "message": "连接成功"}
    except Exception as exc:
        return {"ok": False, "message": f"连接失败：{exc}"}
