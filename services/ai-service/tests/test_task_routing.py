"""Step 6：任务分流、任务 API 与聊天自动分流。"""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.routing import classify_task_input


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class DummyProvider:
    display_name = "dummy"

    async def stream_chat(self, messages, **kwargs) -> AsyncIterator[str]:
        yield "好"


def prepare_home(tmp_path: Path, monkeypatch, permission_level: str = "confirm_risky") -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DESKMATE_HOME", str(home))
    (home / "config" / "personas").mkdir(parents=True)
    (home / "config").joinpath("settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (home / "config").joinpath("system_prompt.md").write_text("你是 DeskMate。", encoding="utf-8")
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", home / "config" / "agents.yaml")
    (home / "config" / "personas" / "default.yaml").write_text(
        """
id: default
name: 千问
kind: assistant
description: 项目伙伴
personality: [简洁]
backstory: 住在桌面上。
language: zh-CN
reply_style: 简洁
avatar: ""
voice: {}
activation: {}
""".strip(),
        encoding="utf-8",
    )
    (home / "data").mkdir(parents=True, exist_ok=True)
    (home / "data" / "settings.local.json").write_text(
        json.dumps({"permission_level": permission_level}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@contextmanager
def make_client(
    tmp_path: Path,
    monkeypatch,
    permission_level: str = "confirm_risky",
    llm_provider=None,
) -> TestClient:
    prepare_home(tmp_path, monkeypatch, permission_level)
    with TestClient(create_app(load_settings(), llm_provider=llm_provider)) as client:
        yield client


def test_answer_routes_to_answer(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"input": "解释一下任务分流是什么"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["category"] == "answer"
        assert body["task"]["risk_level"] == "low"
        assert body["approval_event"] is None
        task_id = body["task"]["task_id"]
        fetched = client.get(f"/api/tasks/{task_id}").json()
        assert fetched["task_id"] == task_id


def test_task_without_run_returns_null_not_404(tmp_path: Path, monkeypatch) -> None:
    """尚无 Agent Run 的任务返回 200 + run:null，避免前端批量轮询刷 404 噪音。"""
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"input": "帮我检查项目结构"})
        assert resp.status_code == 200
        task_id = resp.json()["task"]["task_id"]
        body = client.get(f"/api/tasks/{task_id}/run")
        assert body.status_code == 200
        assert body.json() == {"run": None}


def test_search_action_routes_to_browser_executor(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"input": "帮我打开浏览器搜索 Python 文档"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["category"] == "delegate_backend"
        assert body["task"]["preferred_executor"] == "browser"
        assert body["task"]["work_kind"] == "browser"


def test_office_tasks_get_work_kind_without_new_executor(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        cases = [
            ("帮我把这个 Word 文档重新排版", "word"),
            ("分析这个 Excel 数据并生成图表", "excel"),
            ("把这个 PPT 美化一下", "ppt"),
            ("请整理一下报告.docx", "word"),
            ("请整理这个 Excel 文档", "excel"),
        ]
        for text, work_kind in cases:
            resp = client.post("/api/tasks", json={"input": text})
            assert resp.status_code == 200
            task = resp.json()["task"]
            assert task["category"] == "delegate_backend", text
            assert task["work_kind"] == work_kind, text
            assert task["preferred_executor"] is None, text


def test_work_kind_preserves_existing_risk_gate(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"input": "删除这个 Excel 文件"})
        assert resp.status_code == 200
        task = resp.json()["task"]
        assert task["category"] == "request_approval"
        assert task["work_kind"] == "excel"
        assert task["required_approval"] is True


def test_backend_work_routes_to_delegate_backend(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"input": "帮我检查这个项目的代码结构并给出建议"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["category"] == "delegate_backend"
        assert body["task"]["preferred_executor"] is None
        assert body["task"]["risk_level"] in {"low", "medium"}


def test_file_organization_routes_to_delegate_backend(tmp_path: Path, monkeypatch) -> None:
    """整理文件/项目属于后台操作，不应被问答分支抢先吃掉。"""
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"input": "帮我整理 README 文件和项目说明"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["category"] == "delegate_backend"
        assert body["task"]["preferred_executor"] is None


def test_short_chitchat_is_not_a_task(tmp_path: Path, monkeypatch) -> None:
    """顺口一说（哪怕超过 8 个字）不该被判成后台任务。"""
    with make_client(tmp_path, monkeypatch) as client:
        for text in ("就是你看那个落花生。", "你刚才那句话什么意思"):
            resp = client.post("/api/tasks", json={"input": text})
            assert resp.status_code == 200
            assert resp.json()["task"]["category"] == "answer", text


def test_interaction_kind_distinguishes_casual_project_and_work() -> None:
    casual = classify_task_input("你今天怎么样")
    assert casual.category == "answer"
    assert casual.interaction_kind == "casual"

    project = classify_task_input("这个项目现在进行到哪一步了")
    assert project.category == "answer"
    assert project.work_kind == "project"
    assert project.interaction_kind == "project"

    work = classify_task_input("帮我检查这个项目的代码结构")
    assert work.category == "delegate_backend"
    assert work.interaction_kind == "work"


def test_plain_command_routes_to_expected_executor(tmp_path: Path, monkeypatch) -> None:
    """真指令即使不含「代码/项目」等词，也要落到 medium 才会自动起跑。"""
    with make_client(tmp_path, monkeypatch) as client:
        cases = [
            ("帮我改一下 README 的错别字", "delegate_backend", None),
            ("查一下石家庄中考招生政策", "delegate_backend", "browser"),
            ("打开闲鱼主页", "delegate_backend", "browser"),
        ]
        for text, category, executor in cases:
            resp = client.post("/api/tasks", json={"input": text})
            assert resp.status_code == 200
            body = resp.json()
            assert body["task"]["category"] == category, text
            assert body["task"]["preferred_executor"] == executor, text
            assert body["task"]["risk_level"] == "medium", text


def test_route_endpoint_and_task_listing(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks/route", json={"input": "帮我改一下这个项目代码"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["category"] == "delegate_backend"
        assert body["task"]["preferred_executor"] is None

        items = client.get("/api/tasks").json()["items"]
        assert items and items[0]["task_id"] == body["task"]["task_id"]


def test_task_status_lifecycle(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        task_id = client.post("/api/tasks", json={"input": "帮我检查项目代码"}).json()["task"]["task_id"]

        cases = [
            ("running", "/running"),
            ("awaiting_approval", "/approval"),
            ("completed", "/completed"),
            ("failed", "/failed"),
        ]
        for expected, endpoint in cases:
            resp = client.post(f"/api/tasks/{task_id}{endpoint}")
            assert resp.status_code == 200
            assert resp.json()["task"]["status"] == expected
            assert client.get(f"/api/tasks/{task_id}").json()["status"] == expected


def test_missing_task_status_update_returns_404(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks/not-found/completed")
        assert resp.status_code == 404


def test_high_risk_routes_to_approval_and_updates_widget_state(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"input": "帮我删除临时文件"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["category"] == "request_approval"
        assert body["task"]["required_approval"] is True
        assert body["approval_event"]["event_type"] == "task.approval_required"
        state = client.get("/api/widget/state").json()["widget_state"]
        assert state["state"] == "awaiting_approval"


def test_url_message_routes_to_backend_web_task() -> None:
    task = classify_task_input(
        "https://mp.weixin.qq.com/s/LsCjMbsbKXvBgKVspOlczw我想让你整理和提炼这个公众号的内容"
    )
    assert task.category == "delegate_backend"
    assert task.risk_level == "medium"
    assert task.required_approval is False

    short = classify_task_input("总结一下这篇文章 https://example.com/a")
    assert short.category == "delegate_backend"
    assert short.risk_level == "medium"


def test_confirm_all_promotes_non_answer_to_approval(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch, permission_level="confirm_all") as client:
        resp = client.post("/api/tasks", json={"input": "帮我打开浏览器搜索 Python 文档"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["category"] == "request_approval"
        assert body["approval_event"]["event_type"] == "task.approval_required"


def test_chat_auto_routes_and_replies_to_browser_task(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch, llm_provider=DummyProvider()) as client:
        async def _fake_execute(task, *, executor=None, mode="read-only", cwd=None):
            return object()

        # 单元测试不启动真实 Playwright：只验证对话页自动起跑分支与回执文案。
        monkeypatch.setattr(
            client.app.state.agent_run_manager, "execute", _fake_execute
        )
        resp = client.post("/api/chat/stream", json={"message": "打开页面搜索 DeskMate"})
        assert resp.status_code == 200
        tasks = client.get("/api/tasks").json()["items"]
        assert tasks and tasks[0]["category"] == "delegate_backend"
        assert tasks[0]["preferred_executor"] == "browser"
        assert tasks[0]["status"] == "queued"

        conversations = client.get("/api/conversations").json()["items"]
        conversation_id = conversations[0]["conversation_id"]
        messages = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assert "后台执行" in messages[-1]["content"]


def test_chat_done_exposes_interaction_kind(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch, llm_provider=DummyProvider()) as client:
        resp = client.post("/api/chat/stream", json={"message": "你今天怎么样"})
        assert resp.status_code == 200
        assert '"interaction_kind": "casual"' in resp.text


def test_chat_task_keeps_project_binding(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with make_client(tmp_path, monkeypatch, llm_provider=DummyProvider()) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "你今天怎么样", "project": str(project)},
        )
        assert resp.status_code == 200
        task = client.get("/api/tasks").json()["items"][0]
        assert task["project"] == str(project)
