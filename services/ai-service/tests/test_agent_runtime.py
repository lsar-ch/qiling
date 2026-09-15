"""Step 7 Phase 2：Agent Run 生命周期测试（不依赖真实 codex-acp）。"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.base import AgentAdapter, AgentTaskRequest, AgentTaskResult
from app.agents.base import AgentExecutionError
from app.config import load_settings
from app.main import create_app
from deskmate_contracts.agent import AgentInfo
from deskmate_contracts.task import Task


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FakeReadyAdapter(AgentAdapter):
    name = "fake-ready"
    adapter_id = "fake-ready"
    display_name = "Fake Ready"
    executable = True

    def __init__(
        self,
        *,
        result_status: str = "completed",
        result_message: str = "fake result",
        error: str | None = None,
        raise_error: str | None = None,
    ) -> None:
        self.result_status = result_status
        self.result_message = result_message
        self.error = error
        self.raise_error = raise_error
        self.request: AgentTaskRequest | None = None
        self.cancelled_at: str | None = None
        self.approved_at: str | None = None
        self.permission_requested = False

    async def detect(self) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            integration_status="ready",
            available=True,
            enabled=True,
            version="1.0",
            command="fake",
            capabilities=["code"],
            protocol="fake",
        )

    async def run(self, request: AgentTaskRequest, on_update) -> AgentTaskResult:
        self.request = request
        if self.raise_error:
            raise AgentExecutionError(self.raise_error)
        await on_update("session_ready", {"session_id": "sess_fake", "mode": request.mode})
        await on_update("progress", {"progress": "fake progress", "text": "fake progress"})
        return AgentTaskResult(
            status=self.result_status,
            message=self.result_message,
            error=self.error,
            session_id="sess_fake",
        )

    async def cancel(self, task_id: str, session_id: str | None = None) -> None:
        self.cancelled_at = f"{task_id}:{session_id or ''}"

    async def approve(self, task_id: str, decision: str) -> None:
        self.approved_at = f"{task_id}:{decision}"


class PendingAdapter(FakeReadyAdapter):
    name = "fake-pending"
    adapter_id = "pending"
    display_name = "Fake Pending"
    executable = False

    async def detect(self) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            integration_status="pending",
            available=True,
            enabled=True,
            version=None,
            command="fake-pending",
            capabilities=["code"],
            protocol=None,
        )

    async def run(self, request: AgentTaskRequest, on_update) -> AgentTaskResult:
        raise AgentExecutionUnsupported("not implemented")


class UnavailableAdapter(FakeReadyAdapter):
    """模拟 codex 等真适配器已安装协议但当前检测不到/不可执行。"""

    name = "fake-unavailable"
    adapter_id = "fake-unavailable"
    display_name = "Fake Unavailable"
    executable = True

    async def detect(self) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            integration_status="not_installed",
            available=False,
            enabled=True,
            detail="测试用执行器未安装",
        )


class BlockingAgentAdapter(FakeReadyAdapter):
    """run() 会停在授权/释放点，便于测试取消与批准路径。"""

    name = "fake-blocking"
    adapter_id = "fake-blocking"
    display_name = "Fake Blocking"
    executable = True

    def __init__(
        self,
        *,
        block_on_start: bool = False,
        await_permission: bool = False,
    ) -> None:
        super().__init__()
        self.block_on_start = block_on_start
        self.await_permission = await_permission
        self.hold_future: asyncio.Future[None] | None = None
        self.permission_future: asyncio.Future[dict] | None = None
        self.result_status = "completed"
        self.result_message = "released"

    async def run(self, request: AgentTaskRequest, on_update) -> AgentTaskResult:
        self.request = request
        await on_update("session_ready", {"session_id": "sess_block", "mode": request.mode})
        if self.await_permission:
            await on_update(
                "permission_request",
                {
                    "tool_call": {"name": "shell", "title": "执行命令"},
                    "options": [
                        {"optionId": "allow_once", "title": "Allow once"},
                        {"optionId": "reject_once", "title": "Reject once"},
                    ],
                },
            )
            loop = asyncio.get_running_loop()
            self.permission_future = loop.create_future()
            await self.permission_future
        if self.block_on_start:
            loop = asyncio.get_running_loop()
            self.hold_future = loop.create_future()
            await self.hold_future
        return AgentTaskResult(status=self.result_status, message=self.result_message)

    async def cancel(self, task_id: str, session_id: str | None = None) -> None:
        self.cancelled_at = f"{task_id}:{session_id or ''}"
        self.result_status = "cancelled"
        if self.permission_future is not None and not self.permission_future.done():
            self.permission_future.set_result({"outcome": "cancelled"})
        if self.hold_future is not None and not self.hold_future.done():
            self.hold_future.set_result(None)

    async def approve(self, task_id: str, decision: str) -> None:
        self.approved_at = f"{task_id}:{decision}"
        if self.permission_future is not None and not self.permission_future.done():
            self.permission_future.set_result(
                {"outcome": "selected", "optionId": "allow_once" if decision == "approved" else "reject_once"}
            )
        if self.hold_future is not None and not self.hold_future.done():
            self.hold_future.set_result(None)


def prepare_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "deskmate-home"
    monkeypatch.setenv("DESKMATE_HOME", str(home))
    (home / "config" / "personas").mkdir(parents=True)
    (home / "data").mkdir(parents=True)
    (home / "config").joinpath("settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (home / "config").joinpath("system_prompt.md").write_text(
        "你是 DeskMate。",
        encoding="utf-8",
    )
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", home / "config" / "agents.yaml")


@contextmanager
def make_client(tmp_path: Path, monkeypatch, adapter: AgentAdapter):
    prepare_home(tmp_path, monkeypatch)
    app = create_app(load_settings())
    app.state.agent_registry.register(adapter)
    with TestClient(app) as client:
        yield client


def _wait_for(client: TestClient, task_id: str, wanted: tuple[str, ...]) -> dict:
    for _ in range(100):
        body = client.get(f"/api/tasks/{task_id}/run").json()
        if body.get("run", {}).get("status") in wanted:
            return body["run"]
        time.sleep(0.05)
    raise AssertionError(f"run did not reach {wanted}")


def _route(
    client: TestClient,
    text: str = "帮我重构 README 文件中的代码结构",
    *,
    preferred_executor: str | None = "codex",
) -> dict:
    resp = client.post("/api/tasks/route", json={"input": text})
    assert resp.status_code == 200
    task = resp.json()["task"]
    if task["category"] != "delegate_backend":
        task = Task(
            input=text,
            category="delegate_backend",
            risk_level="medium",
            complexity="complex",
            estimated_duration="long",
            preferred_executor="codex",
            status="queued",
        ).model_dump(mode="json")
    task["preferred_executor"] = preferred_executor
    client.app.state.task_store.put(Task(**task))
    return task


def test_echo_of_own_reply_is_not_treated_as_new_task() -> None:
    """常开监听回采自己播报的内容（含识别偏差）时不应再起后台任务。"""
    from app.api.chat import _is_echo_of_reply
    from deskmate_contracts.conversation import Conversation, ConversationMessage

    reply = "收到，已交给后台执行；进度、报错和结果都会回到这条对话里。"

    def conversation_with(spoken: str) -> Conversation:
        # 末条是本轮刚写入的用户消息，与真实链路一致
        return Conversation(
            conversation_id="conv_echo",
            messages=[
                ConversationMessage(role="user", content="帮我整理这个项目的 docs 目录结构"),
                ConversationMessage(role="assistant", content=reply),
                ConversationMessage(role="user", content=spoken),
            ],
        )

    spoken_echo = "收到已交给后台执行进度报错和结果都会回到这条对话里。"
    assert _is_echo_of_reply(spoken_echo, conversation_with(spoken_echo))
    spoken_variant = "收到你交给后台执行进度报错和结果都会回到这条对话里。"
    assert _is_echo_of_reply(spoken_variant, conversation_with(spoken_variant))
    new_task = "帮我整理这个项目的 docs 目录结构，只列清单"
    assert not _is_echo_of_reply(new_task, conversation_with(new_task))


def test_chat_task_reports_back_into_conversation(tmp_path, monkeypatch) -> None:
    """对话页发起后台任务：自动起跑，进展与结果写回同一条会话（role=tool）。"""
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        resp = client.post(
            "/api/chat/stream",
            json={"message": "帮我重构 README 里的代码结构"},
        )
        assert resp.status_code == 200
        events = [
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
        done = next(event for event in events if event["type"] == "done")
        assert done["task_id"], "后台任务应自动起跑"
        _wait_for(client, done["task_id"], ("completed",))

        conv = client.get(f"/api/conversations/{done['conversation_id']}").json()
        notes = [item["content"] for item in conv["messages"] if item["role"] == "tool"]
        assert any("已交给" in text and adapter.name in text for text in notes)
        assert any(text.startswith("✓ 任务完成") and "fake result" in text for text in notes)


def test_execute_completed_updates_task_run_and_events(tmp_path, monkeypatch) -> None:
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        task_id = task["task_id"]
        resp = client.post(
            f"/api/tasks/{task_id}/execute",
            json={"executor": adapter.name, "mode": "read-only"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["run"]["status"] == "queued"
        run_id = body["run"]["run_id"]

        run = _wait_for(client, task_id, ("completed",))
        assert run["executor"] == adapter.name
        assert run["session_id"] == "sess_fake"
        assert run["result"] == "fake result"

        task_body = client.get(f"/api/tasks/{task_id}").json()
        assert task_body["status"] == "completed"


def test_execute_falls_back_to_default_executor_when_task_has_none(tmp_path, monkeypatch) -> None:
    """WI-08 回归：分流器不再硬编码 codex，任务未指定执行器时应落到 registry 默认执行器。"""
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        task = _route(client, preferred_executor=None)
        assert task["preferred_executor"] is None

        resp = client.post(f"/api/tasks/{task['task_id']}/execute", json={"mode": "read-only"})
        assert resp.status_code == 200
        run = _wait_for(client, task["task_id"], ("completed",))
        assert run["executor"] == adapter.name


def test_execute_failure_marks_failed_and_emits_event(tmp_path, monkeypatch) -> None:
    adapter = FakeReadyAdapter(result_status="failed", error="boom")
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        run = _wait_for(client, task["task_id"], ("failed",))
        assert run["error"] == "boom"
        assert client.get(f"/api/tasks/{task['task_id']}").json()["status"] == "failed"


def test_executor_upstream_failure_is_not_cancelled(tmp_path, monkeypatch) -> None:
    adapter = FakeReadyAdapter(raise_error="provider returned 400")
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        assert resp.status_code == 200
        run = _wait_for(client, task["task_id"], ("failed",))
        assert run["status"] == "failed"
        assert "provider returned 400" in (run["error"] or "")


def test_codex_system_error_is_marked_failed() -> None:
    import asyncio

    from app.agents.codex import CodexAdapter

    adapter = CodexAdapter()

    async def run_update() -> None:
        outputs: list[dict] = []
        async def sink(kind: str, payload: dict) -> None:
            outputs.append({"kind": kind, **payload})
        handler = adapter._make_update_handler("task_sys", sink)
        await handler(
            {
                "sessionUpdate": "session_info_update",
                "_meta": {
                    "codex": {
                        "threadStatus": {"type": "systemError", "activeFlags": []},
                    }
                },
            }
        )
        assert not outputs

    asyncio.run(run_update())
    assert adapter._run_errors.get("task_sys")


def test_duplicate_execute_on_running_task_is_rejected(tmp_path, monkeypatch) -> None:
    adapter = BlockingAgentAdapter(block_on_start=True)
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        first = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        assert second.status_code == 409


def test_cancel_run_sets_task_and_run_cancelled(tmp_path, monkeypatch) -> None:
    adapter = BlockingAgentAdapter(block_on_start=True)
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        run_id = resp.json()["run"]["run_id"]
        cancel = client.post(f"/api/agent-runs/{run_id}/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["run"]["status"] == "cancelled"
        assert client.get(f"/api/tasks/{task['task_id']}").json()["status"] == "cancelled"


def test_approval_and_result_write_back_to_conversation(tmp_path, monkeypatch) -> None:
    """任务授权请求与最终结果都写回来源会话（对话页可见）。"""
    adapter = BlockingAgentAdapter(await_permission=True)
    with make_client(tmp_path, monkeypatch, adapter) as client:
        chat = client.post("/api/chat/stream", json={"message": "你好"})
        conv_id = next(
            json.loads(line[6:])["conversation_id"]
            for line in chat.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        task = _route(client, preferred_executor=adapter.name)
        task["conversation_id"] = conv_id
        client.app.state.task_store.put(Task(**task))

        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        run_id = resp.json()["run"]["run_id"]
        _wait_for(client, task["task_id"], ("awaiting_approval",))

        def notes() -> list[str]:
            conv = client.get(f"/api/conversations/{conv_id}").json()
            return [item["content"] for item in conv["messages"] if item["role"] == "tool"]

        assert any("已交给" in text for text in notes())
        assert any("需要你确认" in text for text in notes())

        approval = client.post(
            f"/api/agent-runs/{run_id}/approval",
            json={"decision": "approved"},
        )
        assert approval.status_code == 200
        _wait_for(client, task["task_id"], ("completed",))
        assert any(text.startswith("✓ 任务完成") for text in notes())


def test_approval_route_resolves_pending_permission(tmp_path, monkeypatch) -> None:
    adapter = BlockingAgentAdapter(await_permission=True)
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        run_id = resp.json()["run"]["run_id"]
        _wait_for(client, task["task_id"], ("awaiting_approval",))
        assert adapter.permission_future is not None
        approval = client.post(
            f"/api/agent-runs/{run_id}/approval",
            json={"decision": "approved"},
        )
        assert approval.status_code == 200
        assert approval.json()["run"]["status"] in ("running", "completed")
        _wait_for(client, task["task_id"], ("completed",))


def test_pending_executor_execute_is_rejected(tmp_path, monkeypatch) -> None:
    adapter = PendingAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        assert resp.status_code == 400
        assert "尚未接入真实执行" in resp.json()["detail"]


def test_unavailable_executor_keeps_task_queued_with_clear_error(
    tmp_path, monkeypatch
) -> None:
    adapter = UnavailableAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name},
        )
        assert resp.status_code == 400
        assert "当前不可执行" in resp.json()["detail"]
        assert "not_installed" in resp.json()["detail"]

        queued = client.get(f"/api/tasks/{task['task_id']}").json()
        assert queued["status"] == "queued"
        listed = client.get("/api/tasks").json()["items"]
        assert any(item["task_id"] == task["task_id"] for item in listed)


def test_agent_run_list_is_newest_first(tmp_path, monkeypatch) -> None:
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        client.post(f"/api/tasks/{task['task_id']}/execute", json={"executor": adapter.name})
        _wait_for(client, task["task_id"], ("completed",))
        items = client.get("/api/agent-runs").json()["items"]
        assert items and items[0]["task_id"] == task["task_id"]
        assert items[0]["status"] == "completed"
