"""
核心 Agent：协调语音、LLM、记忆、UI 的总调度器。

工作流程：
1. VAD 检测用户说话 → 2. STT 转文字 → 3. 检索记忆 → 4. LLM 生成回复 → 5. TTS 合成并播放 → 6. 记忆归档

参考 Warashi 的语音打断机制 + Soul-of-Waifu 的记忆架构。
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from .llm.agent import LLMClient
from .memory.store import MemoryStore
from .memory.retriever import MemoryRetriever
from .voice.recognizer import STTRecognizer
from .voice.synthesizer import TTSSynthesizer
from .voice.vad import VADDetector
from .viz.renderer import create_renderer

logger = logging.getLogger(__name__)


class DeskMateAgent:
    """桌面 AI 精灵主控制器。"""

    def __init__(
        self,
        ui_controller,
        settings: dict,
    ):
        self.ui = ui_controller
        self.settings = settings

        # ── 初始化各模块 ────────────────────────────────────────
        voice_cfg = settings.get("voice", {})
        llm_cfg = settings.get("llm", {})
        memory_cfg = settings.get("memory", {})

        self.stt = STTRecognizer(
            model_size=voice_cfg.get("stt", {}).get("model", "small"),
            language=voice_cfg.get("stt", {}).get("language", "zh"),
        )
        self.tts = TTSSynthesizer(
            voice=voice_cfg.get("tts", {}).get("voice", "zh-CN-XiaoxiaoNeural"),
            rate=voice_cfg.get("tts", {}).get("rate", 1.0),
        )
        self.vad = VADDetector(
            agent=voice_cfg.get("vad", {}).get("agent", "webrtcvad"),
            threshold=voice_cfg.get("vad", {}).get("threshold", 0.5),
        )
        self.llm = LLMClient(
            provider=llm_cfg.get("provider", "ollama"),
            model=llm_cfg.get("model", "qwen3:8b"),
            base_url=llm_cfg.get("base_url", "http://localhost:11434"),
            system_prompt_path=settings.get("llm", {}).get("system_prompt_path", ""),
        )
        self.memory = MemoryStore(
            db_path=memory_cfg.get("db_path", "./data/memory/chat_history.db"),
        )
        self.retriever = MemoryRetriever(self.memory)

        # ── 渲染器 ──────────────────────────────────────────────
        ui_mode = settings.get("ui", {}).get("mode", "floating_spring")
        self.renderer = create_renderer(ui_controller, mode=ui_mode)

        # ── 运行状态 ─────────────────────────────────────────────
        self._running = False
        self._listen_thread: threading.Thread | None = None
        self._current_response = ""
        self._interrupted = False

        logger.info("DeskMateAgent initialized")

    # ── 生命周期 ─────────────────────────────────────────────────
    def start(self) -> None:
        """启动精灵。"""
        self._running = True
        self.ui.set_state("idle")
        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listen_thread.start()
        logger.info("Agent started, listening...")

    def stop(self) -> None:
        """停止精灵。"""
        self._running = False
        if self._listen_thread:
            self._listen_thread.join(timeout=2.0)
        self.ui.set_state("idle")
        self.memory.close()
        logger.info("Agent stopped")

    # ── 主监听循环 ──────────────────────────────────────────────
    def _listen_loop(self) -> None:
        """持续监听麦克风，检测语音并处理对话。"""
        import sounddevice as sd
        import numpy as np

        sample_rate = 16000
        chunk_size = int(sample_rate * 0.02)  # 20ms 块

        logger.info(f"Audio listener started: {sample_rate}Hz")

        with sd.InputStream(
            channels=1,
            samplerate=sample_rate,
            dtype="int16",
            blocksize=chunk_size,
        ) as stream:
            while self._running:
                try:
                    data, overflowed = stream.read(chunk_size)
                    if overflowed:
                        logger.warning("Audio buffer overflow")

                    # VAD 检测
                    vad_result = self.vad.check(data.tobytes())

                    if vad_result.is_speech:
                        # 检测到说话开始，进入 listening 状态
                        self.ui.set_state("listening")
                        audio_buffer = bytearray(data.tobytes())
                        silence_frames = 0
                        max_silence_frames = int(
                            self.settings.get("voice", {}).get("vad", {}).get("pause_threshold_ms", 600)
                            / 20
                        )

                        # 持续录音直到检测到静音
                        while self._running and silence_frames < max_silence_frames:
                            data2, _ = stream.read(chunk_size)
                            vad2 = self.vad.check(data2.tobytes())
                            if vad2.is_speech:
                                silence_frames = 0
                                audio_buffer.extend(data2.tobytes())
                            else:
                                silence_frames += 1
                                if silence_frames < 3:  # 短暂静音不结束
                                    audio_buffer.extend(data2.tobytes())

                        # 处理录制的音频
                        if len(audio_buffer) > 0:
                            self._process_audio(bytes(audio_buffer))

                except Exception as e:
                    logger.error(f"Audio loop error: {e}", exc_info=True)
                    time.sleep(0.1)

    def _process_audio(self, audio_bytes: bytes) -> None:
        """处理一段语音：STT → LLM → TTS。"""
        # 1. 保存临时音频文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            # 简单 PCM 头（16kHz, mono, 16-bit）
            import struct
            f.write(struct.pack("<4sI4sIHHII4s",
                b"RIFF", 36 + len(audio_bytes), b"WAVE", b"fmt ",
                16, 1, 1, 16000, 32000, 2, 16,
                b"data", len(audio_bytes)
            ))
            f.write(audio_bytes)
            audio_path = f.name

        try:
            # 2. STT
            logger.debug("Transcribing...")
            text = self.stt.transcribe(audio_path)
            if not text:
                logger.debug("Empty transcription, skipping")
                return
            logger.info(f"User said: '{text}'")

            # 3. 构建记忆上下文
            context = self.retriever.retrieve_context(text, recent_limit=10, memory_limit=3)
            messages = context.to_messages(self.llm)
            messages.append({"role": "user", "content": text})

            # 4. 记录用户消息到记忆
            self.memory.add_message(role="user", content=text)

            # 5. LLM 生成回复（流式）
            self.ui.set_state("thinking")
            response_chunks = []

            def collect_chunks():
                for chunk in self.llm.chat(messages, stream=True):
                    if self._interrupted:
                        break
                    response_chunks.append(chunk)

            # 6. TTS 边生成边播放（流式）
            self.ui.set_state("speaking")
            full_response = ""

            # TODO: 实现真正的流式 TTS（边生成边播放）
            # 当前实现：先收集完整回复再生成音频
            thread = threading.Thread(target=collect_chunks, daemon=True)
            thread.start()
            thread.join()

            full_response = "".join(response_chunks)
            if not full_response:
                logger.warning("Empty response from LLM")
                return

            # 7. TTS 合成并播放
            logger.debug(f"Synthesizing TTS: '{full_response[:50]}...'")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tts_path = f.name

            try:
                self.tts.synthesize(full_response, tts_path)
                self._play_audio(tts_path)
            except Exception as e:
                logger.error(f"TTS error: {e}")
                # Fallback: 文字转语音用系统 TTS
                self._fallback_speak(full_response)

            # 8. 记录助手回复到记忆
            self.memory.add_message(role="assistant", content=full_response)

            # 9. 定期生成摘要
            stats = self.memory.get_stats()
            if stats["today_messages"] % 10 == 0 and stats["today_messages"] > 0:
                self._maybe_generate_summary()

            self.ui.set_state("idle")

        finally:
            import os
            os.unlink(audio_path)

    def _play_audio(self, path: str) -> None:
        """播放音频文件。"""
        from PyQt6.QtMultimedia import QSoundEffect
        # 使用系统播放器
        import subprocess
        subprocess.run(["afplay", path], check=False, timeout=10)

    def _fallback_speak(self, text: str) -> None:
        """Fallback TTS（macOS 系统语音）。"""
        import subprocess
        subprocess.run(["say", "-v", "Ting-Ting", text], check=False)

    def _maybe_generate_summary(self) -> None:
        """检查是否需要生成对话摘要。"""
        # TODO: 实现摘要生成逻辑
        pass

    def manual_chat(self, text: str) -> str:
        """手动文本对话接口（绕过语音）。"""
        context = self.retriever.retrieve_context(text, recent_limit=10, memory_limit=3)
        messages = context.to_messages(self.llm)
        messages.append({"role": "user", "content": text})
        self.memory.add_message(role="user", content=text)

        response = self.llm.chat(messages, stream=False)
        self.memory.add_message(role="assistant", content=response)
        return response
