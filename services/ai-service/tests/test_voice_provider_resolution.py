"""语音供应商解析与模型档案白名单：STT 新供应商、Breeze、连接测试分流。"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import pytest

from app import model_profiles
from app.config import Settings, resolve_stt_provider, resolve_tts_provider
from app.model_profiles import ModelProfile, apply_default_profiles
from app.speech.breeze import BreezeSynthesizer
from app.speech.factory import build_speech_stack, build_stt_recognizer, build_tts_synthesizer
from app.speech.openai_stt import OpenAICompatibleRecognizer

ROOT = Path(__file__).resolve().parents[3]


def _settings(**overrides) -> Settings:
    return Settings(repo_root=ROOT, **overrides)


def _profile(**overrides) -> ModelProfile:
    values: dict = {
        "id": "p1",
        "name": "测试档案",
        "category": "stt",
        "provider": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3-turbo",
    }
    values.update(overrides)
    return ModelProfile(**values)


def test_stt_profile_accepts_openai_compatible():
    # Groq Whisper 预设此前被后端白名单拒绝（保存即 422），现在必须能存下来
    profile = _profile()
    assert profile.provider == "openai_compatible"


def test_stt_profile_still_rejects_unknown_provider():
    with pytest.raises(ValueError, match="不支持供应商"):
        _profile(provider="volcengine")


def test_tts_profile_accepts_breeze():
    profile = _profile(category="tts", provider="breeze", model="breeze-tts-2")
    assert profile.provider == "breeze"


def test_resolve_stt_openai_compatible_needs_base_url():
    ok = _settings(stt_provider="openai_compatible", stt_base_url="https://api.groq.com/openai/v1")
    assert resolve_stt_provider(ok) == ("openai_compatible", None)

    missing = _settings(stt_provider="openai_compatible", stt_base_url="")
    provider, reason = resolve_stt_provider(missing)
    assert provider == "disabled"
    assert "Base URL" in (reason or "")


def test_resolve_stt_auto_order():
    both = _settings(
        stt_provider="auto", dashscope_api_key="dk", stt_base_url="https://x/v1"
    )
    assert resolve_stt_provider(both)[0] == "dashscope"
    assert resolve_stt_provider(
        _settings(stt_provider="auto", stt_base_url="https://x/v1")
    )[0] == "openai_compatible"
    assert resolve_stt_provider(_settings(stt_provider="auto"))[0] == "disabled"


def test_resolve_stt_volcengine_reports_missing_adapter():
    # 后端没有火山识别适配器，必须给明确原因，而不是静默降级到 dashscope
    settings = _settings(stt_provider="volcengine", volc_app_id="a", volc_token="t")
    provider, reason = resolve_stt_provider(settings)
    assert provider == "disabled"
    assert "火山" in (reason or "")


def test_resolve_stt_rejects_unknown_provider():
    provider, reason = resolve_stt_provider(_settings(stt_provider="kimi"))
    assert provider == "disabled"
    assert "未知 STT 供应商" in (reason or "")


def test_resolve_tts_breeze():
    assert resolve_tts_provider(
        _settings(tts_provider="breeze", breeze_api_key="bk")
    ) == ("breeze", None)
    provider, reason = resolve_tts_provider(_settings(tts_provider="breeze", breeze_api_key=""))
    assert provider == "disabled"
    assert "BREEZE_API_KEY" in (reason or "")


def test_resolve_tts_auto_falls_back_to_breeze():
    assert resolve_tts_provider(_settings(tts_provider="auto", breeze_api_key="bk"))[0] == "breeze"


def test_factory_builds_new_adapters():
    recognizer = build_stt_recognizer(
        "openai_compatible", base_url="https://x/v1", model="whisper-large-v3-turbo"
    )
    assert isinstance(recognizer, OpenAICompatibleRecognizer)
    assert recognizer.available is True

    synthesizer = build_tts_synthesizer("breeze", api_key="bk", model="breeze-tts-2", voice="voc_1")
    assert isinstance(synthesizer, BreezeSynthesizer)
    assert synthesizer.available is True

    # 未接入的供应商仍返回 disabled，不抛异常
    assert build_stt_recognizer("volcengine", reason="待接入").available is False


def test_breeze_runtime_uses_saved_tts_base_url():
    stack = build_speech_stack(
        _settings(
            tts_provider="breeze",
            breeze_api_key="bk",
            tts_base_url="https://breeze.internal/v1",
        )
    )
    assert isinstance(stack.synthesizer, BreezeSynthesizer)
    assert stack.synthesizer._url("voices") == "https://breeze.internal/v1/voices"


def test_apply_default_profiles_wires_stt_base_url_and_breeze_key():
    settings = _settings()
    apply_default_profiles(
        settings,
        {
            "model_profiles": [
                {
                    "id": "stt_groq",
                    "name": "Groq Whisper",
                    "category": "stt",
                    "provider": "openai_compatible",
                    "base_url": "https://api.groq.com/openai/v1",
                    "model": "whisper-large-v3-turbo",
                    "api_key": "gk",
                    "is_default": True,
                },
                {
                    "id": "tts_breeze",
                    "name": "Breeze TTS 2",
                    "category": "tts",
                    "provider": "breeze",
                    "model": "breeze-tts-2",
                    "api_key": "bk",
                    "is_default": True,
                },
            ]
        },
    )
    assert settings.stt_provider == "openai_compatible"
    assert settings.stt_base_url == "https://api.groq.com/openai/v1"
    assert settings.stt_api_key == "gk"
    assert settings.stt_model == "whisper-large-v3-turbo"
    assert settings.tts_provider == "breeze"
    assert settings.breeze_api_key == "bk"


def test_probe_wav_is_readable_mono(tmp_path):
    from app.model_profiles import _probe_wav

    path = tmp_path / "probe.wav"
    _probe_wav(path, 16000)
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 16000
        assert handle.readframes(1) != b""


def test_test_model_profile_dispatches_voice_categories_without_network():
    settings = _settings()

    missing_key = ModelProfile(
        id="t1", name="MiniMax", category="tts", provider="minimax", model="speech-2.8-hd"
    )
    result = asyncio.run(model_profiles.test_model_profile(missing_key, settings))
    assert result["ok"] is False
    assert result["message"] == "请先填写 API Key"

    missing_stt_key = _profile(provider="dashscope", base_url="", model="paraformer-realtime-v2")
    missing_stt_key.api_key = None
    result = asyncio.run(model_profiles.test_model_profile(missing_stt_key, settings))
    assert result["ok"] is False
    assert result["message"] == "请先填写 API Key"

    echo = ModelProfile(id="t2", name="echo", category="text", provider="echo", base_url="", model="")
    assert asyncio.run(model_profiles.test_model_profile(echo, settings))["ok"] is False


def test_preview_key_fallback_covers_breeze():
    """Breeze key 只存在于配置（档案里没存）时，试听不能误判为缺 key。"""
    from app.api.voice import _KEY_REQUIRED, _settings_key

    assert "breeze" in _KEY_REQUIRED
    assert _settings_key(Settings(breeze_api_key="brz_env"), "breeze") == "brz_env"
    assert _settings_key(Settings(), "breeze") == ""
