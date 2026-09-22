"""
TTS 合成器：文本 → 音频。

支持：
- edge-tts（微软 Edge 在线 TTS，免费高质量）
- minimax（MiniMax 在线 TTS，高质量中文语音）
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class TTSSynthesizer:
    """文本转语音合成器。"""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural", rate: float = 1.0, 
                 provider: Optional[str] = None, config_path: Optional[str] = None):
        self.voice = voice
        self.rate = rate
        self.provider = provider or self._detect_provider(config_path)
        self._edge_tts_available = False
        self._minimax_available = False

        # 检查依赖
        if self.provider == "edge-tts":
            try:
                import edge_tts  # noqa: F401
                self._edge_tts_available = True
                logger.info("edge-tts available")
            except ImportError:
                logger.warning("edge-tts not installed, TTS will not work")
        
        elif self.provider == "minimax":
            try:
                from .minimax_tts import MiniMaxTTSSynthesizer
                self._minimax_available = True
                logger.info("MiniMax TTS available")
            except ImportError:
                logger.warning("MiniMax TTS not available, check dependencies")

    def _detect_provider(self, config_path: Optional[str] = None) -> str:
        """自动检测TTS提供商。"""
        if config_path:
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                voice_cfg = config.get('voice', {})
                return voice_cfg.get('tts', {}).get('provider', 'edge-tts')
            except Exception:
                pass
        
        # 默认使用edge-tts
        return 'edge-tts'

    async def synthesize_async(
        self,
        text: str,
        output_path: str | Path,
    ) -> Path:
        """异步合成语音。"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.provider == "edge-tts" and self._edge_tts_available:
            return await self._synthesize_edge_tts_async(text, output_path)
        elif self.provider == "minimax" and self._minimax_available:
            from .minimax_tts import MiniMaxTTSSynthesizer
            minimax_tts = MiniMaxTTSSynthesizer(
                voice=self.voice,
                rate=self.rate
            )
            return await minimax_tts.synthesize_async(text, output_path)
        else:
            raise RuntimeError(f"TTS provider '{self.provider}' not available")

    async def _synthesize_edge_tts_async(
        self,
        text: str,
        output_path: str | Path,
    ) -> Path:
        """使用edge-tts异步合成语音。"""
        import edge_tts

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
        """合成并立即播放（流式播放，不等全部生成完）。"""
        if output_path is None:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                output_path = Path(tmp.name)
        self.synthesize(text, output_path)
        return output_path
