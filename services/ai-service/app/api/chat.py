"""文字对话接口：SSE 流式回复 + 会话保存。"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal
from typing import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deskmate_contracts import new_event_id
from deskmate_contracts.conversation import ChatAttachment, ChatMode
from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.project import ProjectNode
from deskmate_contracts.reminder import Reminder
from app.chat.context import build_llm_messages
from app.config import repo_root
from app.core.emotion_resolver import infer_emotion
from app.core.persona_prompt import compose_system_prompt, load_persona
from app.core.reminders import parse_reminder_message
from app.llm import create_provider
from app.llm.base import ToolSpec
from app.model_profiles import find_model_profile, load_model_profiles, profile_settings
from app.routing import classify_task_input

router = APIRouter(prefix="/api", tags=["chat"])

_ECHO_STRIP = re.compile(r"[\s，。！？、,.!?'\"“”‘’；：:;…—\-()（）【】《》~～·]+")

_ALLOWED_ATTACHMENT_SUFFIXES = {
    ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt",
    ".pdf", ".txt", ".csv", ".md", ".png", ".jpg", ".jpeg",
}
_MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024

MAX_TOOL_TURNS = 5
TOOL_APPROVAL_TIMEOUT_S = 120
TOOL_RESULT_MAX_CHARS = 8000


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


class ProjectBinding(BaseModel):
    """会话与项目目录的绑定；project 为空字符串/null 即解绑，回到普通对话。"""

    project: str | None = None
    name: str | None = None


class ChatTurnRequest(BaseModel):
    conversation_id: str | None = None
    project: str | None = None  # 本轮要绑定的项目目录（绝对路径）
    project_name: str | None = None  # 新建项目时填写的用户可见名称
    message: str = Field(min_length=1, max_length=8000)
    attachments: list[ChatAttachment] = Field(default_factory=list)
    modality: Literal["text", "voice"] = "text"
    mode: ChatMode = "auto"
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


def _uploads_root(request: Request) -> Path:
    return request.app.state.settings.data_dir / "uploads"


def _safe_attachment_name(filename: str) -> str:
    """生成唯一且安全的上传文件名；扩展名不在白名单时直接拒绝。"""
    path = Path(filename or "")
    suffix = path.suffix.lower()
    if suffix not in _ALLOWED_ATTACHMENT_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix or '无扩展名'}",
        )
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]", "_", path.stem)[:80].strip("_") or "file"
    return f"{uuid4().hex[:8]}_{stem}{suffix}"


async def _prepare_attachments(
    request: Request, body: ChatTurnRequest
) -> tuple[list[ChatAttachment], str | None]:
    """校验附件并把项目对话的附件复制进项目目录。

    返回 (最终附件列表, 普通对话附件执行目录)；项目对话的执行目录仍由项目绑定决定。
    """
    if not body.attachments:
        return [], None
    uploads = _uploads_root(request)
    uploads.mkdir(parents=True, exist_ok=True)
    project = resolve_project_dir(body.project) if body.project else None
    prepared: list[ChatAttachment] = []
    for attachment in body.attachments:
        source = Path(attachment.path).expanduser()
        try:
            source.resolve().relative_to(uploads.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="附件路径无效") from None
        if not source.is_file():
            raise HTTPException(status_code=404, detail=f"附件不存在：{attachment.name}")
        if project is None:
            prepared.append(attachment)
            continue
        destination = project / _safe_attachment_name(attachment.name or source.name)
        shutil.copy2(source, destination)
        prepared.append(
            ChatAttachment(
                name=destination.name,
                path=str(destination),
                size=destination.stat().st_size,
                mime=attachment.mime,
            )
        )
    return prepared, (str(uploads) if project is None else None)


@router.post("/chat/attachments")
async def upload_chat_attachments(
    request: Request,
    files: list[UploadFile] = File(...),
) -> dict:
    """把对话附件暂存到 DeskMate 数据目录，返回可随消息提交的附件元数据。"""
    uploads = _uploads_root(request)
    uploads.mkdir(parents=True, exist_ok=True)
    items: list[ChatAttachment] = []
    for file in files:
        name = _safe_attachment_name(file.filename or "")
        destination = uploads / name
        total = 0
        with destination.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_ATTACHMENT_BYTES:
                    destination.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="附件不能超过 50MB")
                out.write(chunk)
        items.append(
            ChatAttachment(
                name=name,
                path=str(destination),
                size=total,
                mime=file.content_type or "application/octet-stream",
            )
        )
    return {"items": [item.model_dump(mode="json") for item in items]}


def _project_memory_key(project: str | None) -> str | None:
    """项目独立记忆文档 key；未绑定返回 None（回退全局 project 文档）。"""
    if not project:
        return None
    slug = re.sub(r"\W+", "-", Path(project).name).strip("-")[:40] or "proj"
    return f"proj-{slug}"


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

    attachments, attachment_cwd = await _prepare_attachments(request, body)
    conversation = await store.append_message(
        body.conversation_id,
        "user",
        body.message,
        modality=body.modality,
        model_profile_id=conversation_profile_id,
        attachments=attachments,
    )
    conversation_id = conversation.conversation_id
    if body.project:
        # 目录存在性已在 chat_stream 校验过，这里只负责改绑会话。
        resolved = resolve_project_dir(body.project)
        updated = await store.set_project(
            conversation_id,
            str(resolved) if resolved else None,
            project_name=body.project_name,
        )
        if updated is not None:
            conversation = updated
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
    selected_skill = request.app.state.skill_registry.select(body.message)
    task = classify_task_input(body.message, settings.permission_level)
    task.conversation_id = conversation_id
    task.project = conversation.project
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
    # 后台任务直接起跑：进度、报错、授权、结果都会写回本会话，
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
            from app.agents.browser import is_browser_task, is_web_fetch_task

            # 带链接的抓取/提炼任务交给后台 workbuddy 以 agent 模式执行（WebFetch
            # 需授权时在对话里确认后同一次运行继续）；纯搜索/打开仍走只读浏览器执行器。
            web_fetch = is_web_fetch_task(body.message)
            executor = (
                "browser" if is_browser_task(body.message) and not web_fetch else None
            )
            mode = (
                "agent"
                if web_fetch or task.work_kind in {"word", "excel", "ppt"}
                else "read-only"
            )
            auto_run = await request.app.state.agent_run_manager.execute(
                task, mode=mode, executor=executor, cwd=attachment_cwd
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

    is_casual = (
        body.mode == "casual"
        or (body.mode == "auto" and task.interaction_kind == "casual")
    )
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
            # 工作模式记忆深度：casual 轻量 / work 完整 / auto 按分流结果
            proj_summary = (
                request.app.state.project_node_store.summary(conversation.project)
                if conversation.project
                else ""
            )
            if is_casual:
                compiled = memory.recall_context(
                    query="",
                    budget_chars=min(settings.memory_budget_chars, 800),
                    surfaces=[],
                    persona_id=settings.active_persona_id,
                )
            else:
                proj_key = _project_memory_key(conversation.project)
                compiled = memory.recall_context(
                    query=body.message,
                    budget_chars=settings.memory_budget_chars,
                    surfaces=["conversation", proj_key or "project"],
                    persona_id=settings.active_persona_id,
                )
            llm_messages = build_llm_messages(
                _system_prompt(request),
                conversation,
                memory_context="\n\n".join(p for p in (compiled.text, proj_summary) if p.strip()),
                skill_context=(
                    f"技能：{selected_skill.info.name}\n{selected_skill.body}"
                    if selected_skill is not None
                    else ""
                ),
            )
            mcp_manager = request.app.state.mcp_manager
            await mcp_manager.reclaim_idle()
            tool_pairs = await mcp_manager.prepare_tool_specs()
            tool_lookup = {
                f"mcp__{server_id}__{tool.name}": (server_id, tool.name)
                for server_id, tool in tool_pairs
            }
            tool_specs = [
                ToolSpec(
                    name=f"mcp__{server_id}__{tool.name}",
                    description=(tool.description or tool.name)[:500],
                    parameters=tool.input_schema
                    or {"type": "object", "properties": {}},
                )
                for server_id, tool in tool_pairs
            ]
            if not tool_specs:
                # 无可用 MCP 工具：保持原流式路径不变
                buffer: list[str] = []
                async for chunk in provider.stream_chat(llm_messages):
                    buffer.append(chunk)
                    yield _sse({"type": "delta", "content": chunk})
                answer = "".join(buffer)
            else:
                answer = ""
                extra_messages: list[dict] = []
                for _ in range(MAX_TOOL_TURNS):
                    result = await provider.chat(
                        [*llm_messages, *extra_messages],
                        tools=tool_specs,
                    )
                    if not result.tool_calls:
                        answer = result.text or "（模型未返回内容）"
                        break
                    extra_messages.append(
                        {
                            "role": "assistant",
                            "content": result.text or "",
                            "tool_calls": [
                                {
                                    "id": call.id,
                                    "type": "function",
                                    "function": {
                                        "name": call.name,
                                        "arguments": json.dumps(
                                            call.arguments, ensure_ascii=False
                                        ),
                                    },
                                }
                                for call in result.tool_calls
                            ],
                        }
                    )
                    for call in result.tool_calls:
                        parsed = tool_lookup.get(call.name)
                        tool_content = ""
                        if parsed is None:
                            tool_content = f"未知工具：{call.name}"
                        else:
                            server_id, tool_name = parsed
                            yield _sse(
                                {
                                    "type": "tool_call",
                                    "server": server_id,
                                    "tool": tool_name,
                                }
                            )
                            access = mcp_manager.get_access(server_id) or "read"
                            denied = False
                            if access == "write":
                                approval_id = f"approve_{uuid4().hex[:12]}"
                                yield _sse(
                                    {
                                        "type": "tool_approval",
                                        "approval_id": approval_id,
                                        "server": server_id,
                                        "tool": tool_name,
                                        "arguments": json.dumps(
                                            call.arguments, ensure_ascii=False
                                        )[:500],
                                    }
                                )
                                future = asyncio.get_running_loop().create_future()
                                request.app.state.tool_approvals[approval_id] = future
                                try:
                                    decision = await asyncio.wait_for(
                                        future, TOOL_APPROVAL_TIMEOUT_S
                                    )
                                except asyncio.TimeoutError:
                                    decision = "rejected"
                                request.app.state.tool_approvals.pop(
                                    approval_id, None
                                )
                                if decision != "approved":
                                    denied = True
                                    tool_content = (
                                        f"用户拒绝执行 {server_id}.{tool_name}"
                                    )
                            if not denied:
                                try:
                                    tool_content = await mcp_manager.call_tool(
                                        server_id, tool_name, call.arguments
                                    )
                                except Exception as exc:
                                    tool_content = f"工具执行失败：{exc}"
                                if len(tool_content) > TOOL_RESULT_MAX_CHARS:
                                    tool_content = (
                                        tool_content[:TOOL_RESULT_MAX_CHARS]
                                        + "\n…（结果过长已截断）"
                                    )
                        extra_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": tool_content,
                            }
                        )
                else:
                    answer = "（工具调用轮数超限，已停止；请换个说法或手动执行）"
                if answer:
                    yield _sse({"type": "delta", "content": answer})
        await store.append_message(
            conversation_id, "assistant", answer, modality="text"
        )
    except Exception as exc:  # 模型失败也要完成一轮，保证会话可继续
        answer = f"（模型调用失败：{exc}）"
        await store.append_message(
            conversation_id, "assistant", answer, modality="text"
        )
        yield _sse({"type": "error", "message": str(exc)})

    reminder_note = ""
    parsed_reminder = parse_reminder_message(body.message)
    if parsed_reminder is not None:
        reminder_text, remind_at = parsed_reminder
        request.app.state.reminder_store.put(
            Reminder(kind="memo", text=reminder_text, remind_at=remind_at)
        )
        reminder_note = f"⏰ 已设置提醒：{reminder_text}"
    if reminder_note:
        answer = f"{reminder_note}\n{answer}"

    is_short = len(answer) <= settings.short_reply_chars
    speak_text = build_speak_text(answer, settings.short_reply_chars)
    reply_emotion = infer_emotion(speak_text or answer, casual=is_casual)
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
            memory.upsert_entry(
                "L2",
                _project_memory_key(conversation.project) or "project",
                "项目线索",
                body.message[:500],
                [user_trace_id],
            )
        if conversation.project and ("决定" in body.message or "采用" in body.message):
            request.app.state.project_node_store.put(
                ProjectNode(
                    project=conversation.project,
                    title=body.message[:60],
                    kind="decision",
                    status="completed",
                    decision=body.message[:500],
                    source="conversation",
                )
            )
        if assistant_trace_id and ("完成" in answer or "已" in answer):
            memory.upsert_entry("L3", "recent", "最近结果", speak_text[:300] or answer[:300], [assistant_trace_id])
    except Exception:
        pass
    await hub.publish(
        EventEnvelope(
            event_type="conversation.completed",
            source="conversation",
            conversation_id=conversation_id,
            expression={
                "state": "completed",
                "task_id": task.task_id if task else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "emotion": reply_emotion,
            },
            payload={
                "message": answer,
                "speak_text": speak_text,
                "short": is_short,
                "expand_ui": not is_short,
                "task_id": task.task_id if task else None,
                "task_category": task.category if task else "answer",
                "interaction_kind": task.interaction_kind if task else "casual",
                "skill_id": selected_skill.info.id if selected_skill else None,
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
            "emotion": reply_emotion,
            "task_id": task.task_id if task else None,
            "task_category": task.category if task else "answer",
            "interaction_kind": task.interaction_kind if task else "casual",
            "skill_id": selected_skill.info.id if selected_skill else None,
            "model_profile_id": active_profile.id if active_profile else None,
            "model_name": active_profile.name if active_profile else provider.display_name,
        }
    )


@router.post("/chat/stream")
async def chat_stream(request: Request, body: ChatTurnRequest) -> StreamingResponse:
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="消息不能为空")
    if body.project and resolve_project_dir(body.project) is None:
        raise HTTPException(status_code=400, detail=f"项目目录不存在或不是目录：{body.project}")
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
                "project": c.project,
                "project_name": c.project_name or (Path(c.project).name if c.project else None),
                "message_count": len(c.messages),
                "updated_at": c.updated_at,
            }
            for c in conversations
        ]
    }


@router.put("/conversations/{conversation_id}/project")
async def update_conversation_project(
    request: Request,
    conversation_id: str,
    body: ProjectBinding,
) -> dict:
    """给会话绑定或解绑项目目录；解绑后回到「普通对话」分组。"""
    store = request.app.state.conversation_store
    project = body.project.strip() if body.project else ""
    if project:
        resolved = resolve_project_dir(project)
        if resolved is None:
            raise HTTPException(status_code=400, detail=f"项目目录不存在或不是目录：{project}")
        project = str(resolved)
    conversation = await store.set_project(conversation_id, project or None, project_name=body.name)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation.model_dump(mode="json")


def resolve_project_dir(value: str) -> Path | None:
    """把用户填的项目路径解析成真实存在的目录；不允许相对路径或越权猜测。"""
    raw = (value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (repo_root() / path).resolve()
    return path if path.is_dir() else None


@router.get("/conversations/{conversation_id}")
async def get_conversation(request: Request, conversation_id: str) -> dict:
    store = request.app.state.conversation_store
    conversation = await store.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation.model_dump(mode="json")
