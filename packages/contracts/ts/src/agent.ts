// Agent 契约 —— 镜像自 qiling_contracts/agent.py。

export type AgentIntegrationStatus =
  | "ready"
  | "pending"
  | "auth_required"
  | "not_installed"
  | "error";

export interface AgentInfo {
  name: string;
  label: string;
  adapter: string;
  integration_status: AgentIntegrationStatus;
  available: boolean;
  enabled: boolean;
  default_eligible: boolean;
  version: string | null;
  command: string | null;
  protocol: string | null;
  capabilities: string[];
  tags: string[];
  source_url: string | null;
  detail: string;
}
