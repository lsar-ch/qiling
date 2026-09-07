"""事件 → 挂件状态 映射（对应 docs/V1-INTERFACES.md §7）。

原则：状态由程序事件驱动，动画只是状态可视化；LLM 不直接控制动画。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from deskmate_contracts.events import EventEnvelope
from deskmate_contracts.widget import WidgetState, WidgetStatusReport

# 事件 → 状态（含回归空闲的瞬态映射）
_EVENT_TO_STATE: dict[str, tuple[WidgetState, str | None]] = {
    "speech.started": ("listening", "聆听中"),
    "conversation.input": ("thinking", "思考中"),
    "conversation.transcript": ("thinking", "思考中"),
    "conversation.response": ("speaking", "说话中"),
    "conversation.completed": ("completed", "回复完成"),
    "task.started": ("executing", "任务执行中"),
    "task.progress": ("executing", "任务执行中"),
    "task.approval_required": ("awaiting_approval", "需要授权"),
    "speech.interrupted": ("interrupted", "已打断"),
    "speech.stopped": ("idle", "空闲"),
    "task.completed": ("completed", "任务完成"),
    "task.failed": ("completed", "任务失败"),
    "task.cancelled": ("completed", "任务已取消"),
}


def widget_state_for(event_type: str) -> WidgetState | None:
    hit = _EVENT_TO_STATE.get(event_type)
    return hit[0] if hit else None


class WidgetStateRegistry:
    """维护最新挂件状态，供 GET /api/widget/state 与 WS hello 使用。"""

    def __init__(self) -> None:
        self._current: WidgetStatusReport | None = None

    def update(self, envelope: EventEnvelope) -> WidgetStatusReport | None:
        hit = _EVENT_TO_STATE.get(envelope.event_type)
        if hit is None:
            return None
        state, message = hit
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
