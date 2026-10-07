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
from qiling_contracts.agent import AgentInfo
from qiling_contracts.task import Task


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


class WordArtifactAdapter(FakeReadyAdapter):
    """模拟 Word 执行器写出一个新文档，验证产物回传。"""

    async def run(self, request: AgentTaskRequest, on_update) -> AgentTaskResult:
        self.request = request
        await on_update("session_ready", {"session_id": "sess_word", "mode": request.mode})
        output = Path(request.cwd) / "报告_edited.docx"
        output.write_bytes(b"fake-docx")
        return AgentTaskResult(status="completed", message="已完成 Word 排版")


class ExcelArtifactAdapter(FakeReadyAdapter):
    """模拟 Excel 执行器写出一个新表格，验证产物回传。"""

    async def run(self, request: AgentTaskRequest, on_update) -> AgentTaskResult:
        self.request = request
        await on_update("session_ready", {"session_id": "sess_excel", "mode": request.mode})
        output = Path(request.cwd) / "数据_processed.xlsx"
        output.write_bytes(b"fake-xlsx")
        return AgentTaskResult(status="completed", message="已完成 Excel 数据处理")


class PptArtifactAdapter(FakeReadyAdapter):
    """模拟 PPT 执行器写出一个新演示文稿，验证产物回传。"""

    async def run(self, request: AgentTaskRequest, on_update) -> AgentTaskResult:
        self.request = request
        await on_update("session_ready", {"session_id": "sess_ppt", "mode": request.mode})
        output = Path(request.cwd) / "方案_edited.pptx"
        output.write_bytes(b"fake-pptx")
        return AgentTaskResult(status="completed", message="已完成 PPT 美化")


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
            # 与真实适配器一致：future 先登记再通知，运行器可能在这次回调里就回绝
            loop = asyncio.get_running_loop()
            self.permission_future = loop.create_future()
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
    home = tmp_path / "qiling-home"
    monkeypatch.setenv("QILING_HOME", str(home))
    (home / "config" / "personas").mkdir(parents=True)
    (home / "data").mkdir(parents=True)
    (home / "config").joinpath("settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (home / "config").joinpath("system_prompt.md").write_text(
        "你是 栖灵。",
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
    body: dict = {}
    for _ in range(100):
        body = client.get(f"/api/tasks/{task_id}/run").json()
        if body.get("run", {}).get("status") in wanted:
            return body["run"]
        time.sleep(0.05)
    raise AssertionError(f"run did not reach {wanted}, last={body.get('run')}")


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
    from qiling_contracts.conversation import Conversation, ConversationMessage

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


def test_word_task_uses_agent_mode_and_reports_new_artifact(tmp_path, monkeypatch) -> None:
    adapter = WordArtifactAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        resp = client.post(
            "/api/chat/stream",
            json={"message": "帮我把这个 Word 文档重新排版"},
        )
        assert resp.status_code == 200
        done = next(
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        run = _wait_for(client, done["task_id"], ("completed",))
        assert run["mode"] == "agent"
        assert "报告_edited.docx" in (run["result"] or "")
        assert adapter.request is not None
        assert adapter.request.mode == "agent"
        assert "不要覆盖原文件" in adapter.request.prompt


def test_excel_task_uses_agent_mode_and_reports_new_artifact(tmp_path, monkeypatch) -> None:
    adapter = ExcelArtifactAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        resp = client.post("/api/chat/stream", json={"message": "分析这个 Excel 数据并生成图表"})
        assert resp.status_code == 200
        done = next(
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        run = _wait_for(client, done["task_id"], ("completed",))
        assert run["mode"] == "agent"
        assert "数据_processed.xlsx" in (run["result"] or "")
        assert adapter.request is not None
        assert adapter.request.mode == "agent"
        assert "不要覆盖原文件" in adapter.request.prompt


def test_ppt_task_uses_agent_mode_and_reports_new_artifact(tmp_path, monkeypatch) -> None:
    adapter = PptArtifactAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        resp = client.post("/api/chat/stream", json={"message": "把这个 PPT 美化一下"})
        assert resp.status_code == 200
        done = next(
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        run = _wait_for(client, done["task_id"], ("completed",))
        assert run["mode"] == "agent"
        assert "方案_edited.pptx" in (run["result"] or "")
        assert adapter.request is not None
        assert adapter.request.mode == "agent"
        assert "不要覆盖原文件" in adapter.request.prompt


def test_low_risk_chatter_is_not_auto_started(tmp_path, monkeypatch) -> None:
    """随机一句闲聊：判成纯问答，不自动拉真实 agent。"""
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        resp = client.post("/api/chat/stream", json={"message": "就是你看那个落花生。"})
        done = next(
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        assert done["task_category"] == "answer"
        assert client.get(f"/api/tasks/{done['task_id']}/run").json()["run"] is None


def test_chat_auto_runs_browser_search_on_browser_executor(tmp_path, monkeypatch) -> None:
    """搜索类后台任务自动起跑时优先选浏览器执行器。"""
    browser = FakeReadyAdapter(result_message="石家庄中考招生政策摘要")
    browser.name = "browser"
    browser.adapter_id = "browser"
    browser.display_name = "浏览器"
    with make_client(tmp_path, monkeypatch, browser) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "搜索 石家庄中考招生政策 并返回前几条摘要"},
        )
        assert resp.status_code == 200
        done = next(
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        assert done["task_category"] == "delegate_backend"
        run = client.get(f"/api/tasks/{done['task_id']}/run").json()["run"]
        assert run["executor"] == "browser"
        _wait_for(client, done["task_id"], ("completed",))
        conv = client.get(f"/api/conversations/{done['conversation_id']}").json()
        notes = [item["content"] for item in conv["messages"] if item["role"] == "tool"]
        assert any("摘要" in text for text in notes)


def test_chat_web_fetch_task_runs_workbuddy_in_agent_mode(tmp_path, monkeypatch) -> None:
    """带链接的抓取/提炼任务不走浏览器执行器，交给 workbuddy 以 agent 模式执行。"""
    adapter = FakeReadyAdapter(result_message="已抓取文章并完成提炼")
    adapter.name = "workbuddy"
    adapter.adapter_id = "workbuddy"
    adapter.display_name = "WorkBuddy"
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        resp = client.post(
            "/api/chat/stream",
            json={"message": "https://mp.weixin.qq.com/s/LsCjMbsbKXvBgKVspOlczw我想让你整理和提炼这个公众号的内容"},
        )
        assert resp.status_code == 200
        done = next(
            json.loads(line[6:])
            for line in resp.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        assert done["task_category"] == "delegate_backend"
        run = client.get(f"/api/tasks/{done['task_id']}/run").json()["run"]
        assert run["executor"] == "workbuddy"
        assert run["mode"] == "agent"
        _wait_for(client, done["task_id"], ("completed",))
        assert adapter.request.mode == "agent"


def test_multi_turn_context_is_carried_into_backend_prompt(tmp_path, monkeypatch) -> None:
    """同一对话里第二轮任务要带上前几轮内容，后台 agent 不能刚交代完就忘。"""
    adapter = FakeReadyAdapter()
    adapter.name = "workbuddy"
    adapter.adapter_id = "workbuddy"
    adapter.display_name = "WorkBuddy"
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        first = client.post(
            "/api/chat/stream",
            json={"message": "帮我整理这个项目的 docs 目录结构"},
        )
        done1 = next(
            json.loads(line[6:])
            for line in first.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        _wait_for(client, done1["task_id"], ("completed",))

        conv_id = done1["conversation_id"]
        second = client.post(
            "/api/chat/stream",
            json={"conversation_id": conv_id, "message": "把上一步的结果整理成清单写进文档"},
        )
        done2 = next(
            json.loads(line[6:])
            for line in second.text.splitlines()
            if line.startswith("data: ") and '"done"' in line
        )
        _wait_for(client, done2["task_id"], ("completed",))
        prompt = adapter.request.prompt
        assert "帮我整理这个项目的 docs 目录结构" in prompt
        assert "当前任务：把上一步的结果整理成清单写进文档" in prompt


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


def test_completed_task_publishes_memory_updated_event(tmp_path, monkeypatch) -> None:
    """P1-T3 回归：任务完成必须发 memory.updated，前端记忆气泡依赖这条事件。"""
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        task_id = task["task_id"]
        resp = client.post(
            f"/api/tasks/{task_id}/execute",
            json={"executor": adapter.name, "mode": "read-only"},
        )
        assert resp.status_code == 200
        _wait_for(client, task_id, ("completed",))

        # memory.updated 由 ensure_future 异步发布，轮询等它进 hub 历史
        hub = client.app.state.event_hub
        memory_events: list[dict] = []
        for _ in range(100):
            memory_events = [
                item
                for item in hub.recent(50)
                if item.get("event_type") == "memory.updated"
            ]
            if memory_events:
                break
            time.sleep(0.05)

        assert memory_events, "任务完成后未发布 memory.updated 事件"
        # recent() 从新到旧，取最新一条
        latest = memory_events[0]
        assert latest["source"] == "task"
        assert latest["task_id"] == task_id
        assert str(latest.get("payload", {}).get("bubble", "")).startswith("已记住：")


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
            json={"executor": adapter.name, "mode": "agent"},
        )
        run_id = resp.json()["run"]["run_id"]
        _wait_for(client, task["task_id"], ("awaiting_approval",))

        def notes() -> list[str]:
            conv = client.get(f"/api/conversations/{conv_id}").json()
            return [item["content"] for item in conv["messages"] if item["role"] == "tool"]

        assert any("已交给" in text for text in notes())
        assert any("请求授权" in text for text in notes())

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
            json={"executor": adapter.name, "mode": "agent"},
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


def test_read_only_auto_rejects_permission_request(tmp_path, monkeypatch) -> None:
    """read-only 不弹授权卡片：需授权的操作由运行器直接回绝。

    WorkBuddy 的 plan / Codex 的只读档都只是「每次问」，有人应答就能写盘，
    所以隔离必须在 AgentRunManager 收口，不能依赖执行器自己的档位。
    """
    adapter = BlockingAgentAdapter(await_permission=True)
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name, "mode": "read-only"},
        )
        run_id = resp.json()["run"]["run_id"]
        _wait_for(client, task["task_id"], ("completed",))

        assert adapter.approved_at == f"{task['task_id']}:rejected"
        assert client.get("/api/agent-runs/awaiting").json()["items"] == []
        listed = next(
            item
            for item in client.get("/api/agent-runs").json()["items"]
            if item["run_id"] == run_id
        )
        assert listed["status"] == "completed"
        assert listed["progress"] == "执行命令"
        assert client.get(f"/api/tasks/{task['task_id']}").json()["status"] != "awaiting_approval"


def test_read_only_rejection_writes_back_to_conversation(tmp_path, monkeypatch) -> None:
    """自动拒绝要在会话里留下可见说明，否则用户只看到任务静默结束。"""
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
        client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name, "mode": "read-only"},
        )
        _wait_for(client, task["task_id"], ("completed",))

        conv = client.get(f"/api/conversations/{conv_id}").json()
        notes = [item["content"] for item in conv["messages"] if item["role"] == "tool"]
        assert any(text.startswith("⛔") and "执行命令" in text for text in notes)
        assert not any("请求授权" in text for text in notes)


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


class DisabledReadyAdapter(FakeReadyAdapter):
    """页面停用后的执行器：条目仍可探测，但 enabled=False。"""

    name = "fake-disabled"
    adapter_id = "fake-disabled"
    display_name = "Fake Disabled"

    async def detect(self) -> AgentInfo:
        info = await super().detect()
        return info.model_copy(update={"enabled": False})


def test_execute_rejects_disabled_executor(tmp_path, monkeypatch) -> None:
    """停用中的执行器保留展示，但不能再接任务。"""
    adapter = DisabledReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        client.app.state.agent_registry.default_executor = adapter.name
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"mode": "read-only"},
        )
        assert resp.status_code == 400
        assert "已停用" in resp.json()["detail"]
        assert adapter.request is None


def test_permission_summary_prefers_real_command() -> None:
    """WorkBuddy 的 toolCall 没有 title/name，摘要必须落到真实命令上。"""
    from app.agents.runtime import _permission_summary

    assert _permission_summary({"title": "执行命令", "name": "shell"}) == "执行命令"
    workbuddy_call = {
        "toolCallId": "call_79cc0eb968c648b29fe164d0",
        "rawInput": {
            "command": "printf 'hello' > probe.txt",
            "description": "Create probe.txt with content hello",
        },
        "_meta": {"codebuddy.ai/toolName": "Bash"},
    }
    assert _permission_summary(workbuddy_call) == "printf 'hello' > probe.txt"
    assert _permission_summary(
        {"rawInput": {"description": "读取配置"}, "_meta": {"codebuddy.ai/toolName": "Read"}}
    ) == "读取配置"
    assert _permission_summary({"_meta": {"codebuddy.ai/toolName": "Bash"}}) == "Bash 操作"
    assert _permission_summary(None) == "等待授权"
    assert _permission_summary({}) == "等待授权"


def test_permission_summary_unwraps_workbuddy_tools() -> None:
    """Write 要能看出写哪个文件；DeferExecuteTool 要显出被它包装的真实操作。

    报文取自 2026-09-17 真实会话记录（~/.codebuddy/projects/…/*.jsonl）。
    """
    from app.agents.runtime import _permission_summary

    assert _permission_summary(
        {
            "rawInput": {"file_path": "/Users/x/Desktop/note.txt", "content": "…"},
            "_meta": {"codebuddy.ai/toolName": "Write"},
        }
    ) == "Write：/Users/x/Desktop/note.txt"
    assert _permission_summary(
        {"rawInput": {"file_path": "/Users/x/Desktop/note.txt"},
         "_meta": {"codebuddy.ai/toolName": "Read"}}
    ) == "Read：/Users/x/Desktop/note.txt"
    assert _permission_summary(
        {
            "rawInput": {
                "toolName": "ExitPlanMode",
                "params": {"allowedPrompts": [{"tool": "Bash", "prompt": "确认桌面文件是否创建成功（ls）"}]},
            },
            "_meta": {"codebuddy.ai/toolName": "DeferExecuteTool"},
        }
    ) == "ExitPlanMode：确认桌面文件是否创建成功（ls）"
    assert _permission_summary(
        {"rawInput": {"toolName": "ExitPlanMode", "params": {}},
         "_meta": {"codebuddy.ai/toolName": "DeferExecuteTool"}}
    ) == "ExitPlanMode"


def test_approval_timeout_auto_rejects(tmp_path, monkeypatch) -> None:
    """授权长时间无人响应时自动按拒绝收口，run 不会永远挂在 awaiting_approval。"""
    adapter = BlockingAgentAdapter(await_permission=True)
    with make_client(tmp_path, monkeypatch, adapter) as client:
        manager = client.app.state.agent_run_manager
        monkeypatch.setattr(manager, "_APPROVAL_TIMEOUT_SECONDS", 1)
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name, "mode": "agent"},
        )
        run_id = resp.json()["run"]["run_id"]
        _wait_for(client, task["task_id"], ("awaiting_approval",))

        run = _wait_for(client, task["task_id"], ("completed",))
        assert run["run_id"] == run_id
        assert adapter.approved_at == f"{task['task_id']}:rejected"
        assert manager._approval_deadlines == {}
        assert manager._approval_timers == {}


def test_manual_approval_cancels_timeout(tmp_path, monkeypatch) -> None:
    """用户先决定时，超时兜底任务必须被撤掉，不能事后再拒绝一次。"""
    adapter = BlockingAgentAdapter(await_permission=True)
    with make_client(tmp_path, monkeypatch, adapter) as client:
        manager = client.app.state.agent_run_manager
        monkeypatch.setattr(manager, "_APPROVAL_TIMEOUT_SECONDS", 1)
        task = _route(client, preferred_executor=adapter.name)
        resp = client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name, "mode": "agent"},
        )
        run_id = resp.json()["run"]["run_id"]
        _wait_for(client, task["task_id"], ("awaiting_approval",))
        assert client.post(
            f"/api/agent-runs/{run_id}/approval", json={"decision": "approved"}
        ).status_code == 200
        assert adapter.approved_at == f"{task['task_id']}:approved"
        _wait_for(client, task["task_id"], ("completed",))
        time.sleep(1.2)
        assert client.get(f"/api/tasks/{task['task_id']}").json()["status"] == "completed"
        assert adapter.approved_at == f"{task['task_id']}:approved"


def _link_node(client, tmp_path: Path, task_id: str):
    """在项目下建一个已关联该任务的节点，返回 node_id。"""
    from qiling_contracts.project import ProjectNode

    node = ProjectNode(
        project=str(tmp_path),
        title="V2 P1-T2 节点联动",
        kind="node",
        status="in_progress",
        task_ids=[task_id],
    )
    client.app.state.project_node_store.put(node)
    return node.node_id


def test_completed_task_advances_linked_project_node(tmp_path, monkeypatch) -> None:
    """任务完成后，关联节点应自动推进为 completed。"""
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        task["project"] = str(tmp_path)
        client.app.state.task_store.put(Task(**task))
        node_id = _link_node(client, tmp_path, task["task_id"])

        client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name, "mode": "read-only"},
        )
        _wait_for(client, task["task_id"], ("completed",))

        node = client.app.state.project_node_store.get(node_id)
        assert node is not None
        assert node.status == "completed"


def test_failed_task_blocks_linked_project_node(tmp_path, monkeypatch) -> None:
    """任务失败后，关联节点应转为 blocked 并记下原因。"""
    adapter = FakeReadyAdapter(result_status="failed", error="执行器崩了")
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        task["project"] = str(tmp_path)
        client.app.state.task_store.put(Task(**task))
        node_id = _link_node(client, tmp_path, task["task_id"])

        client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name, "mode": "read-only"},
        )
        _wait_for(client, task["task_id"], ("failed",))

        node = client.app.state.project_node_store.get(node_id)
        assert node is not None
        assert node.status == "blocked"
        assert "执行器崩了" in (node.blocker or "")

        hub = client.app.state.event_hub
        blocked_events: list[dict] = []
        for _ in range(100):
            blocked_events = [
                item for item in hub.recent(50) if item.get("event_type") == "project.blocked"
            ]
            if blocked_events:
                break
            time.sleep(0.05)
        assert blocked_events, "节点阻塞后未发布 project.blocked 事件"
        assert "节点阻塞" in (blocked_events[0].get("payload", {}).get("bubble") or "")


def test_unlinked_node_is_untouched_by_task_finish(tmp_path, monkeypatch) -> None:
    """没关联该任务的节点不应被误改。"""
    adapter = FakeReadyAdapter()
    with make_client(tmp_path, monkeypatch, adapter) as client:
        task = _route(client, preferred_executor=adapter.name)
        task["project"] = str(tmp_path)
        client.app.state.task_store.put(Task(**task))

        from qiling_contracts.project import ProjectNode

        other = ProjectNode(project=str(tmp_path), title="无关节点", status="planned")
        client.app.state.project_node_store.put(other)

        client.post(
            f"/api/tasks/{task['task_id']}/execute",
            json={"executor": adapter.name, "mode": "read-only"},
        )
        _wait_for(client, task["task_id"], ("completed",))

        assert client.app.state.project_node_store.get(other.node_id).status == "planned"


def test_restart_marks_interrupted_runs_failed(tmp_path) -> None:
    """T4：重启后磁盘上遗留的 queued/running run 必然没有进程在跑，启动即判失败。

    判据是「进程存活」而不是「跑了多久」，所以正常跑着的长任务不受影响。
    """
    from app.agents.runtime import AgentRun, AgentRunManager, AgentRunStore
    from app.core.bus import EventHub
    from app.routing.store import TaskStore

    runs = AgentRunStore(tmp_path / "runs")
    tasks = TaskStore(tmp_path / "tasks")
    interrupted = Task(input="重启前还在跑的任务")
    tasks.put(interrupted)
    runs.put(AgentRun(task_id=interrupted.task_id, executor="fake", status="running"))
    finished = Task(input="重启前就完成了的任务")
    tasks.put(finished)
    runs.put(AgentRun(task_id=finished.task_id, executor="fake", status="completed"))

    AgentRunManager(
        registry=None,  # type: ignore[arg-type]
        store=runs,
        task_store=tasks,
        hub=EventHub(),
        memory=None,  # type: ignore[arg-type]
        data_dir=tmp_path,
    )

    killed = runs.latest_for_task(interrupted.task_id)
    assert killed is not None and killed.status == "failed"
    assert "服务重启" in (killed.error or "")
    assert tasks.get(interrupted.task_id).status == "failed"
    kept = runs.latest_for_task(finished.task_id)
    assert kept is not None and kept.status == "completed"


def test_stale_sweeper_reminds_once_per_run(tmp_path) -> None:
    """T3：超阈值无进展的 running run 发 task.stale，且同一 run 只提醒一次。"""
    import asyncio

    from app.agents.runtime import AgentRun, AgentRunManager, AgentRunStore
    from app.core.bus import EventHub
    from app.routing.store import TaskStore

    hub = EventHub()
    manager = AgentRunManager(
        registry=None,  # type: ignore[arg-type]
        store=AgentRunStore(tmp_path / "runs"),
        task_store=TaskStore(tmp_path / "tasks"),
        hub=hub,
        memory=None,  # type: ignore[arg-type]
        data_dir=tmp_path,
    )
    run = AgentRun(task_id="task_a", executor="fake", status="running")
    manager.store.put(run)
    run.updated_at = "2000-01-01T00:00:00+00:00"

    async def _sweep_twice() -> None:
        await manager._sweep_stale_runs(60)
        await manager._sweep_stale_runs(60)

    asyncio.run(_sweep_twice())
    stale = [e for e in hub.recent(10) if e.get("event_type") == "task.stale"]
    assert len(stale) == 1
    assert "无进展" in (stale[0].get("payload", {}).get("bubble") or "")
