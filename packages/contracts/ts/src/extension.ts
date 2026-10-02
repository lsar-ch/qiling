// 技能与 MCP 扩展契约 —— 镜像自 deskmate_contracts/extension.py。

export type ExtensionSource = "builtin" | "user";

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  source: ExtensionSource;
  enabled: boolean;
  triggers: string[];
  tools: string[];
  has_scripts: boolean;
}

export interface SkillDetail {
  id: string;
  name: string;
  description: string;
  source: ExtensionSource;
  enabled: boolean;
  triggers: string[];
  tools: string[];
  has_scripts: boolean;
  body: string;
}

export type McpTransport = "stdio" | "streamablehttp";
export type McpServerStatus = "not_started" | "ready" | "error" | "disabled";
export type McpToolAccess = "read" | "write";

export interface McpToolInfo {
  name: string;
  description: string;
  access: McpToolAccess;
}

export interface McpServerInfo {
  id: string;
  source: ExtensionSource;
  enabled: boolean;
  transport: McpTransport;
  status: McpServerStatus;
  access: McpToolAccess;
  command: string | null;
  args: string[];
  url: string | null;
  tool_count: number;
  detail: string;
}

export type OfficeToolInstallKind = "builtin" | "pip" | "link";

export interface OfficeToolInfo {
  name: string;
  label: string;
  detail: string;
  homepage: string | null;
  license: string;
  powers: string[];
  install_kind: OfficeToolInstallKind;
  installed: boolean;
}
