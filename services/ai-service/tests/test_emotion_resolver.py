"""Step 9.5 P1：情绪名归一化与映射表（借鉴 here emotion_resolver.py）。"""

from __future__ import annotations

from typing import get_args

import pytest

from deskmate_contracts.widget import ExpressionEmotion
from app.core.emotion_resolver import (
    EMOTION_VISUAL_HINTS,
    canonical_emotions,
    infer_emotion,
    resolve_emotion,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 英文别名与大小写/空白容错
        ("neutral", "neutral"),
        ("JOY", "happy"),
        (" joy ", "happy"),
        ("happy", "happy"),
        ("completed", "success"),
        ("done", "success"),
        ("failed", "error"),
        ("sad", "sad"),
        ("shock", "surprised"),
        ("surprised", "surprised"),
        ("awaiting approval", "confused"),
        ("thinking", "thinking"),
        ("listening", "attentive"),
        ("unknown_tag", "neutral"),
        # 中文别名
        ("开心", "happy"),
        ("完成", "success"),
        ("失败", "error"),
        ("难过", "sad"),
        ("需要确认", "confused"),
        ("思考", "thinking"),
        ("聆听", "attentive"),
        ("平常", "neutral"),
        # 空值
        ("", "neutral"),
        (None, "neutral"),
    ],
)
def test_resolve_emotion(raw: str | None, expected: str) -> None:
    assert resolve_emotion(raw) == expected


def test_visual_hints_cover_all_canonical_emotions() -> None:
    canonical = set(get_args(ExpressionEmotion))
    assert set(EMOTION_VISUAL_HINTS) == canonical
    assert set(canonical_emotions()) == canonical
    for hints in EMOTION_VISUAL_HINTS.values():
        assert set(hints) == {"eyes", "mouth", "aura"}
        assert all(hints[part].strip() for part in ("eyes", "mouth", "aura"))


def test_infer_emotion_only_in_casual_mode() -> None:
    assert infer_emotion("太棒了，我这就帮你搞定！", casual=True) == "happy"
    assert infer_emotion("我有点难过，这个问题没解决。", casual=True) == "sad"
    assert infer_emotion("哇，这个结果居然这么快！", casual=True) == "surprised"
    assert infer_emotion("任务已完成。", casual=True) == "neutral"
    assert infer_emotion("太棒了", casual=False) == "neutral"
