from __future__ import annotations

import json
import io
import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_settings_and_persona_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        """
id: default
name: 千问
kind: assistant
description: 默认角色
personality: [自然, 可靠]
backstory: ""
language: zh-CN
reply_style: 简洁
avatar: ""
voice:
  provider: minimax
  model: speech-2.8-hd
  voice: "Chinese (Mandarin)_Soft_Girl"
  speed: 1.05
  pitch: 1.0
activation:
  persona_name: 千问
  wake_prefixes: ["你好", "嗨"]
  sleep_phrases: ["暂时静默"]
""".strip(),
        encoding="utf-8",
    )
    with TestClient(create_app(load_settings())) as client:
        settings = client.get("/api/settings").json()
        assert settings["active_persona_id"] == "default"
        assert settings["voice"]["tts_voice"] == "Chinese (Mandarin)_Soft_Girl"
        assert settings["voice"]["auto_speak"] is True

        updated = client.put("/api/settings", json={"voice_auto_speak": False}).json()
        assert updated["voice"]["auto_speak"] is False
        assert client.get("/api/voice/status").json()["auto_speak"] is False

        created = client.post(
            "/api/personas",
            json={
                "id": "cat",
                "name": "小猫",
                "kind": "cat",
                "description": "猫型伙伴",
                "personality": ["活泼"],
                "backstory": "",
                "language": "zh-CN",
                "reply_style": "短句",
                "avatar": "",
                "voice": {"voice": "cat_voice", "speed": 1.2, "pitch": 1.1},
                "activation": {"persona_name": "小猫", "wake_prefixes": ["你好"]},
            },
        )
        assert created.status_code == 200

        updated = client.put("/api/settings", json={"active_persona_id": "cat"}).json()
        assert updated["active_persona_id"] == "cat"
        assert client.get("/api/voice/status").json()["activation"]["persona_name"] == "小猫"

    assert (tmp_path / "data" / "settings.local.json").is_file()


def test_existing_environment_is_not_leaked() -> None:
    assert "OPENAI_API_KEY" not in os.environ or os.environ["OPENAI_API_KEY"] != ""


def test_persona_avatar_upload_and_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        "id: default\nname: 默认\navatar: ''\n", encoding="utf-8"
    )
    image = Image.new("RGBA", (512, 1024), (255, 255, 255, 0))
    subject = Image.new("RGBA", (256, 768), (30, 40, 60, 255))
    image.alpha_composite(subject, (128, 128))
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    png = payload.getvalue()

    with TestClient(create_app(load_settings())) as client:
        missing = client.put("/api/personas/missing/avatar", content=png, headers={"content-type": "image/png"})
        assert missing.status_code == 404

        uploaded = client.put("/api/personas/default/avatar", content=png, headers={"content-type": "image/png"})
        assert uploaded.status_code == 200
        assert uploaded.json()["avatar"] == "/api/personas/default/avatar"
        assert uploaded.json()["width"] == 1024
        assert uploaded.json()["height"] == 1024
        assert uploaded.json()["background_removed"] is False
        manifest = json.loads(
            (tmp_path / "data" / "persona-assets" / "default" / "asset-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["mode"] == "artwork"
        assert manifest["main"] == "/api/personas/default/avatar"
        assert manifest["processing"] == "trim-align-canvas"
        assert manifest["content_bbox"][3] == 975
        assert manifest["canvas"]["baseline"] == 976

        # 挂件按 asset-manifest 推算贴边保留量，接口必须原样透出 content_bbox
        listed = client.get("/api/personas/default/asset-manifest")
        assert listed.status_code == 200
        assert listed.json()["content_bbox"] == manifest["content_bbox"]
        assert listed.json()["width"] == 1024
        assert client.get("/api/personas/missing/asset-manifest").status_code == 404

        image = client.get("/api/personas/default/avatar")
        assert image.status_code == 200
        with Image.open(io.BytesIO(image.content)) as normalized:
            assert normalized.size == (1024, 1024)
            assert normalized.mode == "RGBA"
            assert normalized.getchannel("A").getextrema()[0] == 0
            assert normalized.getchannel("A").getbbox()[3] == 976

        invalid = client.put(
            "/api/personas/default/avatar",
            content=b"not an image",
            headers={"content-type": "image/png"},
        )
        assert invalid.status_code == 400


def test_persona_avatar_removes_uniform_background_and_rejects_small_images(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        "id: default\nname: 默认\navatar: ''\n", encoding="utf-8"
    )
    opaque = Image.new("RGB", (512, 512), "white")
    draw = ImageDraw.Draw(opaque)
    draw.rounded_rectangle((128, 72, 384, 440), radius=32, fill=(52, 76, 120))
    opaque_payload = io.BytesIO()
    opaque.save(opaque_payload, format="JPEG", quality=95)
    small = Image.new("RGBA", (64, 64), (255, 255, 255, 0))
    small_payload = io.BytesIO()
    small.save(small_payload, format="PNG")

    with TestClient(create_app(load_settings())) as client:
        opaque_result = client.put(
            "/api/personas/default/avatar",
            content=opaque_payload.getvalue(),
            headers={"content-type": "image/jpeg"},
        )
        assert opaque_result.status_code == 200
        assert opaque_result.json()["background_removed"] is True
        saved = client.get("/api/personas/default/avatar")
        with Image.open(io.BytesIO(saved.content)) as normalized:
            assert normalized.size == (1024, 1024)
            assert normalized.getchannel("A").getextrema()[0] == 0

        small_result = client.put(
            "/api/personas/default/avatar",
            content=small_payload.getvalue(),
            headers={"content-type": "image/png"},
        )
        assert small_result.status_code == 400
        assert "512" in small_result.json()["detail"]


def test_persona_profile_roundtrip_and_preserved_on_update(tmp_path: Path, monkeypatch) -> None:
    """Step 9.5 P1：六段式 profile 可写入；前端不带 profile 的更新不覆盖它。"""
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    with TestClient(create_app(load_settings())) as client:
        created = client.post(
            "/api/personas",
            json={
                "id": "hero",
                "name": "小助手",
                "kind": "assistant",
                "description": "",
                "personality": [],
                "backstory": "",
                "language": "zh-CN",
                "reply_style": "",
                "avatar": "",
                "voice": {},
                "activation": {},
                "profile": {
                    "identity": "桌面上的 AI 工作伙伴",
                    "personality": "自然、亲切（ISFJ）",
                    "speech": "中文短句，适合朗读",
                    "relationship": "并肩推进项目的搭档",
                    "preferences": "喜欢清晰的任务边界",
                    "boundaries": "敏感操作必须确认",
                },
            },
        )
        assert created.status_code == 200

        saved = client.get("/api/personas").json()["items"]
        hero = next(item for item in saved if item["id"] == "hero")
        assert hero["profile"]["identity"] == "桌面上的 AI 工作伙伴"

        # 前端保存时尚未支持 profile 字段 → 更新不应把它冲掉
        updated = client.put(
            "/api/personas/hero",
            json={
                "id": "hero",
                "name": "改名后的助手",
                "kind": "assistant",
                "description": "新描述",
                "personality": ["稳重"],
                "backstory": "",
                "language": "zh-CN",
                "reply_style": "简洁",
                "avatar": "",
                "voice": {},
                "activation": {},
            },
        )
        assert updated.status_code == 200

        saved = client.get("/api/personas").json()["items"]
        hero = next(item for item in saved if item["id"] == "hero")
        assert hero["name"] == "改名后的助手"
        assert hero["description"] == "新描述"
        assert hero["profile"]["identity"] == "桌面上的 AI 工作伙伴"
