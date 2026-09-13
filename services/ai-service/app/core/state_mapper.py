"""事件 → 挂件状态 映射（对应 docs/V1-INTERFACES.md §7）。

Step 9.5 扩展：新增情绪推导与 ExpressionEvent 输出。
原则：状态与情绪均由程序事件驱动；LLM 不直接控制动画。
"""

from __future__ import annotations

import logging
from typing import Callable

from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.widget import (
    ExpressionEmotion,
    ExpressionEvent,
    WidgetState,
    WidgetStatusReport,
)

logger = logging.getLogger(__name__)

# ── 事件 → (状态, 中文标签, 情绪) ──────────────────────────────────────

_EVENT_TO_STATE: dict[str, tuple[WidgetState, str | None, ExpressionEmotion]] = {
    # 语音
    "speech.started": ("listening", "聆听中", "attentive"),
    "speech.stopped": ("idle", "空闲", "neutral"),
    "speech.interrupted": ("interrupted", "已打断", "neutral"),
    # 对话
    "conversation.input": ("thinking", "思考中", "thinking"),
    "conversation.transcript": ("thinking", "思考中", "thinking"),
    "conversation.response": ("speaking", "说话中", "neutral"),
    "conversation.completed": ("completed", "回复完成", "success"),
    # 任务
    "task.started": ("executing", "任务执行中", "neutral"),
    "task.progress": ("executing", "任务执行中", "neutral"),
    "task.approval_required": ("awaiting_approval", "需要授权", "confused"),
    "task.completed": ("completed", "任务完成", "success"),
    "task.failed": ("completed", "任务失败", "error"),
    "task.cancelled": ("completed", "任务已取消", "neutral"),
    "task.approval_reminder": ("awaiting_approval", "等待确认超时", "confused"),
    "task.timed_out": ("completed", "任务超时", "error"),
}


def widget_state_for(event_type: str) -> WidgetState | None:
    hit = _EVENT_TO_STATE.get(event_type)
    return hit[0] if hit else None


def emotion_for(event_type: str) -> ExpressionEmotion:
    """从事件类型推导情绪标签。不再映射的事件返回 neutral。"""
    hit = _EVENT_TO_STATE.get(event_type)
    return hit[2] if hit else "neutral"


def _expr_from_envelope(envelope: EventEnvelope) -> ExpressionEvent | None:
    """从 EventEnvelope 构建 ExpressionEvent。

    若事件类型不在映射表中则返回 None（如 memory / system 事件）。
    """
    hit = _EVENT_TO_STATE.get(envelope.event_type)
    if hit is None:
        return None
    state, _message, emotion = hit
    return ExpressionEvent(
        state=state,
        task_id=envelope.task_id,
        timestamp=envelope.timestamp,
        emotion=emotion,
    )


# ── WidgetStateRegistry（保留，供 /api/widget/state 与向后兼容） ──────

class WidgetStateRegistry:
    """维护最新挂件状态，供 GET /api/widget/state 与 WS hello 使用。"""

    def __init__(self) -> None:
        self._current: WidgetStatusReport | None = None

    def update(self, envelope: EventEnvelope) -> WidgetStatusReport | None:
        hit = _EVENT_TO_STATE.get(envelope.event_type)
        if hit is None:
            return None
        state, message, _emotion = hit
        report = WidgetStatusReport(
            state=state,
            task_id=envelope.task_id,
            message=message or envelope.payload.get("message"),
            timestamp=envelope.timestamp,
        )
        # interrupted 是瞬态：完成一次后就应回到 listening
        if state == "interrupted":
            self._current = WidgetStatusReport(
                state="listening",
                message="已打断，继续聆听",
                timestamp=envelope.timestamp,
            )
            return report
        self._current = report
        return report

    def current(self) -> WidgetStatusReport | None:
        return self._current


def make_report_hook(
    registry: WidgetStateRegistry,
) -> Callable[[EventEnvelope], None]:
    def _hook(envelope: EventEnvelope) -> None:
        registry.update(envelope)

    return _hook


# ── 事件总线钩子：自动附加 expression 到 EventEnvelope ─────────────────

def make_expression_hook() -> Callable[[EventEnvelope], None]:
    """创建 on_publish 钩子：为每个事件自动附加 ExpressionEvent。

    用法：
        hub = EventHub(on_publish=make_expression_hook())
        # publish 时自动给 envelope.expression 赋值
    """

    def _hook(envelope: EventEnvelope) -> None:
        if envelope.expression is not None:
            return  # 已有 expression（如手动设置的 bubble），不覆盖
        expr = _expr_from_envelope(envelope)
        if expr is not None:
            envelope.expression = expr.model_dump(mode="json")

    return _hook


def make_composed_hook(
    registry: WidgetStateRegistry,
) -> Callable[[EventEnvelope], None]:
    """组合钩子：状态注册 + expression 自动附加，供 EventHub 单 on_publish 使用。"""
    report_hook = make_report_hook(registry)
    expr_hook = make_expression_hook()

    def _composed(envelope: EventEnvelope) -> None:
        report_hook(envelope)
        expr_hook(envelope)

    return _composed
