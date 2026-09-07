"""
VAD（Voice Activity Detection）语音活动检测。

用于：
1. 检测用户是否开始/结束说话（自动触发录音）
2. 检测新语音打断当前发言（自然打断机制）
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VADResult:
    speech_start: float | None = None   # 说话开始时间
    speech_end: float | None = None     # 说话结束时间
    is_speech: bool = False             # 当前是否有语音
    confidence: float = 0.0             # 置信度


class VADDetector:
    """基于 WebrtcVAD 或 Silero 的语音活动检测器。"""

    def __init__(self, agent: str = "webrtcvad", threshold: float = 0.5):
        self.agent = agent
        self.threshold = threshold
        self._vad = None
        self._sample_rate = 16000
        self._speech_buffer: list[float] = []
        self._last_speech_time: float = 0.0
        self._silence_start: float | None = None

        self._init_vad()

    def _init_vad(self) -> None:
        if self.agent == "webrtcvad":
            try:
                import webrtcvad
                self._vad = webrtcvad.Vad()
                self._vad.set_mode(3)  # 最敏感模式
                logger.info("WebrtcVAD initialized (mode=3)")
            except ImportError:
                logger.warning("webrtcvad not installed, VAD disabled")
        elif self.agent == "silero":
            try:
                import torch
                from silero_vad import load_silero_vad
                self._vad, _ = load_silero_vad()
                logger.info("Silero VAD initialized")
            except ImportError:
                logger.warning("silero-vad not installed, VAD disabled")

    def check(self, audio_chunk: bytes) -> VADResult:
        """检查一段音频是否有语音。

        Args:
            audio_chunk: 16kHz mono PCM 音频数据
        Returns:
            VADResult 检测结果
        """
        if self._vad is None:
            return VADResult(is_speech=False)

        # WebrtcVAD 需要 20ms 的块（16000 * 0.02 = 320 samples = 640 bytes for 16-bit）
        sample_rate = 16000
        frame_len = int(sample_rate * 0.02)

        if len(audio_chunk) < frame_len * 2:  # 16-bit = 2 bytes per sample
            return VADResult(is_speech=False)

        import struct
        samples = struct.unpack(f"{len(audio_chunk)//2}h", audio_chunk)

        is_speech = False
        for i in range(0, len(samples) - frame_len, frame_len):
            frame = samples[i:i + frame_len]
            # webrtcvad requires int16
            vad_result = self._vad.process(frame, sample_rate)
            if vad_result:
                is_speech = True
                break

        now = time.time()
        if is_speech:
            self._last_speech_time = now
            if self._silence_start is not None:
                # 刚刚从静音切换到说话
                pass
            self._silence_start = None
        else:
            if self._silence_start is None:
                self._silence_start = now

        return VADResult(
            is_speech=is_speech,
            confidence=0.8 if is_speech else 0.2,
            speech_start=self._silence_start,
        )

    def get_silence_duration(self) -> float:
        """获取当前静默时长（秒）。"""
        if self._silence_start is None:
            return 0.0
        return time.time() - self._silence_start
