"""文字对话接口：SSE 流式回复 + 会话保存。"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Literal
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deskmate_contracts import new_event_id
from deskmate_contracts.events import EventEnvelope
from app.chat.context import build_llm_messages
from app.core.persona_prompt import compose_system_prompt, load_persona
from app.llm import create_provider
from app.model_profiles import find_model_profile, load_model_profiles, profile_settings
from app.routing import classify_task_input

router = APIRouter(prefix="/api", tags=["chat"])

_ECHO_STRIP = re.compile(r"[\s，。！？、,.!?'\"“”‘’；：:;…—\-()（）【】《》~～·]+")


def _is_echo_of_reply(message: str, conversation) -> bool:
    """识别文本与刚说过的回复高度重合时视为扬声器回采，不据此派后台任务。

    常开监听下扬声器声音会被麦克风回采，若不拦住，任务回执会被再当成新任务提交，
    形成「起任务 → 播报 → 回采 → 再起任务」的自激循环。
    """
    needle = _ECHO_STRIP.sub("", message).lower()
    if len(needle) < 6:
        return False
    recent = conversation.messages[-10:]  # 末条是本轮用户消息
    for prev in reversed(recent):
        if prev.role == "user" or prev.content is None:
            continue
        hay = _ECHO_STRIP.sub("", prev.content).lower()
        if not hay:
            continue
        if needle in hay or hay in needle:
            return True
        # 识别结果常有少量错字（如「你/已」），用相似度兜住
        if SequenceMatcher(None, needle, hay).ratio() >= 0.8:
            return True
    return False


class ChatTurnRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=8000)
    modality: Literal["text", "voice"] = "text"
    model_profile_id: str | None = None

    model_config = {"extra": "forbid"}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _system_prompt(request: Request) -> str:
    settings = request.app.state.settings
    persona = load_persona(settings.personas_dir, settings.active_persona_id)
    return compose_system_prompt(settings.system_prompt, persona)


def _persona_model_profile_id(request: Request) -> str | None:
    settings = request.app.state.settings
    persona = load_persona(settings.personas_dir, settings.active_persona_id)
    llm = persona.get("llm") if isinstance(persona, dict) and isinstance(persona.get("llm"), dict) else {}
    value = llm.get("profile_id")
    return str(value).strip() if value else None


def build_speak_text(answer: str, max_chars: int) -> str:
    """生成语音朗读文本：短回复返回全文；长回复返回开头整句组成的摘要。"""
    text = " ".join(answer.split()).strip()
    if not text or len(text) <= max_chars:
        return text
    sentences: list[str] = []
    cur: list[str] = []
    for ch in text:
        cur.append(ch)
        if ch in "。！？!?…~～":
            sentences.append("".join(cur))
            cur = []
    if cur:
        sentences.append("".join(cur))
    picked: list[str] = []
    for sent in sentences:
        if picked and len("".join(picked)) + len(sent) > max_chars:
            break
        picked.append(sent)
    speak = "".join(picked).strip()
    if not speak:
        speak = text[:max_chars].rstrip("，,、;；:： ")
    return speak


async def _run_turn(request: Request, body: ChatTurnRequest) -> AsyncIterator[str]:
    store = request.app.state.conversation_store
    hub = request.app.state.event_hub
    settings = request.app.state.settings
    memory = request.app.state.memory

    existing = await store.get(body.conversation_id) if body.conversation_id else None
    if "model_profile_id" in body.model_fields_set:
        conversation_profile_id: str | None = body.model_profile_id or ""
    else:
        conversation_profile_id = existing.model_profile_id if existing else None

    conversation = await store.append_message(
        body.conversation_id,
        "user",
        body.message,
        modality=body.modality,
        model_profile_id=conversation_profile_id,
    )
    conversation_id = conversation.conversation_id
    profiles = load_model_profiles(settings.repo_root)
    active_profile = find_model_profile(
        profiles,
        conversation.model_profile_id or _persona_model_profile_id(request),
    )
    provider = (
        create_provider(profile_settings(settings, active_profile))
        if active_profile is not None and active_profile.enabled
        else request.app.state.llm_provider
    )
    await hub.publish(
        EventEnvelope(
            event_type="conversation.input",
            source="conversation",
            conversation_id=conversation_id,
            payload={"message": body.message},
        )
    )
    task = classify_task_input(body.message, settings.permission_level)
    task.conversation_id = conversation_id
    task = request.app.state.task_store.put(task)
    await hub.publish(
        EventEnvelope(
            event_type="task.classified",
            source="task",
            conversation_id=conversation_id,
            task_id=task.task_id,
            payload=task.model_dump(mode="json"),
        )
    )
    if task.required_approval:
        await hub.publish(
            EventEnvelope(
                event_type="task.approval_required",
                source="task",
                conversation_id=conversation_id,
                task_id=task.task_id,
                payload={"reason": "risk_gate", "task": task.model_dump(mode="json")},
            )
        )
    # 后台任务直接起跑（read-only）：进度、报错、授权、结果都会写回本会话，
    # 不让用户再去「我的智能体」手动运行、翻找状态。
    # 只在分流器识别出后台特征（risk_level != low）时自动起跑：随口一句闲聊
    # 不该拉起真实 agent（这类任务仍会记进任务台，需要时手动运行）。
    auto_run = None
    auto_start_error = ""
    if (
        task.category == "delegate_backend"
        and task.risk_level != "low"
        and not _is_echo_of_reply(body.message, conversation)
    ):
        try:
            from app.agents.browser import is_browser_search

            executor = "browser" if is_browser_search(body.message) else None
            auto_run = await request.app.state.agent_run_manager.execute(
                task, mode="read-only", executor=executor
            )
        except Exception as exc:
            auto_start_error = str(exc)
    try:
        user_trace_id = memory.record_event(
            "conversation",
            "conversation.input",
            {"text": body.message, "modality": body.modality},
            session_id=request.app.state.session_id,
            turn_id=conversation_id,
        )
    except Exception:
        user_trace_id = ""

    try:
        if task.category == "request_approval":
            answer = "这类操作需要先确认，我已经挂起等待授权。"
            yield _sse({"type": "delta", "content": answer})
        elif task.category == "execute_frontend":
            answer = "我先把这个记为前台任务，任务台里会显示。"
            yield _sse({"type": "delta", "content": answer})
        elif auto_run is not None:
            answer = "收到，已交给后台执行；进度、报错和结果都会回到这条对话里。"
            yield _sse({"type": "delta", "content": answer})
        elif auto_start_error:
            answer = (
                f"这条任务暂时起不来执行器（{auto_start_error}）；"
                "已记在任务台，配置好后可以手动运行。"
            )
            yield _sse({"type": "delta", "content": answer})
        else:
            compiled = memory.recall_context(
                query=body.message,
                budget_chars=settings.memory_budget_chars,
                surfaces=["conversation", "project"],
                persona_id=settings.active_persona_id,
            )
            llm_messages = build_llm_messages(
                _system_prompt(request), conversation, memory_context=compiled.text
            )
            buffer: list[str] = []
            async for chunk in provider.stream_chat(llm_messages):
                buffer.append(chunk)
                yield _sse({"type": "delta", "content": chunk})
            answer = "".join(buffer)
        await store.append_message(
            conversation_id, "assistant", answer, modality="text"
        )
    except Exception as exc:  # 模型失败也要完成一轮，保证会话可继续
        answer = f"（模型调用失败：{exc}）"
        await store.append_message(
            conversation_id, "assistant", answer, modality="text"
        )
        yield _sse({"type": "error", "message": str(exc)})

    is_short = len(answer) <= settings.short_reply_chars
    speak_text = build_speak_text(answer, settings.short_reply_chars)
    try:
        assistant_trace_id = memory.record_event(
            "conversation",
            "conversation.response",
            {"text": answer, "speak_text": speak_text},
            session_id=request.app.state.session_id,
            turn_id=conversation_id,
        )
        memory.write_session_summary(conversation_id, body.message, answer)
        if user_trace_id:
            memory.upsert_entry("L3", "recent", "近期对话", body.message[:300], [user_trace_id])
        if "决定" in body.message or "方向" in body.message or "项目" in body.message:
            memory.upsert_entry("L2", "project", "项目线索", body.message[:500], [user_trace_id])
        if assistant_trace_id and ("完成" in answer or "已" in answer):
            memory.upsert_entry("L3", "recent", "最近结果", speak_text[:300] or answer[:300], [assistant_trace_id])
    except Exception:
        pass
    await hub.publish(
        EventEnvelope(
            event_type="conversation.completed",
            source="conversation",
            conversation_id=conversation_id,
            payload={
                "message": answer,
                "speak_text": speak_text,
                "short": is_short,
                "expand_ui": not is_short,
                "task_id": task.task_id if task else None,
                "task_category": task.category if task else "answer",
            },
        )
    )
    yield _sse(
        {
            "type": "done",
            "conversation_id": conversation_id,
            "short": is_short,
            "message": answer,
            "speak_text": speak_text,
            "task_id": task.task_id if task else None,
            "task_category": task.category if task else "answer",
            "model_profile_id": active_profile.id if active_profile else None,
            "model_name": active_profile.name if active_profile else provider.display_name,
        }
    )


@router.post("/chat/stream")
async def chat_stream(request: Request, body: ChatTurnRequest) -> StreamingResponse:
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="消息不能为空")
    return StreamingResponse(
        _run_turn(request, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
async def list_conversations(request: Request) -> dict:
    store = request.app.state.conversation_store
    conversations = await store.list_recent(limit=30)
    return {
        "items": [
            {
                "conversation_id": c.conversation_id,
                "title": c.title,
                "message_count": len(c.messages),
                "updated_at": c.updated_at,
            }
            for c in conversations
        ]
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(request: Request, conversation_id: str) -> dict:
    store = request.app.state.conversation_store
    conversation = await store.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation.model_dump(mode="json")
