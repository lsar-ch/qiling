"""
TTS 合成器：文本 → 音频。

支持：
- edge-tts（微软 Edge 在线 TTS，免费高质量）
- piper-tts（本地，完全离线）
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TTSSynthesizer:
    """文本转语音合成器。"""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural", rate: float = 1.0):
        self.voice = voice
        self.rate = rate
        self._edge_tts_available = False

        try:
            import edge_tts  # noqa: F401
            self._edge_tts_available = True
            logger.info("edge-tts available")
        except ImportError:
            logger.warning("edge-tts not installed, TTS will not work")

    async def synthesize_async(
        self,
        text: str,
        output_path: str | Path,
    ) -> Path:
        """异步合成语音（使用 edge-tts）。"""
        if not self._edge_tts_available:
            raise RuntimeError("edge-tts not installed")

        import edge_tts

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(text, self.voice, rate=f"{self.rate * 100:+.0f}%")
        await communicate.save(str(output_path))
        logger.debug(f"TTS saved: {output_path}")
        return output_path

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
    ) -> Path:
        """同步合成语音。"""
        return asyncio.run(self.synthesize_async(text, output_path))

    def speak_now(
        self,
        text: str,
        output_path: str | Path = None,
    ) -> Path:
        """合成并立即播放（流式播放，不等全部生成完）。

        TODO: 实现边生成边播放的流式 TTS
        """
        if output_path is None:
            import tempfile
            output_path = Path(tempfile.mktemp(suffix=".mp3"))
        self.synthesize(text, output_path)
        return output_path
