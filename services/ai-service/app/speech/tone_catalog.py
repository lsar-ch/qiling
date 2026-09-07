"""语音表现校准目录（config/voice_tone/catalog.yaml）的加载与校验。

目录只承载「情绪 → 语音表现参数/指令」的确定性映射；
文案层由 persona.reply_style 负责，不在这里混入。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.config import repo_root

CATALOG_REL = Path("config") / "voice_tone" / "catalog.yaml"
MIN_EMOTIONS = 6
PARAM_BOUNDS = {"speed": (0.5, 2.0), "pitch": (0.5, 2.0), "volume": (0.0, 2.0)}
REQUIRED_KEYS = (
    "label",
    "intent",
    "params",
    "dashscope",
    "volcengine",
    "test_sentence_zh",
)


def catalog_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / CATALOG_REL


def load_catalog(root: Path | None = None) -> dict:
    path = catalog_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"语音校准目录不存在：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "emotions" not in data:
        raise ValueError(f"语音校准目录格式错误：{path}")
    return data


def validate_catalog(data: dict) -> list[str]:
    """返回问题列表；空列表表示通过。"""
    issues: list[str] = []
    emotions = data.get("emotions")
    if not isinstance(emotions, dict) or len(emotions) < MIN_EMOTIONS:
        issues.append(f"emotions 应至少包含 {MIN_EMOTIONS} 个条目")

    carrier = data.get("carrier_sentence")
    if not isinstance(carrier, str) or not carrier.strip():
        issues.append("缺少 carrier_sentence（A/B 载句）")

    for key, item in (emotions or {}).items():
        if not isinstance(item, dict):
            issues.append(f"[{key}] 不是对象")
            continue
        for field in REQUIRED_KEYS:
            if field not in item:
                issues.append(f"[{key}] 缺少字段 {field}")
        params = item.get("params") or {}
        for name, (lo, hi) in PARAM_BOUNDS.items():
            value = params.get(name)
            if not isinstance(value, (int, float)) or not (lo <= value <= hi):
                issues.append(f"[{key}] params.{name}={value!r} 超出范围 {lo}~{hi}")
        for side in ("dashscope", "volcengine"):
            block = item.get(side)
            if not isinstance(block, dict):
                issues.append(f"[{key}] {side} 缺少映射块")
        if not (item.get("test_sentence_zh") or "").strip():
            issues.append(f"[{key}] test_sentence_zh 为空")
    return issues


def load_validated(root: Path | None = None) -> dict:
    data = load_catalog(root)
    issues = validate_catalog(data)
    if issues:
        raise ValueError("语音校准目录校验失败：\n- " + "\n- ".join(issues))
    return data
