"""语音契约（对应 docs/VOICE-PROVIDERS.md）。

设计原则：
- 供应商可替换：stt / tts 各自独立配置 provider。
- 系统侧只维护「表现参数」（speed / pitch / volume / emotion / instruction），
  具体供应商适配层负责把归一化参数映射到厂商字段。
- 未配置任何云供应商时服务优雅降级为 disabled，不影响文字对话。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VoiceProvider = Literal[
    "auto",       # 按配置自动选择
    "dashscope",  # 阿里云百炼（CosyVoice / Paraformer）
    "minimax",    # MiniMax（speech-2.8-hd，主声/克隆音）
    "volcengine", # 火山引擎豆包语音（预留）
    "disabled",   # 未配置 / 显式关闭
]


class VoiceParams(BaseModel):
    """TTS 表现参数（归一化），由适配层映射到厂商字段。

    - speed / pitch 范围 0.5 ~ 2.0，1.0 为厂商默认；
    - volume 范围 0 ~ 2.0，1.0 为厂商默认；
    - emotion / instruction 为可选风格槽位，V1 不要求供应商实现。
    """

    voice: str | None = Field(default=None, description="供应商音色标识")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    emotion: str | None = Field(default=None, description="情感/风格标签（供应商可选）")
    instruction: str | None = Field(
        default=None, description="风格/口音自然语言描述，如温柔、台湾腔（供应商可选）"
    )
    language: str = "zh"

    model_config = {"extra": "forbid"}


class VoiceSettings(BaseModel):
    """语音总配置：STT / TTS 供应商 + 默认表现参数。"""

    enabled: bool = True
    stt_provider: str = "auto"
    stt_model: str = "paraformer-realtime-v2"
    tts_provider: str = "auto"
    tts_model: str = "cosyvoice-v2"
    default_voice: str = "longxiaochun_v2"   # 阿里 CosyVoice 知性女声
    params: VoiceParams = Field(default_factory=VoiceParams)
    interruption_enabled: bool = True
    auto_barge_in: bool = False               # V1 用按钮打断，后续升级自动抢话

    model_config = {"extra": "forbid"}
