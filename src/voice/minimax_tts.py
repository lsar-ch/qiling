"""
MiniMax TTS 合成器：文本 → 音频。

使用MiniMax HTTP API进行语音合成。
"""
import asyncio
import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)


class MiniMaxTTSSynthesizer:
    """MiniMax文本转语音合成器。"""

    def __init__(self, voice: str = "xiaoming", model: str = "speech-01-turbo", 
                 rate: float = 1.0, api_key: Optional[str] = None):
        self.voice = voice
        self.model = model
        self.rate = rate
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY")
        
        if not self.api_key:
            raise ValueError("MiniMax API key not provided. Set MINIMAX_API_KEY environment variable.")
        
        self.base_url = "https://api.minimax.chat/v1/text_to_speech"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def _adjust_rate_for_api(self, text: str) -> str:
        """根据语速调整文本长度。"""
        # MiniMax API不支持语速调整，我们需要通过文本长度来模拟
        if self.rate > 1.0:
            # 加快语速：缩短文本
            words = text.split()
            new_length = int(len(words) / self.rate)
            return ' '.join(words[:new_length])
        elif self.rate < 1.0:
            # 减慢语速：重复文本
            repeat_count = int(1 / self.rate)
            return ' '.join([text] * repeat_count)
        return text

    async def synthesize_async(
        self,
        text: str,
        output_path: str | Path,
    ) -> Path:
        """异步合成语音（使用MiniMax HTTP API）。"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 调整文本以模拟语速变化
        adjusted_text = self._adjust_rate_for_api(text)
        
        # 构建请求
        data = {
            "model": self.model,
            "text": adjusted_text,
            "voice_id": self.voice,
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3"
            }
        }

        try:
            response = self.session.post(self.base_url, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if "base_resp" in result:
                base_resp = result["base_resp"]
                if base_resp["status_code"] == 0:
                    # 解码base64音频数据
                    audio_data = base64.b64decode(result["base64"])
                    with open(output_path, "wb") as f:
                        f.write(audio_data)
                    logger.debug(f"MiniMax TTS saved: {output_path}")
                    return output_path
                else:
                    error_msg = base_resp.get("status_msg", "Unknown error")
                    raise RuntimeError(f"MiniMax API error: {error_msg}")
            else:
                raise RuntimeError(f"Invalid API response: {result}")
                
        except requests.RequestException as e:
            logger.error(f"MiniMax API request failed: {e}")
            raise RuntimeError(f"MiniMax API request failed: {e}")

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
        """合成并立即播放。"""
        if output_path is None:
            import tempfile
            output_path = Path(tempfile.mktemp(suffix=".mp3"))
        
        self.synthesize(text, output_path)
        return output_path
