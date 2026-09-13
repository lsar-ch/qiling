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
    VoiceOption,
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


# CosyVoice 预置音色（官方音色列表页 https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list）。
# 关键约束：音色按 model 分组，不同 model 的音色不能混用，所以这里按模型给集合，
# 而不是给一份混合大列表。DashScope 没有「列出预置音色」的接口，这里只做常用集合，
# 账号下复刻的克隆音色在运行时通过 list_voices() 追加。
_COSYVOICE_PRESETS: dict[str, list[tuple[str, str]]] = {
    "cosyvoice-v1": [
        ("longwan", "龙婉"),
        ("longcheng", "龙橙"),
        ("longhua", "龙华"),
        ("longxiaochun", "龙小淳"),
        ("longxiaoxia", "龙小夏"),
        ("longxiaocheng", "龙小诚"),
        ("longxiaobai", "龙小白"),
        ("longlaotie", "龙老铁"),
        ("longshu", "龙书"),
        ("longshuo", "龙硕"),
        ("longjing", "龙婧"),
        ("longmiao", "龙妙"),
        ("longyue", "龙悦"),
        ("longyuan", "龙媛"),
        ("longfei", "龙飞"),
        ("longjielidou", "龙杰力豆"),
        ("longtong", "龙彤"),
        ("longxiang", "龙祥"),
        ("loongstella", "Stella"),
        ("loongbella", "Bella"),
    ],
    "cosyvoice-v2": [
        ("longxiaochun_v2", "龙小淳（v2）"),
        ("longxiaoxia_v2", "龙小夏（v2）"),
        ("longjing_v2", "龙婧（v2）"),
        ("longxiaobai_v2", "龙小白（v2）"),
    ],
    "cosyvoice-v3-flash": [
        ("longanyang", "龙安洋"),
        ("longanhuan", "龙安欢"),
        ("longanhuan_v3", "龙安欢（V3）"),
        ("longhuhu_v3", "龙呼呼"),
    ],
}


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

    def _preset_voices(self) -> list[VoiceOption]:
        model = (self._model or "").strip().lower()
        if model in _COSYVOICE_PRESETS:
            presets = _COSYVOICE_PRESETS[model]
        else:
            # 未知/其它版本：按前缀归族，例如 cosyvoice-v2.5 → v2 集合
            presets = next(
                (items for key, items in _COSYVOICE_PRESETS.items() if model.startswith(key)),
                [],
            )
        return [
            VoiceOption(id=voice_id, name=name, kind="preset")
            for voice_id, name in presets
        ]

    def _enrolled_voices(self) -> list[VoiceOption]:
        """账号下复刻的克隆音色；SDK 不可用或调用失败时不影响预置列表。"""
        try:
            from dashscope.audio.tts_v2 import VoiceEnrollmentService
        except ImportError:
            return []
        try:
            service = VoiceEnrollmentService(api_key=self._api_key)
            items = service.list_voices(page_size=50) or []
        except Exception:
            return []

        voices: list[VoiceOption] = []
        for item in items:
            voice_id = ""
            if isinstance(item, dict):
                voice_id = str(item.get("voice_id") or "").strip()
            elif isinstance(item, str):
                voice_id = item.strip()
            if voice_id:
                voices.append(VoiceOption(id=voice_id, kind="cloned"))
        return voices

    def _list_voices_sync(self) -> list[VoiceOption]:
        if not self._api_key:
            raise SpeechUnavailable("未配置 DASHSCOPE_API_KEY，语音合成不可用")
        seen = set()
        voices: list[VoiceOption] = []
        for item in self._preset_voices() + self._enrolled_voices():
            if item.id in seen:
                continue
            seen.add(item.id)
            voices.append(item)
        return voices

    async def list_voices(self) -> list[VoiceOption]:
        return await asyncio.to_thread(self._list_voices_sync)

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
