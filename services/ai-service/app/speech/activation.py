"""语音意图路由：唤醒词（= 唤醒前缀 + 角色名）与静默指令识别。

判定在 STT 之后、LLM 之前执行；命中后由调用方切换语音模式，
不需要把唤醒/静默当成普通对话发给模型。
"""

from __future__ import annotations

import difflib
import re

from pypinyin import lazy_pinyin

_NOISE_RE = re.compile(r"[\s\W_]+", flags=re.UNICODE)
_WAKE_PHONETIC_THRESHOLD = 0.75


def _phonetic(text: str) -> str:
    """无调拼音串，用于角色名谐音容错（千问 ≈ 请问/千万）。"""
    return "".join(lazy_pinyin(text))


def normalize(text: str) -> str:
    """去空白/标点，便于用包含关系匹配中文口令。"""
    return _NOISE_RE.sub("", text).lower()


def build_wake_texts(persona_name: str, prefixes: list[str]) -> list[str]:
    """生成「你好千问 / 嗨千问…」等唤醒文本。"""
    name = normalize(persona_name)
    texts = [normalize(f"{p}{persona_name}") for p in prefixes]
    if name and name not in texts:
        texts.append(name)  # 角色名本身也算（设置里可只留名字）
    return [t for t in texts if t]


def match_sleep(text: str, sleep_phrases: list[str]) -> str | None:
    normalized = normalize(text)
    for phrase in sleep_phrases:
        if normalize(phrase) in normalized:
            return phrase
    return None


def match_wake(text: str, persona_name: str, prefixes: list[str]) -> str | None:
    normalized = normalize(text)
    name = normalize(persona_name)
    wake_texts = build_wake_texts(persona_name, prefixes)
    # 唤醒词取最长优先，避免「你好千问你好千问」等噪音误判已可容忍
    for candidate in sorted(wake_texts, key=len, reverse=True):
        if candidate in normalized:
            return candidate
    # 兜底：问候前缀 + 角色名谐音近似（ASR 常把角色名听成近音词）。
    # 仍要求以唤醒前缀开头、整句与唤醒词长度相当，长句普通对话不受影响。
    if name:
        name_py = _phonetic(name)
        for prefix in sorted(prefixes, key=len, reverse=True):
            clean_prefix = normalize(prefix)
            if not clean_prefix or not normalized.startswith(clean_prefix):
                continue
            rest = normalized[len(clean_prefix):]
            if not rest or len(rest) > len(name) + 2:
                continue
            if (
                difflib.SequenceMatcher(None, _phonetic(rest), name_py).ratio()
                >= _WAKE_PHONETIC_THRESHOLD
            ):
                return name
    return None


def classify_intent(
    text: str,
    *,
    persona_name: str = "千问",
    wake_prefixes: list[str] | None = None,
    sleep_phrases: list[str] | None = None,
) -> str:
    """返回 intent：wake | sleep | chat（静默指令优先于唤醒，避免歧义）。"""
    prefixes = wake_prefixes or ["你好", "嗨"]
    phrases = sleep_phrases or ["暂时静默", "先静默", "先别说话", "别说话", "安静一下", "静默"]
    if match_sleep(text, phrases):
        return "sleep"
    if match_wake(text, persona_name, prefixes):
        return "wake"
    return "chat"
