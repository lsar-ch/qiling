// 挂件状态契约 —— 镜像自 deskmate_contracts/widget.py。
export type WidgetState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "executing"
  | "awaiting_approval"
  | "completed"
  | "interrupted";

export interface WidgetStatusReport {
  report_id: string;
  state: WidgetState;
  task_id: string | null;
  message: string | null;
  timestamp: string;
}
