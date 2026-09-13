"""Step 9.5 P1：情绪名归一化与映射表（借鉴 here emotion_resolver.py）。"""

from __future__ import annotations

from typing import get_args

import pytest

from deskmate_contracts.widget import ExpressionEmotion
from app.core.emotion_resolver import (
    EMOTION_VISUAL_HINTS,
    canonical_emotions,
    resolve_emotion,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 英文别名与大小写/空白容错
        ("neutral", "neutral"),
        ("JOY", "success"),
        (" joy ", "success"),
        ("happy", "success"),
        ("completed", "success"),
        ("done", "success"),
        ("failed", "error"),
        ("sad", "error"),
        ("shock", "confused"),
        ("surprised", "confused"),
        ("awaiting approval", "confused"),
        ("thinking", "thinking"),
        ("listening", "attentive"),
        ("unknown_tag", "neutral"),
        # 中文别名
        ("开心", "success"),
        ("完成", "success"),
        ("失败", "error"),
        ("难过", "error"),
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
