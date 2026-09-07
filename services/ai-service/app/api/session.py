"""会话信息：给主界面/挂件标识当前服务实例。"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/session")
async def session_info(request: Request) -> dict:
    settings = request.app.state.settings
    base = str(request.base_url).rstrip("/")
    ws_url = base.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    ws_url += "/api/events"
    return {
        "session_id": request.app.state.session_id,
        "service_url": settings.service_url,
        "ws_url": ws_url,
        "auth_required": False,  # Step 1 仅本机；后续加会话令牌
        "capabilities": {
            "text_chat": True,    # Step 3 已接入
            "voice": request.app.state.speech.voice_enabled,  # Step 4
            "memory": True,       # Step 5：本地项目记忆
            "codex": False,       # Step 6 接入
        },
        "model": {
            "echo_mode": request.app.state.echo_mode,
            "provider": getattr(request.app.state.llm_provider, "display_name", ""),
        },
        "voice": {
            "stt_provider": request.app.state.speech.recognizer.name,
            "tts_provider": request.app.state.speech.synthesizer.name,
            "default_voice": request.app.state.speech.tts_voice,
        },
    }
