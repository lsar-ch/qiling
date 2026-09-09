"""健康检查。"""

from __future__ import annotations

import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from app.config import is_lite_mode

router = APIRouter(prefix="/api", tags=["system"])


def _voice_pipeline(request: Request) -> dict[str, Any]:
    """语音链路状态；不暴露任何密钥。lite 模式视为整体禁用。"""
    settings = request.app.state.settings
    if is_lite_mode(settings):
        return {
            "stt_ready": False,
            "tts_ready": False,
            "vad_working": False,
            "degradation_reason": "轻量模式已禁用语音",
        }
    stack = request.app.state.speech
    stt_ready = stack.recognizer.available
    tts_ready = stack.synthesizer.available
    if not stt_ready and not tts_ready:
        reason = "语音供应商未配置"
    elif not stt_ready:
        reason = "语音识别不可用"
    elif not tts_ready:
        reason = "语音合成不可用"
    else:
        reason = None
    return {
        "stt_ready": stt_ready,
        "tts_ready": tts_ready,
        "vad_working": stt_ready,  # V1 无独立 VAD 标志，等同 STT 可用
        "degradation_reason": reason,
    }


def _recent_activity(request: Request) -> list[dict[str, Any]]:
    """最近 5 条事件摘要，来自 EventHub 历史。"""
    items: list[dict[str, Any]] = []
    for item in request.app.state.event_hub.recent(limit=5):
        payload = item.get("payload") or {}
        if item.get("event_type") in ("conversation.input", "conversation.completed"):
            summary = str(payload.get("message") or payload.get("speak_text") or "").strip()
        elif item.get("event_type") == "conversation.response":
            summary = str(payload.get("message") or "").strip()
        elif item.get("event_type") == "speech.started":
            summary = "语音识别开始"
        else:
            task = payload.get("task")
            if isinstance(task, dict):
                summary = str(task.get("input") or task.get("title") or "").strip()
            else:
                summary = str(payload.get("message") or payload.get("executor") or "").strip()
        if not summary and payload:
            first = next(iter(payload.values()))
            summary = str(first).strip() if first is not None else ""
        items.append(
            {
                "event_type": item.get("event_type", "unknown"),
                "timestamp": item.get("timestamp", ""),
                "summary": summary[:120] or item.get("event_type", "unknown"),
            }
        )
    return items


def _memory_stats(request: Request) -> dict[str, Any]:
    """记忆统计：只暴露计数与布尔开关，不返回文件内容。"""
    settings = request.app.state.settings
    memory = request.app.state.memory
    try:
        total = sum(item.entry_count for item in memory.overview())
    except OSError:
        total = 0
    vault = Path(settings.obsidian_vault_path).expanduser()
    compiled = settings.memory_dir / "compiled" / "memory.md"
    last_compile = None
    try:
        if compiled.is_file():
            last_compile = datetime.fromtimestamp(
                compiled.stat().st_mtime, timezone.utc
            ).isoformat()
    except OSError:
        pass
    return {
        "total_entries": total,
        "obsidian_linked": settings.memory_mode == "obsidian_linked" and vault.is_dir(),
        "last_compile": last_compile,
    }


@router.get("/health")
async def health(request: Request) -> dict:
    """健康状态 + 发布前能力汇总；只暴露状态，不返回任何密钥或本地文件。"""
    settings = request.app.state.settings
    registry = request.app.state.agent_registry
    agents = await registry.detect_all()
    ready = [agent.name for agent in agents if agent.available and agent.integration_status == "ready"]
    degraded = [
        {
            "name": agent.name,
            "integration_status": agent.integration_status,
        }
        for agent in agents
        if not (agent.available and agent.integration_status == "ready")
    ]
    uptime_s = round(time.time() - request.app.state.started_at, 1)
    return {
        "status": "ok",
        "service": "deskmate-ai-service",
        "version": settings.version,
        "performance_mode": settings.performance_mode,
        "voice_pipeline": _voice_pipeline(request),
        "recent_activity": _recent_activity(request),
        "memory_stats": _memory_stats(request),
        "time": datetime.now(timezone.utc).isoformat(),
        "uptime_s": uptime_s,
        "python": platform.python_version(),
        "features": ["health", "events", "memory", "agents"],
        "capabilities": {
            "text_chat": True,
            "voice": request.app.state.speech.voice_enabled,
            "memory": True,
            "agents": {
                "default_executor": registry.default_executor,
                "ready": ready,
                "degraded": degraded,
            },
        },
    }
