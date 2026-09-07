// Agent 契约 —— 镜像自 deskmate_contracts/agent.py。

export type AgentIntegrationStatus =
  | "ready"
  | "pending"
  | "not_installed"
  | "error";

export interface AgentInfo {
  name: string;
  label: string;
  adapter: string;
  integration_status: AgentIntegrationStatus;
  available: boolean;
  enabled: boolean;
  version: string | null;
  command: string | null;
  protocol: string | null;
  capabilities: string[];
  tags: string[];
  source_url: string | null;
  detail: string;
}
