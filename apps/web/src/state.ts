// 挂件状态展示辅助（镜像 qiling_contracts/widget.py）
export type WidgetState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "executing"
  | "awaiting_approval"
  | "completed"
  | "interrupted";

export const WIDGET_STATES: WidgetState[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "executing",
  "awaiting_approval",
  "completed",
  "interrupted",
];

export const STATE_LABEL_ZH: Record<WidgetState, string> = {
  idle: "空闲",
  listening: "聆听中",
  thinking: "思考中",
  speaking: "说话中",
  executing: "执行中",
  awaiting_approval: "等待确认",
  completed: "已完成",
  interrupted: "已打断",
};

export interface DemoAction {
  label: string;
  eventType: string;
  source: "speech" | "conversation" | "task" | "memory";
  taskId?: string;
}

export const DEMO_ACTIONS: DemoAction[] = [
  { label: "聆听", eventType: "speech.started", source: "speech" },
  { label: "思考", eventType: "conversation.input", source: "conversation" },
  { label: "说话", eventType: "conversation.response", source: "conversation" },
  { label: "执行", eventType: "task.started", source: "task", taskId: "task_demo" },
  { label: "等待授权", eventType: "task.approval_required", source: "task", taskId: "task_demo" },
  { label: "完成", eventType: "task.completed", source: "task", taskId: "task_demo" },
  { label: "打断", eventType: "speech.interrupted", source: "speech" },
];
