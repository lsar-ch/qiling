"""语音激活：唤醒词/静默指令匹配与 /api/voice/intent 接口。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.speech.activation import classify_intent, match_sleep, match_wake, normalize


def test_normalize_strips_space_and_punct() -> None:
    assert normalize("你好，千问！") == "你好千问"
    assert normalize(" 先  别 说 话 ") == "先别说话"


def test_wake_matches_persona_name() -> None:
    assert match_wake("你好，千问", persona_name="千问", prefixes=["你好", "嗨"])
    assert match_wake("嗨 千问", persona_name="千问", prefixes=["你好", "嗨"])
    assert not match_wake("今天天气怎么样", persona_name="千问", prefixes=["你好", "嗨"])


def test_wake_binds_to_custom_persona() -> None:
    # 角色名换成银月后，「你好，千问」不再唤醒
    assert match_wake("你好，银月", persona_name="银月", prefixes=["你好"])
    assert not match_wake("你好，千问", persona_name="银月", prefixes=["你好"])


def test_wake_tolerates_asr_homophone() -> None:
    # ASR 把「千问」听成近音词：带问候前缀的短句仍视为唤醒
    assert match_wake("你好，请问", persona_name="千问", prefixes=["你好", "嗨"])
    assert match_wake("你好千万", persona_name="千问", prefixes=["你好", "嗨"])
    # 长句普通对话与其它角色名不误醒
    assert not match_wake("你好，请问今天天气怎么样", persona_name="千问", prefixes=["你好"])
    assert not match_wake("你好，银月", persona_name="千问", prefixes=["你好"])


def test_sleep_phrases() -> None:
    assert match_sleep("先暂时静默一下吧", ["暂时静默", "先别说话"]) is not None
    assert match_sleep("帮我查个天气", ["暂时静默"]) is None


def test_classify_priority_and_default() -> None:
    assert classify_intent("你好，千问", persona_name="千问") == "wake"
    assert classify_intent("千问", persona_name="千问") == "wake"
    assert classify_intent("你先别说话", persona_name="千问") == "sleep"
    assert classify_intent("帮我订个外卖", persona_name="千问") == "chat"
    # 同时含静默指令与角色名：静默优先
    assert classify_intent("千问，先别说话", persona_name="千问") == "sleep"


def _client():
    return TestClient(create_app(load_settings()))


def test_intent_api_wake_and_sleep() -> None:
    with _client() as client:
        headers = {"X-Voice-Client": "web"}
        assert client.post("/api/voice/lease", headers=headers).json()["acquired"] is True
        wake = client.post("/api/voice/intent", json={"text": "你好，千问"}, headers=headers).json()
        assert wake["intent"] == "wake"
        assert "千问" in wake["reply"]

        sleep = client.post("/api/voice/intent", json={"text": "暂时静默"}, headers=headers).json()
        assert sleep["intent"] == "sleep"
        assert "安静" in sleep["reply"]

        chat = client.post("/api/voice/intent", json={"text": "帮我看看天气"}, headers=headers).json()
        assert chat["intent"] == "chat"


def test_status_includes_activation() -> None:
    with _client() as client:
        body = client.get("/api/voice/status").json()
        act = body["activation"]
        assert act["enabled"] is True
        assert act["persona_name"]
        assert act["default_state"] in ("listening", "sleeping")
