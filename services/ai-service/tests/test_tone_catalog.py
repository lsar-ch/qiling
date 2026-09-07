"""语音校准目录：加载、结构与范围校验。"""

from __future__ import annotations

from app.speech.tone_catalog import load_validated, validate_catalog


def test_catalog_loads_and_validates() -> None:
    catalog = load_validated()
    assert validate_catalog(catalog) == []
    assert "neutral" in catalog["emotions"]
    assert "carrier_sentence" in catalog
    assert len(catalog["emotions"]) >= 8


def test_every_emotion_has_provider_mapping_and_sentence() -> None:
    catalog = load_validated()
    for key, item in catalog["emotions"].items():
        assert isinstance(item["params"]["speed"], (int, float))
        assert "instruction" in item["dashscope"]
        assert "emotion" in item["volcengine"]
        assert item["test_sentence_zh"].strip()


def test_instruction_differs_across_emotions() -> None:
    """至少若干情绪应带不同 instruction，避免目录退化为单一语气。"""
    catalog = load_validated()
    instructions = {
        item["dashscope"]["instruction"]
        for item in catalog["emotions"].values()
        if item["dashscope"].get("instruction")
    }
    assert len(instructions) >= 4


def test_params_within_expected_bounds() -> None:
    catalog = load_validated()
    for item in catalog["emotions"].values():
        assert 0.8 <= item["params"]["speed"] <= 1.2
        assert 0.9 <= item["params"]["pitch"] <= 1.2
        assert 0.9 <= item["params"]["volume"] <= 1.1
