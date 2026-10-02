"""契约一致性：TS 镜像接口的字段必须与 pydantic 单一事实源一致。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT

TS_DIR = REPO_ROOT / "packages" / "contracts" / "ts" / "src"

# py 模型名 → TS 接口名（同名镜像）
MIRROR_MAP: dict[str, tuple[str, str]] = {
    "AgentInfo": ("agent", "AgentInfo"),
    "SkillInfo": ("extension", "SkillInfo"),
    "SkillDetail": ("extension", "SkillDetail"),
    "McpServerInfo": ("extension", "McpServerInfo"),
    "McpToolInfo": ("extension", "McpToolInfo"),
    "OfficeToolInfo": ("extension", "OfficeToolInfo"),
    "CharacterConfig": ("character", "CharacterConfig"),
    "PersonaPresentation": ("widget", "PersonaPresentation"),
    "EventEnvelope": ("events", "EventEnvelope"),
    "WidgetStatusReport": ("widget", "WidgetStatusReport"),
    "Task": ("task", "Task"),
    "ApprovalRequest": ("approval", "ApprovalRequest"),
    "DocOverview": ("memory", "DocOverview"),
    "ConversationMessage": ("conversation", "ConversationMessage"),
    "RecordingSession": ("recording", "RecordingSession"),
    "VoiceParams": ("voice", "VoiceParams"),
    "VoiceSettings": ("voice", "VoiceSettings"),
    "ProjectNode": ("project", "ProjectNode"),
}

_PROP_RE = re.compile(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??:", re.MULTILINE)


def ts_interface_keys(file_stem: str, interface: str) -> set[str]:
    text = (TS_DIR / f"{file_stem}.ts").read_text(encoding="utf-8")
    match = re.search(rf"interface {re.escape(interface)} \{{(.*?)\n\}}", text, re.S)
    assert match, f"TS interface {interface} not found in {file_stem}.ts"
    return {m.group(1) for m in _PROP_RE.finditer(match.group(1))}


def import_model(model_name: str):
    import importlib

    return getattr(importlib.import_module("deskmate_contracts"), model_name)


@pytest.mark.parametrize("model_name", sorted(MIRROR_MAP))
def test_ts_mirror_matches_pydantic(model_name: str) -> None:
    file_stem, interface = MIRROR_MAP[model_name]
    py_keys = set(import_model(model_name).model_fields.keys())
    ts_keys = ts_interface_keys(file_stem, interface)
    assert py_keys == ts_keys, (
        f"{model_name} 契约不同步：\n"
        f"  仅在 pydantic: {sorted(py_keys - ts_keys)}\n"
        f"  仅在 TS 镜像:  {sorted(ts_keys - py_keys)}"
    )
