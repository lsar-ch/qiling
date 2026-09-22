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
