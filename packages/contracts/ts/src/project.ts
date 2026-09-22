export type ProjectNodeKind =
  | "project"
  | "phase"
  | "node"
  | "task"
  | "artifact"
  | "decision"
  | "blocker"
  | "next_step";

export type ProjectNodeStatus =
  | "planned"
  | "in_progress"
  | "completed"
  | "blocked"
  | "pending_confirmation"
  | "cancelled";

export interface ProjectNode {
  node_id: string;
  project: string;
  title: string;
  kind: ProjectNodeKind;
  status: ProjectNodeStatus;
  parent_id: string | null;
  task_ids: string[];
  artifact_paths: string[];
  decision: string | null;
  blocker: string | null;
  next_step: string | null;
  source: string | null;
  created_at: string;
  updated_at: string;
}
