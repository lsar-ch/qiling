"""情绪名归一化与映射表（借鉴 here 的 emotion_resolver.py）。

把任意来源的情绪名（英文 / 中文 / 供应商标签 / 帧文件名）归一化为统一的
ExpressionEmotion，供挂件视觉映射（P2）与简易帧图导入（P3）使用。
原则：确定性、无 IO、未知一律回落 neutral——情绪不由 LLM 自由注入。
"""

from __future__ import annotations

from deskmate_contracts.widget import ExpressionEmotion

# 情绪名（小写、下划线分隔）→ 归一化情绪
EMOTION_ALIASES: dict[str, ExpressionEmotion] = {
    # 空闲/默认
    "neutral": "neutral",
    "normal": "neutral",
    "calm": "neutral",
    "daily": "neutral",
    "平常": "neutral",
    "平静": "neutral",
    "日常": "neutral",
    # 聆听
    "attentive": "attentive",
    "listening": "attentive",
    "listen": "attentive",
    "专注": "attentive",
    "聆听": "attentive",
    "倾听": "attentive",
    # 思考
    "thinking": "thinking",
    "thought": "thinking",
    "ponder": "thinking",
    "思考": "thinking",
    "想想": "thinking",
    # 困惑 / 需要确认
    "confused": "confused",
    "confusing": "confused",
    "puzzled": "confused",
    "unsure": "confused",
    "approval": "confused",
    "awaiting_approval": "confused",
    "困惑": "confused",
    "疑惑": "confused",
    "需要确认": "confused",
    "待确认": "confused",
    # 成功 / 愉快
    "success": "success",
    "successful": "success",
    "completed": "success",
    "complete": "success",
    "done": "success",
    "win": "success",
    "成功": "success",
    "完成": "success",
    # 社交：开心
    "happy": "happy",
    "joy": "happy",
    "joyful": "happy",
    "excited": "happy",
    "glad": "happy",
    "开心": "happy",
    "高兴": "happy",
    "兴奋": "happy",
    "喜悦": "happy",
    # 错误 / 失败 / 负面
    "error": "error",
    "failed": "error",
    "fail": "error",
    "failure": "error",
    "angry": "error",
    "problem": "error",
    "失败": "error",
    "错误": "error",
    "出错": "error",
    "生气": "error",
    # 社交：难过
    "sad": "sad",
    "upset": "sad",
    "难过": "sad",
    "伤心": "sad",
    "失落": "sad",
    # 社交：惊讶
    "surprised": "surprised",
    "shock": "surprised",
    "shocked": "surprised",
    "惊讶": "surprised",
    "吃惊": "surprised",
    "意外": "surprised",
}

# 情绪 → 挂件视觉提示（眼睛/嘴/光环；对应 docs/EXPRESSION-EVENT-SCHEMA.md §3）
EMOTION_VISUAL_HINTS: dict[ExpressionEmotion, dict[str, str]] = {
    "neutral": {"eyes": "正常眨眼", "mouth": "闭合", "aura": "无/弱"},
    "attentive": {"eyes": "睁大/微亮", "mouth": "微张", "aura": "柔和脉冲"},
    "thinking": {"eyes": "半闭", "mouth": "抿嘴", "aura": "旋转/省略号"},
    "confused": {"eyes": "一侧缩小", "mouth": "问号型微张", "aura": "黄色抖动"},
    "success": {"eyes": "弯月笑眼", "mouth": "微笑", "aura": "绿色闪烁"},
    "error": {"eyes": "X 眼/垂眼", "mouth": "下垂", "aura": "红色闪烁"},
    "happy": {"eyes": "弯月笑眼", "mouth": "开口笑", "aura": "暖黄闪烁"},
    "sad": {"eyes": "垂眼", "mouth": "下弯", "aura": "蓝色微光"},
    "surprised": {"eyes": "睁大", "mouth": "圆张", "aura": "紫白闪"},
}


def _normalize_key(raw: str) -> str:
    return (
        raw.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("／", "_")
    )


def resolve_emotion(raw: str | None) -> ExpressionEmotion:
    """情绪名归一化：空值 / 未知名称一律回落 neutral。"""
    if not raw:
        return "neutral"
    return EMOTION_ALIASES.get(_normalize_key(raw), "neutral")


def canonical_emotions() -> tuple[ExpressionEmotion, ...]:
    """全部归一化情绪（覆盖 ExpressionEmotion 全集）。"""
    return (
        "neutral",
        "attentive",
        "thinking",
        "confused",
        "success",
        "error",
        "happy",
        "sad",
        "surprised",
    )


_POSITIVE_HINTS = (
    "太棒", "太好了", "开心", "高兴", "兴奋", "哈哈", "耶", "恭喜", "真不错", "喜欢",
)
_SAD_HINTS = (
    "难过", "伤心", "失落", "遗憾", "抱歉", "沮丧", "叹气", "唉", "辛苦", "心疼",
)
_SURPRISED_HINTS = (
    "哇", "居然", "没想到", "惊讶", "吃惊", "意外", "天哪", "我的天",
)


def infer_emotion(text: str, *, casual: bool) -> ExpressionEmotion:
    """从回复文本做确定性情绪推断，避免额外 LLM 调用。

    只在 casual/companion 模式启用社交情绪；work 模式回退 neutral，
    保持「工作状态由事件决定，不随文本漂移」的可靠性原则。
    """
    if not casual:
        return "neutral"
    source = text or ""
    if any(hint in source for hint in _SAD_HINTS):
        return "sad"
    if any(hint in source for hint in _SURPRISED_HINTS):
        return "surprised"
    if any(hint in source for hint in _POSITIVE_HINTS):
        return "happy"
    return "neutral"
