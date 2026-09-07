"""健康检查。"""

from __future__ import annotations

import platform
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["system"])


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
