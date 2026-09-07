"""Step 3：文字对话闭环（SSE 流式 + 会话保存 + 事件联动）。"""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FakeProvider:
    display_name = "fake"

    def __init__(self, answer: str, chunk: int = 3) -> None:
        self._answer = answer
        self._chunk = chunk

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        for i in range(0, len(self._answer), self._chunk):
            yield self._answer[i : i + self._chunk]


@contextmanager
def make_client(provider: FakeProvider) -> TestClient:
    previous = os.environ.get("DESKMATE_HOME")
    tmp_home = Path(os.environ.get("PYTEST_TMPDIR", "/tmp")) / "deskmate-test-chat"
    tmp_home.mkdir(parents=True, exist_ok=True)
    os.environ["DESKMATE_HOME"] = str(tmp_home)
    (tmp_home / "config" / "personas").mkdir(parents=True, exist_ok=True)
    (tmp_home / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_home / "config" / "system_prompt.md").write_text("你是 DeskMate。", encoding="utf-8")
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_home / "config" / "agents.yaml")
    (tmp_home / "config" / "personas" / "default.yaml").write_text(
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
    try:
        with TestClient(create_app(load_settings(), llm_provider=provider)) as client:
            yield client
    finally:
        if previous is None:
            os.environ.pop("DESKMATE_HOME", None)
        else:
            os.environ["DESKMATE_HOME"] = previous


def parse_sse(text: str) -> list[dict]:
    return [
        __import__("json").loads(line[6:])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def test_full_qa_roundtrip_short() -> None:
    with make_client(FakeProvider("你好呀")) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "在吗"},
        )
        assert resp.status_code == 200
        events = parse_sse(resp.text)
        deltas = "".join(e["content"] for e in events if e["type"] == "delta")
        assert deltas == "你好呀"
        done = next(e for e in events if e["type"] == "done")
        assert done["short"] is True
        assert done["speak_text"] == "你好呀"

        # 事件联动：完成后挂件进入 completed
        state = client.get("/api/widget/state").json()["widget_state"]
        assert state["state"] == "completed"

        # 会话已保存
        conv = client.get(f"/api/conversations/{done['conversation_id']}").json()
        assert [m["content"] for m in conv["messages"]] == ["在吗", "你好呀"]
        assert conv["messages"][0]["role"] == "user"
        assert conv["messages"][1]["role"] == "assistant"


def test_long_reply_flags_expand() -> None:
    long_answer = "这是用于验证长回复展开的一段文字。" * 20
    with make_client(FakeProvider(long_answer)) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "写一份方案"},
        )
        events = parse_sse(resp.text)
        done = next(e for e in events if e["type"] == "done")
        assert done["short"] is False
        # 长回复：语音摘要取开头整句，全文仍完整保存在会话中
        assert len(done["speak_text"]) < len(long_answer)
        assert done["speak_text"].endswith("。")
        assert long_answer.startswith(done["speak_text"])


def test_error_survives_and_saves() -> None:
    class BrokenProvider(FakeProvider):
        async def stream_chat(self, messages, **kwargs):
            raise RuntimeError("网络不可达")
            yield ""  # pragma: no cover

    with make_client(BrokenProvider("")) as client:
        resp = client.post(
            "/api/chat/stream",
            json={"message": "hi"},
        )
        events = parse_sse(resp.text)
        assert any(e["type"] == "error" for e in events)
        done = next(e for e in events if e["type"] == "done")
        conv = client.get(f"/api/conversations/{done['conversation_id']}").json()
        assert "模型调用失败" in conv["messages"][-1]["content"]


def test_conversation_listing() -> None:
    with make_client(FakeProvider("ok")) as client:
        client.post("/api/chat/stream", json={"message": "第一条问题"})
        items = client.get("/api/conversations").json()["items"]
        assert len(items) >= 1
        assert items[0]["message_count"] >= 2
        assert "第一条问题" in items[0]["title"]
