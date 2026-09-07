"""语音适配层抽象：识别器 / 合成器 / 统一异常。

V1 形态：整句录音 → recognize → 文本走现有对话链路 → 整句 synthesize → 播放。
接口按全双工（流式）设计留扩展位：后续换流式供应商时替换实现即可。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from deskmate_contracts.voice import VoiceParams


class SpeechUnavailable(RuntimeError):
    """语音供应商未配置 / 不可用（前端应给出明确提示，而非报错轰炸）。"""


class SpeechProviderError(RuntimeError):
    """云供应商调用失败（网络、鉴权、限流等）。"""


@dataclass
class AudioResult:
    data: bytes
    format: str = "wav"          # wav | mp3 | pcm
    sample_rate: int = 24000


class SpeechRecognizer(ABC):
    name = "unavailable"

    @property
    def available(self) -> bool:
        return True

    @abstractmethod
    async def recognize(self, wav_path: str, language: str = "zh") -> str:
        """识别本地 WAV 音频，返回转写文本。"""


class SpeechSynthesizer(ABC):
    name = "unavailable"

    @property
    def available(self) -> bool:
        return True

    @abstractmethod
    async def synthesize(self, text: str, params: VoiceParams | None = None) -> AudioResult:
        """合成文本，返回音频字节。params 为空时使用供应商默认参数。"""


class DisabledRecognizer(SpeechRecognizer):
    name = "disabled"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    @property
    def available(self) -> bool:
        return False

    async def recognize(self, wav_path: str, language: str = "zh") -> str:
        raise SpeechUnavailable(self._reason)


class DisabledSynthesizer(SpeechSynthesizer):
    name = "disabled"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    @property
    def available(self) -> bool:
        return False

    async def synthesize(self, text: str, params: VoiceParams | None = None) -> AudioResult:
        raise SpeechUnavailable(self._reason)


@dataclass
class SpeechStack:
    """一组可用的识别器 + 合成器 + 描述信息。"""
    recognizer: SpeechRecognizer
    synthesizer: SpeechSynthesizer
    tts_model: str
    tts_voice: str
    tts_format: str = "wav"
    tts_sample_rate: int = 24000
    stt_model: str = "paraformer-realtime-v2"
    params: VoiceParams | None = None

    @property
    def voice_enabled(self) -> bool:
        return self.recognizer.available and self.synthesizer.available
