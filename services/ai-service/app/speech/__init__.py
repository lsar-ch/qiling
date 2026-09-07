"""语音模块：云供应商适配（DashScope 已实现，火山预留）。"""

from app.speech.base import (
    AudioResult,
    DisabledRecognizer,
    DisabledSynthesizer,
    SpeechProviderError,
    SpeechRecognizer,
    SpeechStack,
    SpeechSynthesizer,
    SpeechUnavailable,
)

__all__ = [
    "AudioResult",
    "DisabledRecognizer",
    "DisabledSynthesizer",
    "SpeechProviderError",
    "SpeechRecognizer",
    "SpeechStack",
    "SpeechSynthesizer",
    "SpeechUnavailable",
]
