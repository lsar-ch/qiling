// 任务契约 —— 镜像自 deskmate_contracts/task.py。
export type TaskCategory =
  | "answer"
  | "execute_frontend"
  | "delegate_backend"
  | "request_approval";
export type RiskLevel = "low" | "medium" | "high";
export type TaskStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface Task {
  task_id: string;
  conversation_id: string | null;
  input: string;
  category: TaskCategory;
  risk_level: RiskLevel;
  complexity: "simple" | "medium" | "complex";
  estimated_duration: "short" | "medium" | "long";
  required_approval: boolean;
  preferred_executor: string | null;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
}
