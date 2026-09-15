"""DeskMate AI Service 入口。

启动方式（工作目录 services/ai-service）：
    .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8736
"""

from __future__ import annotations

import time
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agents.factory import build_agent_registry
from app.agents.catalog import load_agent_catalog
from app.agents.runtime import AgentRunManager, AgentRunStore
from app.api import agent_runs, agents, chat, events, health, memories, recording, session, settings as settings_api, state, tasks, voice
from app.chat.store import ConversationStore
from app.memory import MemoryService
from app.routing import TaskStore
from app.speech.base import SpeechStack
from app.speech.factory import build_speech_stack
from app.config import Settings, resolve_llm_provider
from app.core.state_mapper import WidgetStateRegistry, make_composed_hook
from app.core.presentation_bridge import PresentationBridge
from app.llm import LLMProvider, create_provider
from app.config import Settings, load_settings
from app.core.bus import EventHub


class VoiceLease:
    def __init__(self, ttl_seconds: float = 12.0) -> None:
        self.owner: str | None = None
        self.expires_at = 0.0
        self.ttl_seconds = ttl_seconds
        self.lock = asyncio.Lock()

    async def acquire(self, client: str) -> bool:
        async with self.lock:
            now = time.monotonic()
            if self.owner is None or self.expires_at <= now or client == "web":
                self.owner = client
                self.expires_at = now + self.ttl_seconds
                return True
            return self.owner == client

    async def heartbeat(self, client: str) -> bool:
        async with self.lock:
            if self.owner != client or self.expires_at <= time.monotonic():
                return False
            self.expires_at = time.monotonic() + self.ttl_seconds
            return True

    async def release(self, client: str) -> None:
        async with self.lock:
            if self.owner == client:
                self.owner = None
                self.expires_at = 0.0

    async def is_owner(self, client: str) -> bool:
        async with self.lock:
            return self.owner == client and self.expires_at > time.monotonic()


def create_app(
    settings: Settings | None = None,
    llm_provider: LLMProvider | None = None,
    speech: SpeechStack | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    widget_state = WidgetStateRegistry()
    hub = EventHub(on_publish=make_composed_hook(widget_state))
    presentation_bridge = PresentationBridge(settings.personas_dir)
    provider = llm_provider or create_provider(settings)
    speech = speech or build_speech_stack(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.memory_dir.mkdir(parents=True, exist_ok=True)
        (settings.data_dir / "run").mkdir(parents=True, exist_ok=True)
        # 启动时广播当前角色呈现
        if settings.active_persona_id:
            await presentation_bridge.broadcast(settings.active_persona_id, hub)
        yield

    app = FastAPI(
        title="DeskMate AI Service",
        version=settings.version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.started_at = time.time()
    app.state.session_id = f"session_{uuid4().hex[:10]}"
    app.state.event_hub = hub
    app.state.widget_state = widget_state
    app.state.presentation_bridge = presentation_bridge
    app.state.conversation_store = ConversationStore(settings.data_dir)
    app.state.task_store = TaskStore(settings.data_dir)
    app.state.memory = MemoryService(settings.memory_dir, persona_dir=settings.personas_dir)
    app.state.agent_catalog = load_agent_catalog()
    app.state.agent_registry = build_agent_registry(app.state.agent_catalog)
    app.state.agent_run_manager = AgentRunManager(
        registry=app.state.agent_registry,
        store=AgentRunStore(settings.data_dir),
        task_store=app.state.task_store,
        hub=hub,
        memory=app.state.memory,
        data_dir=settings.data_dir,
        conversations=app.state.conversation_store,
    )
    app.state.llm_provider = provider
    app.state.speech = speech
    app.state.voice_lease = VoiceLease()
    app.state.echo_mode = resolve_llm_provider(settings) == "echo"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(agents.router)
    app.include_router(agent_runs.router)
    app.include_router(session.router)
    app.include_router(events.router)
    app.include_router(state.router)
    app.include_router(chat.router)
    app.include_router(tasks.router)
    app.include_router(voice.router)
    app.include_router(settings_api.router)
    app.include_router(memories.router)
    app.include_router(recording.router)

    # 生产模式：主界面由 ai-service 托管（apps/web 构建产物）
    dist = settings.web_dist_dir
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app


app = create_app()
