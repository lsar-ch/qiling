// EventEnvelope v0.1 —— 对应 docs/V1-INTERFACES.md §3。
// 镜像自 packages/contracts/py/deskmate_contracts/events.py。

export type EventSource =
  | "conversation"
  | "speech"
  | "task"
  | "agent_router"
  | "memory"
  | "widget"
  | "system";

export type EventType =
  | "conversation.input"
  | "conversation.transcript"
  | "conversation.response"
  | "conversation.completed"
  | "speech.started"
  | "speech.stopped"
  | "speech.interrupted"
  | "task.classified"
  | "task.started"
  | "task.progress"
  | "task.approval_required"
  | "task.completed"
  | "task.failed"
  | "task.cancelled"
  | "task.approval_reminder"
  | "task.timed_out"
  | "memory.created"
  | "memory.updated"
  | "memory.entry.deleted"
  | "system.health"
  | "system.error";

export interface EventEnvelope {
  event_id: string;
  event_type: EventType;
  timestamp: string;
  conversation_id: string | null;
  task_id: string | null;
  source: EventSource;
  payload: Record<string, unknown>;
}
