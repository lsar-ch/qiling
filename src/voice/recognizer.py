"""
STT 识别器：麦克风音频 → 文本。

支持：
- faster-whisper（本地，高质量）
- openai-whisper（备选）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class STTRecognizer:
    """语音转文字识别器。"""

    def __init__(self, model_size: str = "small", language: str = "zh"):
        self.model_size = model_size
        self.language = language
        self._model = None
        self._device = "cpu"

        logger.info(f"STTRecognizer initialized: model={model_size}, lang={language}")

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_size,
                device=self._device,
                compute_type="int8",
            )
            logger.info("faster-whisper model loaded")
        except ImportError:
            logger.error("faster-whisper not installed, run: pip install faster-whisper")
            raise

    def transcribe(self, audio_path: str | Path) -> str:
        """将音频文件转写为文本。"""
        self._load_model()
        segments, info = self._model.transcribe(
            str(audio_path),
            language=self.language,
            beam_size=5,
        )
        text = "".join(segment.text for segment in segments)
        logger.debug(f"STT result: '{text.strip()}' (lang={info.language}, prob={info.language_probability:.2f})")
        return text.strip()
