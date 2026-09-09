"""录制会话契约（Step 10 接口预留）。

对应 docs/STEP10-DASHBOARD-AND-EXTENSIBILITY.md 模块 2。
V1 只建契约 + stub 端点，录制能力在后续版本实现。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class RecordingFormat(StrEnum):
    video_webm = "video/webm"
    video_mp4 = "video/mp4"
    audio_wav = "audio/wav"
    audio_mp3 = "audio/mpeg"


class RecordingMode(StrEnum):
    conversation = "conversation"           # 录制对话文本 + 音频
    task_execution = "task_execution"       # 录制任务执行过程 + 屏幕
    digital_human = "digital_human"         # 数字人口型 + 音频 + 画面


class RecordingSession(BaseModel):
    """一次录制会话的记录；V1 仅定义结构，不接真实录制。"""

    session_id: str = Field(default_factory=lambda: f"rec_{uuid4().hex[:10]}")
    conversation_id: str | None = None
    task_id: str | None = None
    mode: RecordingMode = RecordingMode.conversation
    format: RecordingFormat = RecordingFormat.video_webm
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: str | None = None
    output_path: str | None = None    # 本地文件路径
    duration_s: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "recording"         # recording | processing | completed | failed

    model_config = {"extra": "forbid"}
