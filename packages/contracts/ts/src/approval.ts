// 授权请求契约 —— 镜像自 deskmate_contracts/approval.py。
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";
export type ApprovalDecision = "approved" | "rejected";

export interface ApprovalRequest {
  approval_id: string;
  task_id: string | null;
  action: string;
  description: string;
  risk_level: "medium" | "high";
  expires_at: string;
  status: ApprovalStatus;
  created_at: string;
}
