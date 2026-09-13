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
