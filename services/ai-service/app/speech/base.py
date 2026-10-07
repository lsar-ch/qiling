"""语音适配层抽象：识别器 / 合成器 / 统一异常。

V1 形态：整句录音 → recognize → 文本走现有对话链路 → 整句 synthesize → 播放。
接口按全双工（流式）设计留扩展位：后续换流式供应商时替换实现即可。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import re
from dataclasses import dataclass

from qiling_contracts.voice import VoiceParams


class SpeechUnavailable(RuntimeError):
    """语音供应商未配置 / 不可用（前端应给出明确提示，而非报错轰炸）。"""


class SpeechProviderError(RuntimeError):
    """云供应商调用失败（网络、鉴权、限流等）。"""


@dataclass
class AudioResult:
    data: bytes
    format: str = "wav"          # wav | mp3 | pcm
    sample_rate: int = 24000


@dataclass
class VoiceOption:
    """供应商音色条目，供设置页/角色卡选择绑定。"""

    id: str
    name: str = ""
    kind: str = "system"         # system | cloned

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name or self.id, "kind": self.kind}


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

    async def synthesize_stream(self, text: str, params: VoiceParams | None = None):
        """流式合成：按句子拆分，逐句合成后 yield AudioResult chunk。

        默认实现：按中英文标点分句 → 逐句调用 synthesize()。
        子类可覆盖为供应商原生流式 API。
        ponytail: 正则分句，不引入分词库。
        """
        sentences = _split_sentences(text)
        for sentence in sentences:
            if not sentence.strip():
                continue
            yield await self.synthesize(sentence, params)

    async def list_voices(self) -> list[VoiceOption]:
        """列出供应商可用音色。默认表示「不支持自动获取」，由前端回退到手填。"""
        return []


def _split_sentences(text: str) -> list[str]:
    """按中英文句子边界切分，保留标点附着在句尾。"""
    parts = re.split(r'(?<=[。！？；\n.!?;])\s*', text)
    merged: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if merged and len(p) < 4:
            merged[-1] = merged[-1] + p
        else:
            merged.append(p)
    return merged if merged else [text]

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
