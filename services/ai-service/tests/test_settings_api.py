from __future__ import annotations

import json
import io
import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.config import load_settings
from app.core.vrm_validator import REQUIRED_VRMA_BONES
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


def test_persona_preset_roundtrip_and_clear(tmp_path: Path, monkeypatch) -> None:
    """预设字段可写入、可清空，且后续不带该字段的更新不会覆盖预设。"""
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
                "preset": "companion",
            },
        )
        assert created.status_code == 200
        hero = next(
            item for item in client.get("/api/personas").json()["items"] if item["id"] == "hero"
        )
        assert hero["preset"] == "companion"

        cleared = client.put("/api/personas/hero", json={
            "id": "hero",
            "name": "小助手",
            "kind": "assistant",
            "preset": None,
        })
        assert cleared.status_code == 200
        hero = next(
            item for item in client.get("/api/personas").json()["items"] if item["id"] == "hero"
        )
        assert hero["preset"] is None

def test_persona_motion_family_roundtrip_and_preserved(tmp_path: Path, monkeypatch) -> None:
    """动作族/画风可写入，且后续不带该字段的更新不会覆盖。"""
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
                "motion_family": "animal",
                "art_style": "chibi",
            },
        )
        assert created.status_code == 200
        hero = next(
            item for item in client.get("/api/personas").json()["items"] if item["id"] == "hero"
        )
        assert hero["motion_family"] == "animal"
        assert hero["art_style"] == "chibi"

        updated = client.put(
            "/api/personas/hero",
            json={"id": "hero", "name": "小助手", "kind": "assistant"},
        )
        assert updated.status_code == 200
        hero = next(
            item for item in client.get("/api/personas").json()["items"] if item["id"] == "hero"
        )
        assert hero["motion_family"] == "animal"
        assert hero["art_style"] == "chibi"


def test_setup_status_and_completion(tmp_path: Path, monkeypatch) -> None:
    """首次启动引导：初始未完成且 echo 模式缺 LLM；写入 setup_completed 后持久化。"""
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n", encoding="utf-8"
    )
    (tmp_path / "config" / "personas" / "default.yaml").write_text(
        "id: default\nname: 千问\nkind: assistant\nlanguage: zh-CN\n",
        encoding="utf-8",
    )
    settings = load_settings()
    settings.llm_provider = "echo"
    settings.llm_api_key = None
    settings.llm_base_url = None
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/setup/status").json()
        assert status["completed"] is False
        assert "llm" in status["missing"]
        assert status["llm_configured"] is False

        # 公共设置里也带 setup_completed 标志
        assert client.get("/api/settings").json()["setup_completed"] is False

        # 完成引导：配置 LLM + 标记完成
        updated = client.put(
            "/api/settings",
            json={
                "llm_base_url": "https://api.example.com/v1",
                "llm_api_key": "sk-test-123",
                "llm_model": "test-model",
                "setup_completed": True,
            },
        ).json()
        assert updated["setup_completed"] is True
        assert updated["llm"]["api_key_configured"] is True

        status2 = client.get("/api/setup/status").json()
        assert status2["completed"] is True
        assert status2["llm_configured"] is True
        assert status2["missing"] == []

        # 持久化：重读 overrides 仍为已完成
        assert client.get("/api/settings").json()["setup_completed"] is True

        # 密钥值不出现在任何响应里
        blob = json.dumps(updated, ensure_ascii=False)
        assert "sk-test-123" not in blob


def test_persona_delete_guards(tmp_path: Path, monkeypatch) -> None:
    """删除角色卡：内置与启用中不可删，删除后不再出现在列表。"""
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "personas" / "default.yaml").write_text("id: default\nname: 千问\n", encoding="utf-8")
    payload = {"id": "cat", "name": "小猫"}
    with TestClient(create_app(load_settings())) as client:
        assert client.post("/api/personas", json=payload).status_code == 200
        assert client.delete("/api/personas/default").status_code == 400
        assert client.delete("/api/personas/missing").status_code == 404
        assert client.put("/api/settings", json={"active_persona_id": "cat"}).json()["active_persona_id"] == "cat"
        assert client.delete("/api/personas/cat").status_code == 409
        assert client.put("/api/settings", json={"active_persona_id": "default"}).status_code == 200
        assert client.delete("/api/personas/cat").status_code == 200
        assert not (tmp_path / "config" / "personas" / "cat.yaml").exists()
        assert [item["id"] for item in client.get("/api/personas").json()["items"]] == ["default"]


def test_persona_asset_file_route(tmp_path: Path, monkeypatch) -> None:
    """layers.json / 图层文件可经资产路由读取；路径穿越与缺失文件返回 404。"""
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text("app:\n  version: 0.1.0\n", encoding="utf-8")
    (tmp_path / "config" / "personas" / "default.yaml").write_text("id: default\nname: 千问\n", encoding="utf-8")
    asset_dir = tmp_path / "data" / "persona-assets" / "default"
    (asset_dir / "layers").mkdir(parents=True)
    (asset_dir / "layers" / "eyes.png").write_bytes(b"fake-png")
    (asset_dir / "layers.json").write_text(
        json.dumps({"layers": [{"id": "eyes", "file": "layers/eyes.png", "z": 1, "role": "eyes"}]}),
        encoding="utf-8",
    )
    with TestClient(create_app(load_settings())) as client:
        layers = client.get("/api/personas/default/asset/layers.json")
        assert layers.status_code == 200
        assert layers.json()["layers"][0]["role"] == "eyes"
        image = client.get("/api/personas/default/asset/layers/eyes.png")
        assert image.status_code == 200
        assert image.content == b"fake-png"
        assert client.get("/api/personas/default/asset/../settings.yaml").status_code == 404
        assert client.get("/api/personas/default/asset/%2e%2e/settings.yaml").status_code == 404
        assert client.get("/api/personas/missing/asset/layers.json").status_code == 404


def _minimal_glb(doc: dict, bin_bytes: bytes = b"") -> bytes:
    """构造最小 GLB：只含 JSON chunk（可选 BIN），供闸门测试用。"""
    import json
    import struct

    json_bytes = json.dumps(doc).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    chunks = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    if bin_bytes:
        padded = bin_bytes + b"\x00" * ((4 - len(bin_bytes) % 4) % 4)
        chunks += struct.pack("<II", len(padded), 0x004E4942) + padded
    total = 12 + len(chunks)
    return struct.pack("<4sII", b"glTF", 2, total) + chunks


def _vrma_doc() -> dict:
    """最小合规 VRMA：闸门要求 humanoid.humanBones 带 VRM 1.0 必备骨。"""
    return {
        "extensionsUsed": ["VRMC_vrm_animation"],
        "animations": [{"channels": []}],
        "extensions": {
            "VRMC_vrm_animation": {
                "humanoid": {
                    "humanBones": {
                        name: {"node": 0} for name in REQUIRED_VRMA_BONES
                    }
                }
            }
        },
    }


def _spec_vrm_doc() -> dict:
    """符合 §3 规格的最小 VRM 1.0 文档（含 15 表情 / 人骨 / spring）。"""
    bones = [
        "hips", "spine", "chest", "upperChest", "neck", "head",
        "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
        "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
        "leftUpperLeg", "leftLowerLeg", "leftFoot",
        "rightUpperLeg", "rightLowerLeg", "rightFoot",
    ]
    nodes = [
        {"name": "Hips"},
        {"name": "Head"},
        {"name": "LeftUpperArm"},
        {"name": "RightUpperArm"},
    ]
    human_bones = {}
    for i, name in enumerate(bones):
        if name == "hips":
            human_bones[name] = {"node": 0}
        elif name == "head":
            human_bones[name] = {"node": 1}
        elif name == "leftUpperArm":
            human_bones[name] = {"node": 2}
        elif name == "rightUpperArm":
            human_bones[name] = {"node": 3}
        else:
            human_bones[name] = {"node": 0}
    presets = [
        "aa", "ih", "ou", "ee", "oh", "blink", "happy", "angry", "sad",
        "relaxed", "neutral", "lookUp", "lookDown", "lookLeft", "lookRight",
    ]
    return {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["VRMC_vrm", "VRMC_springBone"],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {
                    "name": "闸门测试",
                    "avatarPermission": "onlyAuthor",
                    "commercialUsage": "personalNonProfit",
                    "modification": "prohibited",
                    "allowRedistribution": False,
                    "creditNotation": "unnecessary",
                    "allowExcessivelyViolentUsage": False,
                    "allowExcessivelySexualUsage": False,
                    "allowPoliticalOrReligiousUsage": False,
                    "allowAntisocialOrHateUsage": False,
                    "thumbnailImage": 0,
                },
                "humanoid": {"humanBones": human_bones},
                "expressions": {"preset": {name: {"morphTargetBinds": []} for name in presets}},
            },
            "VRMC_springBone": {
                "springs": [{"joints": [{"node": 0}, {"node": 1}]}],
            },
        },
        "materials": [{"name": "body"}],
        "images": [],
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0},
                "indices": 1,
                "targets": [{"POSITION": 2} for _ in range(15)],
            }],
        }],
        "accessors": [
            {"count": 100, "type": "VEC3", "componentType": 5126},
            {"count": 300, "type": "SCALAR", "componentType": 5123},
            *[{"count": 100, "type": "VEC3", "componentType": 5126} for _ in range(15)],
        ],
        "nodes": nodes,
    }


def test_import3d_zip_applies_assets_and_yaml(tmp_path: Path, monkeypatch) -> None:
    import zipfile

    import yaml as yaml_lib

    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "personas" / "hero.yaml").write_text(
        "id: hero\nname: 测试\nkind: assistant\navatar: ''\n",
        encoding="utf-8",
    )
    model_bytes = _minimal_glb(_spec_vrm_doc())
    idle_bytes = _minimal_glb(_vrma_doc())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pack/model.vrm", model_bytes)
        zf.writestr("pack/vrma/idle.vrma", idle_bytes)
        zf.writestr("pack/vrma/notatrig.vrma", idle_bytes)
        zf.writestr("pack/avatar.png", b"png-fake")
    buf.seek(0)

    with TestClient(create_app(load_settings())) as client:
        resp = client.post(
            "/api/personas/hero/import3d",
            files={"file": ("pack.zip", buf, "application/zip")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["vrma"] == ["idle"]
        assert body["avatar"] == "/api/personas/hero/avatar"

        assets = tmp_path / "data" / "persona-assets" / "hero"
        assert (assets / "model.vrm").read_bytes() == model_bytes
        assert (assets / "vrma" / "idle.vrma").read_bytes() == idle_bytes
        assert not (assets / "vrma" / "notatrig.vrma").exists()
        raw = yaml_lib.safe_load(
            (tmp_path / "config" / "personas" / "hero.yaml").read_text(encoding="utf-8")
        )
        assert raw["vrm"] == "model.vrm"
        assert raw["avatar_driver"] == "vrm_3d"

        missing = client.post(
            "/api/personas/hero/import3d",
            files={"file": ("empty.zip", io.BytesIO(b"not a zip"), "application/zip")},
        )
        assert missing.status_code == 400


def test_import3d_rejects_non_spec_vrm(tmp_path: Path, monkeypatch) -> None:
    """闸门：不符合规格的 VRM 必须 400 拒绝，且不落盘覆盖已有资产。"""
    import zipfile

    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "personas" / "hero.yaml").write_text(
        "id: hero\nname: 测试\nkind: assistant\navatar: ''\n",
        encoding="utf-8",
    )
    assets = tmp_path / "data" / "persona-assets" / "hero"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "model.vrm").write_bytes(b"previous-good")
    (assets / "vrma").mkdir(exist_ok=True)
    (assets / "vrma" / "idle.vrma").write_bytes(b"previous-idle")

    # 1) 高关节数：模拟未裁剪的 spring（34 关节 > 30）
    joints = [{"node": 0} for _ in range(35)]
    bad = _spec_vrm_doc()
    bad["extensions"]["VRMC_springBone"] = {"springs": [{"joints": joints}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pack/model.vrm", _minimal_glb(bad))
        zf.writestr("pack/vrma/idle.vrma", _minimal_glb(_vrma_doc()))
    buf.seek(0)
    with TestClient(create_app(load_settings())) as client:
        resp = client.post(
            "/api/personas/hero/import3d",
            files={"file": ("bad.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400, resp.text
        assert "spring bone" in resp.json()["detail"]
        # 旧资产必须原样保留，不能被半截导入污染
        assert (assets / "model.vrm").read_bytes() == b"previous-good"
        assert (assets / "vrma" / "idle.vrma").read_bytes() == b"previous-idle"

        # 2) 非 GLB 字节：直接拒绝
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("pack/model.vrm", b"glTF-fake")
        buf.seek(0)
        resp = client.post(
            "/api/personas/hero/import3d",
            files={"file": ("fake.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400, resp.text

        # 3) 坏 VRMA：拒绝，不写入
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("pack/model.vrm", _minimal_glb(_spec_vrm_doc()))
            zf.writestr("pack/vrma/idle.vrma", b"not-a-glb")
        buf.seek(0)
        resp = client.post(
            "/api/personas/hero/import3d",
            files={"file": ("badvrma.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400, resp.text
        assert "VRMA" in resp.json()["detail"]


def test_persona_motions_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """动作实验室：2D 动作覆盖与 3D VRMA 参数可保存、回显，并落到角色卡。"""
    import yaml as yaml_lib

    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "personas" / "hero.yaml").write_text(
        "id: hero\nname: 测试\nkind: assistant\navatar: ''\n",
        encoding="utf-8",
    )
    actions = {
        "human": {
            "idle": [
                {
                    "id": "human-breathe",
                    "durationMs": 4200,
                    "cooldownMs": 6000,
                    "weight": 3,
                    "loop": True,
                }
            ]
        }
    }
    vrm = {"loop_triggers": ["idle", "speaking"], "crossfade_ms": 250}

    with TestClient(create_app(load_settings())) as client:
        missing = client.get("/api/personas/missing/motions")
        assert missing.status_code == 404

        saved = client.put(
            "/api/personas/hero/motions",
            json={"actions": actions, "vrm": vrm},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["actions"] == actions
        assert saved.json()["vrm"] == vrm

        loaded = client.get("/api/personas/hero/motions")
        assert loaded.status_code == 200
        assert loaded.json()["actions"] == actions
        assert loaded.json()["vrm"] == vrm

        raw = yaml_lib.safe_load(
            (tmp_path / "config" / "personas" / "hero.yaml").read_text(encoding="utf-8")
        )
        assert raw["presentation"]["actions"] == actions
        assert raw["presentation"]["vrm"] == vrm


def test_persona_motions_animations_merge(tmp_path: Path, monkeypatch) -> None:
    """调度节奏写入 presentation.animations，且按 key 合并而非整体替换。"""
    import yaml as yaml_lib

    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(
        "app:\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "personas" / "hero.yaml").write_text(
        "id: hero\nname: 测试\nkind: assistant\navatar: ''\n"
        "presentation:\n  animations:\n    breath_rate: 1.5\n",
        encoding="utf-8",
    )

    with TestClient(create_app(load_settings())) as client:
        saved = client.put(
            "/api/personas/hero/motions",
            json={"animations": {"idle_action_interval_ms": 12000, "transition_ms": 400}},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["animations"]["idle_action_interval_ms"] == 12000
        # 未提交的既有键必须保留
        assert saved.json()["animations"]["breath_rate"] == 1.5

        loaded = client.get("/api/personas/hero/motions")
        assert loaded.json()["animations"]["transition_ms"] == 400
        assert loaded.json()["animations"]["breath_rate"] == 1.5

        raw = yaml_lib.safe_load(
            (tmp_path / "config" / "personas" / "hero.yaml").read_text(encoding="utf-8")
        )
        assert raw["presentation"]["animations"]["idle_action_interval_ms"] == 12000


def test_motion_library_serves_shared_clips_only(tmp_path: Path, monkeypatch) -> None:
    """共享动作库只读下发；库名白名单与路径穿越都必须拦掉。"""
    monkeypatch.setenv("DESKMATE_HOME", str(tmp_path))
    (tmp_path / "config" / "personas").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "config" / "agents.yaml", tmp_path / "config" / "agents.yaml")

    for variant in ("female", "animal"):
        d = tmp_path / "data" / "motion-library" / variant
        d.mkdir(parents=True)
        (d / "idle.vrma").write_bytes(b"vrma-" + variant.encode())
    # 新导出的片段：还没写进任何角色卡，也要能在动作实验室里列出来预览
    (tmp_path / "data" / "motion-library" / "female" / "idle_alt.vrma").write_bytes(b"vrma-alt")

    with TestClient(create_app(load_settings())) as client:
        ok = client.get("/api/motion-library/female/idle.vrma")
        assert ok.status_code == 200, ok.text
        assert ok.content == b"vrma-female"

        # animal 目录真实存在，但动物线走 2D 表，不在白名单里
        listing = client.get("/api/motion-library/female")
        assert listing.status_code == 200, listing.text
        assert listing.json()["clips"] == ["idle", "idle_alt"]

        # animal 目录真实存在，但动物线走 2D 表，不在白名单里
        assert client.get("/api/motion-library/animal/idle.vrma").status_code == 404
        assert client.get("/api/motion-library/animal").status_code == 404
        assert client.get("/api/motion-library/female/nope.vrma").status_code == 404
        escaped = client.get("/api/motion-library/female/%2e%2e%2f%2e%2e%2fconfig%2fagents.yaml")
        assert escaped.status_code == 404, escaped.text
