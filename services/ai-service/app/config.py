"""ai-service 配置加载。

优先级：环境变量 > config/settings.yaml 的 service 段 > 默认值。
Step 1 只绑定 127.0.0.1，不开放公网。
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8736
DEFAULT_WEB_DEV_PORT = 5173
DEFAULT_DESKTOP_DEV_PORT = 1420


class PerformanceMode(StrEnum):
    """性能模式：quality（全功能）/ balanced（均衡默认）/ lite（仅文字）。"""

    QUALITY = "quality"
    BALANCED = "balanced"
    LITE = "lite"


def repo_root() -> Path:
    env = os.environ.get("DESKMATE_HOME")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[3]


def _read_version(repo: Path) -> str:
    try:
        cfg = yaml.safe_load((repo / "config" / "settings.yaml").read_text(encoding="utf-8"))
        version = (cfg or {}).get("app", {}).get("version")
        return str(version) if version else "0.1.0"
    except Exception:
        return "0.1.0"


@dataclass
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    repo_root: Path = field(default_factory=repo_root)
    version: str = "0.1.0"
    # ── LLM（Step 3）──────────────────────────
    llm_provider: str = "auto"          # auto | openai | echo
    llm_base_url: str | None = None     # OpenAI 兼容地址（可含 /v1）
    llm_api_key: str | None = None
    llm_model: str = ""
    llm_temperature: float = 0.7
    llm_max_tokens: int = 512
    llm_timeout_s: float = 60.0
    short_reply_chars: int = 120        # 超过则展开主界面
    # ── 语音（Step 4，云 API，见 docs/VOICE-PROVIDERS.md）────────
    voice_enabled: bool = True
    voice_auto_speak: bool = True
    stt_provider: str = "auto"          # auto | dashscope | volcengine | disabled
    stt_model: str = "paraformer-realtime-v2"
    stt_sample_rate: int = 16000
    stt_language: str = "zh"
    tts_provider: str = "auto"
    tts_model: str = "speech-2.8-hd"          # MiniMax 主声模型
    tts_voice: str = "Chinese (Mandarin)_Soft_Girl"  # 2026-09-04 用户拍板
    tts_format: str = "mp3"
    tts_sample_rate: int = 32000
    voice_speed: float = 1.0            # 0.5~2.0
    voice_pitch: float = 1.0            # 0.5~2.0
    voice_volume: float = 1.0           # 0~2.0
    voice_emotion: str | None = None
    voice_instruction: str | None = None
    # ── 角色卡与界面设置 ─────────────────────
    active_persona_id: str = "default"
    persona_name: str = "千问"
    persona_kind: str = "assistant"
    persona_description: str = ""
    persona_personality: list[str] = field(default_factory=list)
    persona_backstory: str = ""
    persona_language: str = "zh-CN"
    persona_reply_style: str = ""
    persona_avatar: str = ""
    ui_language: str = "zh-CN"
    ui_theme: str = "system"
    permission_level: str = "confirm_risky"
    memory_budget_chars: int = 4000
    memory_mode: str = "standalone"
    performance_mode: str = "balanced"    # quality | balanced | lite
    obsidian_vault_path: str = (
        "/Users/lxb/Library/Mobile Documents/iCloud~md~obsidian/Documents/knowledge/knowledge"
    )
    dashscope_api_key: str | None = None
    minimax_api_key: str | None = None
    # ── 语音激活（常开/静默/唤醒，见 docs/VOICE-ACTIVATION.md）──
    activation_enabled: bool = True
    activation_default_state: str = "listening"   # listening | sleeping
    activation_persona_name: str = "千问"          # 唤醒词 = 前缀 + 角色名（可自定义）
    activation_wake_prefixes: list[str] = field(
        default_factory=lambda: ["你好", "嗨"]
    )
    activation_sleep_phrases: list[str] = field(
        default_factory=lambda: ["暂时静默", "先静默", "先别说话", "别说话", "安静一下", "静默"]
    )
    volc_app_id: str | None = None
    volc_token: str | None = None
    volc_cluster: str = "volcano_tts"
    volc_voice_type: str | None = None
    interruption_enabled: bool = True
    auto_barge_in: bool = False
    cors_origins: list[str] = field(
        default_factory=lambda: [
            f"http://127.0.0.1:{DEFAULT_WEB_DEV_PORT}",
            f"http://localhost:{DEFAULT_WEB_DEV_PORT}",
            f"http://127.0.0.1:{DEFAULT_DESKTOP_DEV_PORT}",
            f"http://localhost:{DEFAULT_DESKTOP_DEV_PORT}",
            "tauri://localhost",
            "http://tauri.localhost",
        ]
    )

    @property
    def system_prompt(self) -> str:
        """系统提示词（默认读取 config/system_prompt.md）。"""
        try:
            path = self.repo_root / "config" / "system_prompt.md"
            text = path.read_text(encoding="utf-8")
            return text.strip() or "你是 DeskMate，一个本地优先的桌面 AI 助理。"
        except Exception:
            return "你是 DeskMate，一个本地优先的桌面 AI 助理。"

    @property
    def service_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def web_dist_dir(self) -> Path:
        return self.repo_root / "apps" / "web" / "dist"

    @property
    def data_dir(self) -> Path:
        return self.repo_root / "data"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def personas_dir(self) -> Path:
        return self.repo_root / "config" / "personas"

    @property
    def local_settings_path(self) -> Path:
        return self.data_dir / "settings.local.json"


def _load_yaml_section(root: Path, name: str) -> dict:
    try:
        cfg = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
        section = (cfg or {}).get(name, {})
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def _load_local_overrides(root: Path) -> dict[str, Any]:
    path = root / "data" / "settings.local.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_persona(root: Path, persona_id: str) -> dict[str, Any]:
    path = root / "config" / "personas" / f"{persona_id}.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _apply_persona(settings: Settings, persona: dict[str, Any]) -> None:
    settings.active_persona_id = str(persona.get("id") or settings.active_persona_id)
    settings.persona_name = str(persona.get("name") or settings.persona_name)
    settings.persona_kind = str(persona.get("kind") or settings.persona_kind)
    settings.persona_description = str(persona.get("description") or "")
    settings.persona_personality = [
        str(item) for item in persona.get("personality", []) if str(item).strip()
    ]
    settings.persona_backstory = str(persona.get("backstory") or "")
    settings.persona_language = str(persona.get("language") or settings.persona_language)
    settings.persona_reply_style = str(persona.get("reply_style") or "")
    settings.persona_avatar = str(persona.get("avatar") or "")
    voice = persona.get("voice") if isinstance(persona.get("voice"), dict) else {}
    settings.tts_provider = str(voice.get("provider") or settings.tts_provider).lower()
    settings.tts_model = str(voice.get("model") or settings.tts_model)
    settings.tts_voice = str(voice.get("voice") or settings.tts_voice)
    settings.voice_speed = _as_float(voice.get("speed", settings.voice_speed), settings.voice_speed)
    settings.voice_pitch = _as_float(voice.get("pitch", settings.voice_pitch), settings.voice_pitch)
    activation = persona.get("activation") if isinstance(persona.get("activation"), dict) else {}
    settings.activation_persona_name = str(
        activation.get("persona_name") or settings.activation_persona_name
    )
    prefixes = activation.get("wake_prefixes")
    if isinstance(prefixes, list) and prefixes:
        settings.activation_wake_prefixes = [str(item) for item in prefixes]
    sleep_phrases = activation.get("sleep_phrases")
    if isinstance(sleep_phrases, list) and sleep_phrases:
        settings.activation_sleep_phrases = [str(item) for item in sleep_phrases]


def _as_float(value: object, default: float) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def load_settings() -> Settings:
    root = repo_root()
    try:  # 自动读取项目根目录 .env（无则忽略）
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except Exception:
        pass
    settings = Settings(repo_root=root, version=_read_version(root))
    overrides = _load_local_overrides(root)
    settings.active_persona_id = str(overrides.get("active_persona_id", settings.active_persona_id))
    persona_cfg = _load_persona(root, settings.active_persona_id)
    _apply_persona(settings, persona_cfg)
    ui_cfg = overrides.get("ui", {}) if isinstance(overrides.get("ui"), dict) else {}
    settings.ui_language = str(ui_cfg.get("language", settings.ui_language))
    settings.ui_theme = str(ui_cfg.get("theme", settings.ui_theme))
    settings.permission_level = str(overrides.get("permission_level", settings.permission_level))
    memory_cfg = _load_yaml_section(root, "memory")
    local_memory = overrides.get("memory", {}) if isinstance(overrides.get("memory"), dict) else {}
    memory_mode_value = local_memory.get("mode", overrides.get("memory_mode", settings.memory_mode))
    settings.memory_mode = str(
        os.environ.get(
            "MEMORY_MODE",
            memory_mode_value if memory_mode_value is not None else memory_cfg.get("mode", settings.memory_mode),
        )
    ).strip().lower() or "standalone"
    settings.memory_budget_chars = _as_int(
        os.environ.get(
            "MEMORY_BUDGET_CHARS",
            local_memory.get("budget_chars", memory_cfg.get("budget_chars", settings.memory_budget_chars)),
        ),
        settings.memory_budget_chars,
    )
    settings.performance_mode = str(
        os.environ.get(
            "PERFORMANCE_MODE", overrides.get("performance_mode", settings.performance_mode)
        )
    ).strip().lower() or "balanced"
    if settings.performance_mode not in ("quality", "balanced", "lite"):
        settings.performance_mode = "balanced"
    settings.obsidian_vault_path = str(
        os.environ.get(
            "OBSIDIAN_VAULT_PATH",
            local_memory.get(
                "obsidian_vault_path",
                memory_cfg.get("obsidian_vault_path", settings.obsidian_vault_path),
            ),
        )
    )
    settings.host = os.environ.get("DESKMATE_HOST", settings.host)
    try:
        settings.port = int(os.environ.get("DESKMATE_PORT", str(settings.port)))
    except ValueError:
        pass
    origins = os.environ.get("DESKMATE_CORS_ORIGINS", "")
    if origins.strip():
        settings.cors_origins = [o.strip() for o in origins.split(",") if o.strip()]

    llm_cfg = _load_yaml_section(root, "llm")
    chat_cfg = _load_yaml_section(root, "chat")
    local_llm = overrides.get("llm", {}) if isinstance(overrides.get("llm"), dict) else {}
    # 用户在设置页保存的配置优先于开发环境 .env；未保存时继续使用环境变量。
    settings.llm_provider = str(
        local_llm.get("provider")
        or os.environ.get("LLM_PROVIDER")
        or llm_cfg.get("provider", "auto")
    )
    settings.llm_base_url = _nonempty(
        local_llm.get("base_url")
        or os.environ.get("OPENAI_BASE_URL")
        or llm_cfg.get("base_url")
    )
    settings.llm_api_key = _nonempty(
        local_llm.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
        or llm_cfg.get("api_key")
    )
    settings.llm_model = str(
        local_llm.get("model")
        or os.environ.get("OPENAI_MODEL")
        or llm_cfg.get("model", "")
    )
    settings.llm_temperature = _as_float(
        os.environ.get("LLM_TEMPERATURE", llm_cfg.get("temperature", 0.7)), 0.7
    )
    settings.llm_max_tokens = _as_int(
        os.environ.get("LLM_MAX_TOKENS", llm_cfg.get("max_tokens", 512)), 512
    )
    settings.llm_timeout_s = _as_float(
        os.environ.get("LLM_TIMEOUT_S", llm_cfg.get("timeout_seconds", 60)), 60.0
    )
    settings.short_reply_chars = _as_int(
        os.environ.get("SHORT_REPLY_CHARS", chat_cfg.get("short_reply_chars", 120)), 120
    )

    # ── 语音配置（yaml voice 段；环境变量优先）──────────────
    voice_cfg = _load_yaml_section(root, "voice") or {}
    persona_voice = persona_cfg.get("voice") if isinstance(persona_cfg.get("voice"), dict) else {}
    persona_activation = (
        persona_cfg.get("activation")
        if isinstance(persona_cfg.get("activation"), dict)
        else {}
    )
    settings.voice_enabled = _as_bool(
        os.environ.get(
            "VOICE_ENABLED",
            overrides.get("voice_enabled", _nested(voice_cfg, ("enabled",), True)),
        ),
        True,
    )
    settings.voice_auto_speak = _as_bool(
        os.environ.get(
            "VOICE_AUTO_SPEAK",
            overrides.get("voice_auto_speak", _nested(voice_cfg, ("auto_speak",), True)),
        ),
        True,
    )
    settings.stt_provider = os.environ.get(
        "VOICE_STT_PROVIDER", str(_nested(voice_cfg, ("stt", "provider"), "auto"))
    ).strip().lower()
    settings.stt_model = os.environ.get(
        "VOICE_STT_MODEL", str(_nested(voice_cfg, ("stt", "model"), settings.stt_model))
    ).strip()
    settings.stt_sample_rate = _as_int(
        os.environ.get("VOICE_STT_SAMPLE_RATE", _nested(voice_cfg, ("stt", "sample_rate"), 16000)),
        16000,
    )
    settings.stt_language = os.environ.get(
        "VOICE_STT_LANGUAGE", str(_nested(voice_cfg, ("stt", "language"), "zh"))
    ).strip() or "zh"
    settings.tts_provider = os.environ.get(
        "VOICE_TTS_PROVIDER",
        str(
            persona_voice.get(
                "provider", _nested(voice_cfg, ("tts", "provider"), settings.tts_provider)
            )
        ),
    ).strip().lower()
    settings.tts_model = os.environ.get(
        "VOICE_TTS_MODEL",
        str(persona_voice.get("model", _nested(voice_cfg, ("tts", "model"), settings.tts_model))),
    ).strip()
    settings.tts_voice = os.environ.get(
        "VOICE_TTS_VOICE",
        str(persona_voice.get("voice", _nested(voice_cfg, ("tts", "voice"), settings.tts_voice))),
    ).strip()
    settings.tts_format = os.environ.get(
        "VOICE_TTS_FORMAT", str(_nested(voice_cfg, ("tts", "format"), "wav"))
    ).strip().lower() or "wav"
    settings.tts_sample_rate = _as_int(
        os.environ.get("VOICE_TTS_SAMPLE_RATE", _nested(voice_cfg, ("tts", "sample_rate"), 24000)),
        24000,
    )
    params_cfg = _nested(voice_cfg, ("params",), {}) or {}
    settings.voice_speed = _as_float(
        os.environ.get(
            "VOICE_SPEED",
            overrides.get("voice_speed", persona_voice.get("speed", params_cfg.get("speed", 1.0))),
        ),
        1.0,
    )
    settings.voice_pitch = _as_float(
        os.environ.get(
            "VOICE_PITCH",
            overrides.get("voice_pitch", persona_voice.get("pitch", params_cfg.get("pitch", 1.0))),
        ),
        1.0,
    )
    settings.voice_volume = _as_float(
        os.environ.get("VOICE_VOLUME", overrides.get("voice_volume", params_cfg.get("volume", 1.0))),
        1.0,
    )
    settings.voice_emotion = _nonempty(
        os.environ.get("VOICE_EMOTION", overrides.get("voice_emotion", params_cfg.get("emotion")))
    )
    settings.voice_instruction = _nonempty(
        os.environ.get(
            "VOICE_INSTRUCTION", overrides.get("voice_instruction", params_cfg.get("instruction"))
        )
    )
    dashscope_cfg = _nested(voice_cfg, ("dashscope",), {}) or {}
    settings.dashscope_api_key = _nonempty(
        overrides.get("dashscope_api_key")
        or os.environ.get("DASHSCOPE_API_KEY")
        or dashscope_cfg.get("api_key")
    )
    minimax_cfg = _nested(voice_cfg, ("minimax",), {}) or {}
    settings.minimax_api_key = _nonempty(
        overrides.get("minimax_api_key")
        or os.environ.get("MINIMAX_API_KEY")
        or minimax_cfg.get("api_key")
    )
    act_cfg = _nested(voice_cfg, ("activation",), {}) or {}
    settings.activation_enabled = _as_bool(
        os.environ.get(
            "VOICE_ACTIVATION_ENABLED",
            overrides.get("activation_enabled", act_cfg.get("enabled", True)),
        ),
        True,
    )
    settings.activation_default_state = os.environ.get(
        "VOICE_ACTIVATION_STATE",
        str(overrides.get("activation_default_state", act_cfg.get("default_state", "listening"))),
    ).strip().lower() or "listening"
    settings.activation_persona_name = (
        _nonempty(
            os.environ.get(
                "VOICE_PERSONA_NAME",
                persona_activation.get("persona_name", act_cfg.get("persona_name")),
            )
        )
        or settings.persona_name
    )
    wake_prefixes = act_cfg.get("wake_prefixes")
    if not isinstance(wake_prefixes, list) or not wake_prefixes:
        wake_prefixes = persona_activation.get("wake_prefixes")
    if isinstance(wake_prefixes, list) and wake_prefixes:
        settings.activation_wake_prefixes = [str(x) for x in wake_prefixes]
    sleep_phrases = act_cfg.get("sleep_phrases")
    if not isinstance(sleep_phrases, list) or not sleep_phrases:
        sleep_phrases = persona_activation.get("sleep_phrases")
    if isinstance(sleep_phrases, list) and sleep_phrases:
        settings.activation_sleep_phrases = [str(x) for x in sleep_phrases]
    volc_cfg = _nested(voice_cfg, ("volcengine",), {}) or {}
    settings.volc_app_id = _nonempty(os.environ.get("VOLC_APP_ID", volc_cfg.get("app_id")))
    settings.volc_token = _nonempty(os.environ.get("VOLC_ACCESS_TOKEN", volc_cfg.get("token")))
    settings.volc_cluster = os.environ.get(
        "VOLC_CLUSTER", str(volc_cfg.get("cluster", "volcano_tts"))
    ).strip() or "volcano_tts"
    settings.volc_voice_type = _nonempty(
        os.environ.get("VOLC_VOICE_TYPE", volc_cfg.get("voice_type"))
    )
    settings.interruption_enabled = _as_bool(
        os.environ.get(
            "VOICE_INTERRUPTION", _nested(voice_cfg, ("interruption", "enabled"), True)
        ),
        True,
    )
    settings.auto_barge_in = _as_bool(
        os.environ.get(
            "VOICE_AUTO_BARGE_IN", _nested(voice_cfg, ("interruption", "auto_barge_in"), False)
        ),
        False,
    )
    # 模型档案优先级最高；用户新建/设为默认后无需重启服务。
    from app.model_profiles import apply_default_profiles

    apply_default_profiles(settings, overrides)
    return settings


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return default


def _nested(cfg: dict, keys: tuple[str, ...], default: object = None) -> object:
    """从嵌套 dict 安全取值（yaml voice.stt.provider 之类）。"""
    cur: object = cfg
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _nonempty(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def resolve_llm_provider(settings: Settings) -> str:
    """auto：配置了 OpenAI 兼容端点就用 openai，否则退回 echo 演示。"""
    provider = settings.llm_provider.strip().lower()
    if provider == "echo":
        return "echo"
    if provider == "openai":
        return "openai"
    if settings.llm_base_url or settings.llm_api_key:
        return "openai"
    return "echo"


def is_lite_mode(settings: Settings) -> bool:
    """lite 模式：语音与动画视为禁用，只保留文字链路。"""
    return settings.performance_mode == "lite"


def resolve_stt_provider(settings: Settings) -> tuple[str, str | None]:
    """返回 (实际 STT provider, 不可用原因)；未配置云 key 时降级 disabled。"""
    provider = settings.stt_provider.strip().lower()
    if not settings.voice_enabled or provider == "disabled":
        return "disabled", "语音已关闭或未启用"
    if provider == "dashscope":
        if settings.dashscope_api_key:
            return "dashscope", None
        return "disabled", "未配置 DASHSCOPE_API_KEY，语音识别不可用"
    if provider == "volcengine":
        if settings.volc_app_id and settings.volc_token:
            return "volcengine", None
        return "disabled", "未配置 VOLC_APP_ID / VOLC_ACCESS_TOKEN"
    if settings.dashscope_api_key:
        return "dashscope", None
    if settings.volc_app_id and settings.volc_token:
        return "volcengine", None
    return "disabled", "未配置任何云语音供应商（DASHSCOPE_API_KEY 等）"


def resolve_tts_provider(settings: Settings) -> tuple[str, str | None]:
    """TTS 供应商解析：minimax（主声）| dashscope | disabled；火山待 Step 8。

    TTS 与 STT 相互独立：STT 固定走 dashscope，TTS 主声走 minimax（auto 优先 minimax）。
    """
    requested = settings.tts_provider.strip().lower()
    if not settings.voice_enabled or requested == "disabled":
        return "disabled", "语音已关闭或未启用"
    if requested not in ("auto", "dashscope", "minimax", "volcengine"):
        return "disabled", f"未知 TTS 供应商：{requested}"
    if requested == "volcengine":
        return "disabled", "火山豆包语音适配器待接入（Step 8），请用 minimax 或 dashscope"
    if requested == "dashscope":
        if settings.dashscope_api_key:
            return "dashscope", None
        return "disabled", "未配置 DASHSCOPE_API_KEY，语音合成不可用"
    if requested == "minimax":
        if settings.minimax_api_key:
            return "minimax", None
        return "disabled", "未配置 MINIMAX_API_KEY，语音合成不可用"
    # auto：优先 MiniMax 主声，其次 DashScope
    if settings.minimax_api_key:
        return "minimax", None
    if settings.dashscope_api_key:
        return "dashscope", None
    return "disabled", "未配置任何 TTS 云供应商（MINIMAX_API_KEY / DASHSCOPE_API_KEY）"
