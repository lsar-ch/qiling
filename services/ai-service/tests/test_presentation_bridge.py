"""Windows 回迁回归：角色卡必须按 UTF-8 显式读取。"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.core.presentation_bridge import PresentationBridge


def test_read_persona_utf8_chinese(tmp_path: Path) -> None:
    (tmp_path / "chinese.yaml").write_text(
        yaml.safe_dump({"name": "中文角色"}, allow_unicode=True),
        encoding="utf-8",
    )
    raw = PresentationBridge(tmp_path)._read_persona("chinese")
    assert raw is not None
    assert raw["name"] == "中文角色"


def test_presentation_motion_family_and_art_style(tmp_path: Path) -> None:
    raw = {
        "id": "motion",
        "name": "测试",
        "kind": "cat",
        "motion_family": "anime",
        "art_style": "chibi",
        "avatar": "",
    }
    pres = PresentationBridge(tmp_path)._build_presentation("motion", raw)
    assert pres.style == "anime"
    assert pres.motion_family == "anime"
    assert pres.art_style == "chibi"

    fallback = PresentationBridge(tmp_path)._build_presentation(
        "fallback", {"id": "fallback", "name": "回退", "kind": "cat", "avatar": ""}
    )
    assert fallback.style == "animal"
    assert fallback.motion_family == "animal"
    assert fallback.art_style is None


def test_presentation_vrm_path(tmp_path: Path) -> None:
    """persona 配置声明 vrm 时，asset 带出 vrm_path 供挂件走 3D 渲染。"""
    bridge = PresentationBridge(tmp_path)
    pres = bridge._build_presentation(
        "vrm3d", {"id": "vrm3d", "name": "3D", "avatar": "/a.png", "vrm": "model.vrm"}
    )
    assert pres.asset == {"avatar_url": "/a.png", "vrm_path": "model.vrm"}

    plain = bridge._build_presentation(
        "plain", {"id": "plain", "name": "2D", "avatar": "/a.png"}
    )
    assert plain.asset == {"avatar_url": "/a.png"}


def test_presentation_vrm_motion_config_is_preserved(tmp_path: Path) -> None:
    """动作实验室保存的 vrm 播放配置与模型路径互不覆盖。"""
    bridge = PresentationBridge(tmp_path)
    pres = bridge._build_presentation(
        "vrm3d",
        {
            "id": "vrm3d",
            "name": "3D",
            "avatar": "",
            "vrm": "model.vrm",
            "presentation": {
                "vrm": {"loop_triggers": ["idle", "speaking"], "crossfade_ms": 240}
            },
        },
    )
    assert pres.vrm == {"loop_triggers": ["idle", "speaking"], "crossfade_ms": 240}
    assert pres.asset == {"vrm_path": "model.vrm"}


def test_presentation_animal_motion_config_is_preserved(tmp_path: Path) -> None:
    """GLB 动物模型与抽象动作清单必须一起下发，换角色时才可复用动作映射。"""
    bridge = PresentationBridge(tmp_path)
    animal = {
        "model": "model.glb",
        "motionSet": "cat_walk_v1",
        "actions": {"idle": [{"clip": "sit_idle"}], "executing": [{"clip": "walk"}]},
        "fallbacks": {"idle": ["walk"]},
    }
    pres = bridge._build_presentation(
        "pet",
        {
            "id": "pet",
            "name": "动物",
            "kind": "cat",
            "glb": "model.glb",
            "presentation": {"style": "animal", "animal": animal},
        },
    )
    assert pres.animal == animal
    assert pres.asset == {"glb_path": "model.glb"}


def test_build_reads_presentation_without_event_history(tmp_path: Path) -> None:
    """挂件冷启动时事件可能已被历史窗口冲掉，必须能按角色卡直接重建。"""
    (tmp_path / "pet.yaml").write_text(
        "id: pet\nname: 宠物\nkind: cat\nglb: model.glb\n",
        encoding="utf-8",
    )
    bridge = PresentationBridge(tmp_path)

    presentation = bridge.build("pet")

    assert presentation is not None
    assert presentation.persona_id == "pet"
    assert presentation.asset == {"glb_path": "model.glb"}
    assert bridge.build("missing") is None
