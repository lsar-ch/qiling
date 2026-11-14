"""本地模型档案：统一管理文字、多模态、语音识别与语音合成模型。"""

from __future__ import annotations

import json
import math
import struct
import tempfile
import wave
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
            "stt": {"dashscope", "openai_compatible"},
            "tts": {"minimax", "dashscope", "openai_compatible", "breeze"},
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
        if stt.provider == "dashscope" and stt.api_key:
            settings.dashscope_api_key = stt.api_key
        elif stt.provider == "openai_compatible":
            settings.stt_base_url = stt.base_url or settings.stt_base_url
            settings.stt_api_key = stt.api_key or settings.stt_api_key

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
        if tts.provider == "breeze":
            settings.breeze_api_key = tts.api_key or settings.breeze_api_key


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
    elif settings.stt_base_url:
        profiles.append(
            ModelProfile(
                id="stt_default",
                name=settings.stt_model or "默认语音识别（OpenAI 兼容）",
                category="stt",
                provider="openai_compatible",
                base_url=settings.stt_base_url,
                model=settings.stt_model,
                api_key=settings.stt_api_key,
                is_default=True,
            )
        )
    tts_provider = (
        settings.tts_provider
        if settings.tts_provider in {"minimax", "dashscope", "breeze"}
        else "minimax"
    )
    tts_key = {
        "minimax": settings.minimax_api_key,
        "dashscope": settings.dashscope_api_key,
        "breeze": settings.breeze_api_key,
    }[tts_provider]
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


_TEST_PHRASE = "你好，这是栖灵的语音链路连通性测试。"


def _probe_wav(path: Path, rate: int) -> None:
    """写 1 秒 220Hz 低音：用来验证识别端点的鉴权与连通，不追求识别内容。"""
    frames = max(1, int(rate * 1.0))
    samples = b"".join(
        struct.pack("<h", int(600 * math.sin(2 * math.pi * 220 * index / rate)))
        for index in range(frames)
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples)


async def _test_chat_profile(
    profile: ModelProfile, fallback_key: str | None
) -> dict[str, Any]:
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
            return {
                "ok": False,
                "message": f"连接失败：HTTP {response.status_code} {response.text[:120]}",
            }
        return {"ok": True, "message": "连接成功"}
    except Exception as exc:
        return {"ok": False, "message": f"连接失败：{exc}"}


async def _test_tts_profile(profile: ModelProfile, settings: Any) -> dict[str, Any]:
    from app.speech.base import SpeechProviderError, SpeechUnavailable
    from app.speech.factory import build_tts_synthesizer

    if profile.provider in {"minimax", "dashscope", "breeze"} and not profile.api_key:
        return {"ok": False, "message": "请先填写 API Key"}
    if not profile.model:
        return {"ok": False, "message": "请先填写模型名称"}
    synthesizer = build_tts_synthesizer(
        profile.provider,
        api_key=profile.api_key or "",
        base_url=profile.base_url,
        model=profile.model,
        voice=profile.voice,
        fmt=settings.tts_format,
        sample_rate=settings.tts_sample_rate,
    )
    if not synthesizer.available:
        return {"ok": False, "message": "请先填写 API 地址（Base URL）"}
    try:
        audio = await synthesizer.synthesize(_TEST_PHRASE)
    except (SpeechUnavailable, SpeechProviderError) as exc:
        return {"ok": False, "message": str(exc)}
    return {
        "ok": True,
        "message": f"连接成功，已合成 {len(audio.data)} 字节测试音频（消耗少量额度）",
    }


async def _test_stt_profile(profile: ModelProfile, settings: Any) -> dict[str, Any]:
    from app.speech.base import SpeechProviderError, SpeechUnavailable
    from app.speech.factory import build_stt_recognizer

    if profile.provider == "dashscope" and not profile.api_key:
        return {"ok": False, "message": "请先填写 API Key"}
    if not profile.model:
        return {"ok": False, "message": "请先填写模型名称"}
    recognizer = build_stt_recognizer(
        profile.provider,
        api_key=profile.api_key or "",
        base_url=profile.base_url,
        model=profile.model,
        sample_rate=settings.stt_sample_rate,
    )
    if not recognizer.available:
        return {"ok": False, "message": "请先填写 API 地址（Base URL）"}

    tmp = tempfile.TemporaryDirectory()
    try:
        wav_path = Path(tmp.name) / "probe.wav"
        _probe_wav(wav_path, settings.stt_sample_rate)
        try:
            await recognizer.recognize(str(wav_path), language=settings.stt_language)
        except (SpeechUnavailable, SpeechProviderError) as exc:
            return {"ok": False, "message": str(exc)}
    finally:
        tmp.cleanup()
    return {"ok": True, "message": "连接成功，识别端点鉴权与服务正常"}


async def test_model_profile(
    profile: ModelProfile,
    settings: Any,
    fallback_key: str | None = None,
) -> dict[str, Any]:
    """连接测试：文字类打一次 chat/completions，语音类打一次真实合成 / 识别。"""
    if profile.category in CHAT_PROFILE_CATEGORIES:
        return await _test_chat_profile(profile, fallback_key)
    if profile.category == "tts":
        return await _test_tts_profile(profile, settings)
    if profile.category == "stt":
        return await _test_stt_profile(profile, settings)
    return {"ok": False, "message": f"{CATEGORY_LABELS[profile.category]}暂不支持连接测试"}
