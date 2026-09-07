"""阿里云百炼 DashScope 语音适配器（已核实官方 SDK dashscope 1.27.x）。

- TTS：cosyvoice-v2 SpeechSynthesizer（WebSocket 封装，call() 返回完整音频字节）。
- STT：paraformer-realtime-v2 Recognition（其 call(file) 支持本地 wav 一次性识别）。

设计：dashscope 为可选依赖（pip install dashscope），导入放在运行时，
未安装或未配置 key 时由 factory 层降级，不让服务启动失败。
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from deskmate_contracts.voice import VoiceParams

from app.speech.base import (
    AudioResult,
    SpeechProviderError,
    SpeechRecognizer,
    SpeechSynthesizer,
    SpeechUnavailable,
)

_INSTALL_HINT = "未安装 dashscope SDK，请执行：.venv/bin/pip install dashscope"

_WAV_FORMATS: dict[int, str] = {
    8000: "WAV_8000HZ_MONO_16BIT",
    16000: "WAV_16000HZ_MONO_16BIT",
    22050: "WAV_22050HZ_MONO_16BIT",
    24000: "WAV_24000HZ_MONO_16BIT",
    44100: "WAV_44100HZ_MONO_16BIT",
    48000: "WAV_48000HZ_MONO_16BIT",
}
_MP3_FORMATS: dict[int, str] = {
    16000: "MP3_16000HZ_MONO_128KBPS",
    24000: "MP3_24000HZ_MONO_256KBPS",
}


def _nearest(choices: Sequence[int], target: int) -> int:
    return min(choices, key=lambda x: abs(x - target))


class DashScopeRecognizer(SpeechRecognizer):
    name = "dashscope"

    def __init__(
        self,
        api_key: str,
        model: str = "paraformer-realtime-v2",
        sample_rate: int = 16000,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._sample_rate = sample_rate

    def _recognize_sync(self, wav_path: str) -> str:
        try:
            import dashscope  # noqa: WPS433
            from dashscope.audio.asr.recognition import Recognition, RecognitionCallback
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise SpeechUnavailable(_INSTALL_HINT) from exc

        dashscope.api_key = self._api_key

        class _Noop(RecognitionCallback):  # call() 全量模式下不需要事件回调
            pass

        try:
            recognition = Recognition(
                model=self._model,
                callback=_Noop(),
                format="wav",
                sample_rate=self._sample_rate,
            )
            result = recognition.call(wav_path)
        except Exception as exc:
            raise SpeechProviderError(f"DashScope 语音识别失败：{exc}") from exc

        sentence = result.get_sentence()
        if not sentence:
            return ""
        items = sentence if isinstance(sentence, list) else [sentence]
        return "".join(str(s.get("text", "")) for s in items if isinstance(s, dict)).strip()

    async def recognize(self, wav_path: str, language: str = "zh") -> str:
        return await asyncio.to_thread(self._recognize_sync, wav_path)


class DashScopeSynthesizer(SpeechSynthesizer):
    name = "dashscope"

    def __init__(
        self,
        api_key: str,
        model: str = "cosyvoice-v2",
        voice: str = "longxiaochun_v2",
        fmt: str = "wav",
        sample_rate: int = 24000,
        defaults: VoiceParams | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._fmt = fmt
        self._sample_rate = sample_rate
        self._defaults = defaults or VoiceParams()

    def _synthesize_sync(self, text: str, params: VoiceParams | None) -> AudioResult:
        try:
            from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
        except ImportError as exc:  # pragma: no cover
            raise SpeechUnavailable(_INSTALL_HINT) from exc

        merged = params or self._defaults
        voice = merged.voice or self._voice
        audio_format = self._resolve_audio_format()
        # DashScope volume 范围 0~100（默认 50），volume=1.0 → 50
        volume = max(0, min(100, int(round(50 * merged.volume))))
        instruction = merged.instruction or None
        def _build(with_instruction: bool):
            return SpeechSynthesizer(
                model=self._model,
                voice=voice,
                format=audio_format,
                volume=volume,
                speech_rate=max(0.5, min(2.0, merged.speed)),
                pitch_rate=max(0.5, min(2.0, merged.pitch)),
                instruction=instruction if with_instruction else None,
            )

        synthesizer = _build(instruction is not None)
        try:
            try:
                data = synthesizer.call(text)
            except Exception as exc:
                # 428 = 当前音色/账号不支持 instruction（预置音色常见），去掉后重试一次
                if instruction is not None and "428" in str(exc):
                    synthesizer.close()
                    synthesizer = _build(False)
                    data = synthesizer.call(text)
                else:
                    raise
        except Exception as exc:
            raise SpeechProviderError(f"DashScope 语音合成失败：{exc}") from exc
        finally:
            try:
                synthesizer.close()
            except Exception:
                pass
        if not data:
            raise SpeechProviderError("DashScope 语音合成返回空音频")
        return AudioResult(data=data, format=self._fmt, sample_rate=self._sample_rate)

    def _resolve_audio_format(self):
        from dashscope.audio.tts_v2 import AudioFormat

        if self._fmt == "mp3":
            rate = _nearest(list(_MP3_FORMATS), self._sample_rate)
            return getattr(AudioFormat, _MP3_FORMATS[rate])
        rate = _nearest(list(_WAV_FORMATS), self._sample_rate)
        return getattr(AudioFormat, _WAV_FORMATS[rate])

    async def synthesize(self, text: str, params: VoiceParams | None = None) -> AudioResult:
        return await asyncio.to_thread(self._synthesize_sync, text, params)
