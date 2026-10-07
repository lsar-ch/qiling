// 任务契约 —— 镜像自 qiling_contracts/task.py。
export type TaskCategory =
  | "answer"
  | "execute_frontend"
  | "delegate_backend"
  | "request_approval";
export type WorkKind =
  | "general"
  | "code"
  | "browser"
  | "word"
  | "excel"
  | "ppt"
  | "pdf"
  | "image"
  | "email"
  | "project";
export type InteractionKind = "casual" | "project" | "work";
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
  project: string | null;
  input: string;
  category: TaskCategory;
  work_kind: WorkKind;
  interaction_kind: InteractionKind;
  risk_level: RiskLevel;
  complexity: "simple" | "medium" | "complex";
  estimated_duration: "short" | "medium" | "long";
  required_approval: boolean;
  preferred_executor: string | null;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
}
