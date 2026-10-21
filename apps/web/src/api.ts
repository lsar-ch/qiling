// 主界面与 ai-service 通信（同源 /api；开发模式由 Vite 代理转发）。

import type { AgentInfo, AgentIntegrationStatus } from "@qiling/contracts";
import type { EventEnvelope } from "@qiling/contracts";
import type {
  McpServerInfo,
  OfficeToolInfo,
  SkillDetail,
  SkillInfo,
} from "@qiling/contracts";
import type { CompiledMemory, DocOverview, MemoryDoc, SearchHit } from "@qiling/contracts";
import type {
  InteractionKind,
  ProjectNode,
  ProjectNodeKind,
  ProjectNodeStatus,
  Task,
  TaskCategory,
  TaskStatus,
} from "@qiling/contracts";
import type { Reminder, ReminderKind, ReminderRepeat, ReminderStatus } from "@qiling/contracts";

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  time: string;
  uptime_s: number;
  python: string;
  features: string[];
  capabilities: {
    text_chat: boolean;
    voice: boolean;
    memory: boolean;
    agents: {
      default_executor: string;
      ready: string[];
      degraded: { name: string; integration_status: AgentIntegrationStatus }[];
    };
  };
  performance_mode: "quality" | "balanced" | "lite";
  voice_pipeline: {
    stt_ready: boolean;
    tts_ready: boolean;
    vad_working: boolean;
    degradation_reason: string | null;
  };
  recent_activity: Array<{
    event_type: string;
    timestamp: string;
    summary: string;
  }>;
  memory_stats: {
    total_entries: number;
    obsidian_linked: boolean;
    last_compile: string | null;
  };
  diagnostics?: DiagnosticItem[];
}

export interface DiagnosticItem {
  name: string;
  label: string;
  status: "ok" | "degraded" | "error";
  detail: string;
  fix_hint: string | null;
  fix_action: string | null;
}

export interface SessionResponse {
  session_id: string;
  service_url: string;
  ws_url: string;
  auth_required: boolean;
  capabilities: {
    text_chat: boolean;
    voice: boolean;
    memory: boolean;
    codex: boolean;
  };
  model: {
    echo_mode: boolean;
    provider: string;
  };
}

export async function fetchProjectNodes(project: string): Promise<ProjectNode[]> {
  const data = await fetchJson<{ items: ProjectNode[] }>(
    `/api/projects/nodes?project=${encodeURIComponent(project)}`,
  );
  return data.items;
}

export type ProjectNodePayload = {
  project: string;
  title: string;
  kind: ProjectNodeKind;
  status: ProjectNodeStatus;
  parent_id?: string | null;
  task_ids?: string[];
  artifact_paths?: string[];
  decision?: string | null;
  blocker?: string | null;
  next_step?: string | null;
  source?: string | null;
};

async function writeProjectNode(
  method: "POST" | "PUT",
  path: string,
  payload: ProjectNodePayload,
  verb: string,
): Promise<ProjectNode> {
  const resp = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => null);
    throw new Error((detail as { detail?: string } | null)?.detail || `项目节点${verb}失败：HTTP ${resp.status}`);
  }
  return (await resp.json()) as ProjectNode;
}

export async function createProjectNode(payload: ProjectNodePayload): Promise<ProjectNode> {
  return writeProjectNode("POST", "/api/projects/nodes", payload, "创建");
}

export async function updateProjectNode(nodeId: string, payload: ProjectNodePayload): Promise<ProjectNode> {
  return writeProjectNode("PUT", `/api/projects/nodes/${nodeId}`, payload, "更新");
}

export async function deleteProjectNode(nodeId: string): Promise<void> {
  const resp = await fetch(`/api/projects/nodes/${nodeId}`, { method: "DELETE" });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => null);
    throw new Error((detail as { detail?: string } | null)?.detail || `项目节点删除失败：HTTP ${resp.status}`);
  }
}

export type ReminderPayload = {
  kind: ReminderKind;
  text: string;
  remind_at: string;
  repeat: ReminderRepeat;
  task_id?: string | null;
};

export async function fetchReminders(limit = 100): Promise<Reminder[]> {
  const data = await fetchJson<{ items: Reminder[] }>(`/api/reminders?limit=${limit}`);
  return data.items;
}

export async function createReminder(payload: ReminderPayload): Promise<Reminder> {
  const resp = await fetch("/api/reminders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { reminder: Reminder };
  return data.reminder;
}

export async function updateReminder(
  reminderId: string,
  payload: Partial<ReminderPayload> & { status?: ReminderStatus },
): Promise<Reminder> {
  const resp = await fetch(`/api/reminders/${encodeURIComponent(reminderId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { reminder: Reminder };
  return data.reminder;
}

export async function deleteReminder(reminderId: string): Promise<void> {
  const resp = await fetch(`/api/reminders/${encodeURIComponent(reminderId)}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(await readDetail(resp));
}

async function fetchJson<T>(path: string, timeoutMs = 5000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(path, { signal: controller.signal });
    if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`);
    return (await resp.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>("/api/health");
}

export async function fetchAgents(): Promise<{ items: AgentInfo[]; default_executor: string }> {
  return fetchJson<{ items: AgentInfo[]; default_executor: string }>("/api/agents");
}

export async function fetchSkills(): Promise<SkillInfo[]> {
  const data = await fetchJson<{ skills: SkillInfo[] }>("/api/skills");
  return data.skills;
}

export async function fetchSkill(id: string): Promise<SkillDetail> {
  return fetchJson<SkillDetail>(`/api/skills/${encodeURIComponent(id)}`);
}

export async function fetchOfficeTools(): Promise<OfficeToolInfo[]> {
  const data = await fetchJson<{ tools: OfficeToolInfo[] }>("/api/office-tools");
  return data.tools;
}

// 不走 fetchJson：pip 安装动辄几十秒，不能被 5s 超时掐断。
export async function installOfficeTool(
  name: string,
): Promise<{ ok: boolean; message: string; tools: OfficeToolInfo[] }> {
  const resp = await fetch(`/api/office-tools/${encodeURIComponent(name)}/install`, {
    method: "POST",
  });
  const body = await resp.json().catch(() => null);
  if (!resp.ok) {
    throw new Error(
      typeof body?.detail === "string" ? body.detail : `安装请求失败：HTTP ${resp.status}`,
    );
  }
  return body as { ok: boolean; message: string; tools: OfficeToolInfo[] };
}

export async function toggleSkill(id: string, enabled: boolean): Promise<SkillInfo> {
  const resp = await fetch(`/api/skills/${encodeURIComponent(id)}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!resp.ok) throw new Error(`toggle skill -> HTTP ${resp.status}`);
  return (await resp.json()) as SkillInfo;
}

export async function uploadSkillZip(file: File): Promise<SkillInfo> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/skills/upload", { method: "POST", body: form });
  if (!resp.ok) throw new Error(`upload skill -> HTTP ${resp.status}`);
  return (await resp.json()) as SkillInfo;
}

export async function registerSkillDirectory(path: string): Promise<SkillInfo> {
  const resp = await fetch("/api/skills/register-directory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!resp.ok) throw new Error(`register directory -> HTTP ${resp.status}`);
  return (await resp.json()) as SkillInfo;
}

export async function deleteSkill(id: string): Promise<void> {
  const resp = await fetch(`/api/skills/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`delete skill -> HTTP ${resp.status}`);
}

export interface McpServerPayload {
  id: string;
  transport: "stdio" | "streamablehttp";
  access: "read" | "write";
  enabled: boolean;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
}

export async function fetchMcpServers(): Promise<McpServerInfo[]> {
  const data = await fetchJson<{ servers: McpServerInfo[] }>("/api/mcp-servers");
  return data.servers;
}

export async function addMcpServer(payload: McpServerPayload): Promise<void> {
  const resp = await fetch("/api/mcp-servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new Error((body as { detail?: string } | null)?.detail ?? `添加 MCP -> HTTP ${resp.status}`);
  }
}

export async function toggleMcpServer(id: string, enabled: boolean): Promise<void> {
  const resp = await fetch(`/api/mcp-servers/${encodeURIComponent(id)}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!resp.ok) throw new Error(`toggle MCP -> HTTP ${resp.status}`);
}

export async function deleteMcpServer(id: string): Promise<void> {
  const resp = await fetch(`/api/mcp-servers/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`delete MCP -> HTTP ${resp.status}`);
}

export async function testMcpServer(id: string): Promise<{ name: string; description: string }[]> {
  const resp = await fetch(`/api/mcp-servers/${encodeURIComponent(id)}/test`, {
    method: "POST",
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new Error((body as { detail?: string } | null)?.detail ?? `测试 MCP -> HTTP ${resp.status}`);
  }
  const data = (await resp.json()) as { tools: { name: string; description: string }[] };
  return data.tools;
}

export async function fetchMcpTools(id: string): Promise<
  { name: string; description: string; input_schema: Record<string, unknown> }[]
> {
  const data = await fetchJson<{
    tools: { name: string; description: string; input_schema: Record<string, unknown> }[];
  }>(`/api/mcp-servers/${encodeURIComponent(id)}/tools`);
  return data.tools;
}

export async function decideToolApproval(
  approvalId: string,
  decision: "approved" | "rejected",
): Promise<void> {
  const resp = await fetch(
    `/api/mcp-tool-approvals/${encodeURIComponent(approvalId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    },
  );
  if (!resp.ok) throw new Error(`tool approval -> HTTP ${resp.status}`);
}

export interface ToolApprovalView {
  approval_id: string;
  server: string;
  tool: string;
  arguments: string;
}

export interface AgentConfigEntry {
  name: string;
  label: string;
  adapter: string;
  enabled: boolean;
  commands: string[];
  protocol: string | null;
  capabilities: string[];
  source_url: string | null;
  tags: string[];
  detail: string;
  config: Record<string, unknown>;
  /** 该执行器是否已配置自备 API Key（明文永不出接口）。 */
  api_key_configured: boolean;
}

export async function fetchAgentConfig(): Promise<{
  default_executor: string;
  items: AgentConfigEntry[];
}> {
  return fetchJson<{ default_executor: string; items: AgentConfigEntry[] }>("/api/agents/config");
}

export async function updateAgentConfig(
  name: string,
  body: {
    command?: string | null;
    internet_environment?: string | null;
    api_key?: string | null;
    enabled?: boolean;
    set_default?: boolean;
  },
): Promise<AgentInfo> {
  const resp = await fetch(`/api/agents/${encodeURIComponent(name)}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = (await resp.json()) as { detail?: unknown };
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // 保留默认错误信息
    }
    throw new Error(`「${name}」配置保存失败：${detail}`);
  }
  return (await resp.json()) as AgentInfo;
}

export async function loginAgent(name: string, methodId: "api-key" | "chat-gpt"): Promise<AgentInfo> {
  const resp = await fetch(`/api/agents/${encodeURIComponent(name)}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method_id: methodId }),
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = (await resp.json()) as { detail?: unknown };
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // 保留默认错误信息
    }
    throw new Error(`「${name}」登录失败：${detail}`);
  }
  return (await resp.json()) as AgentInfo;
}

export async function addCustomAgent(body: {
  name: string;
  label?: string | null;
  command: string;
  api_key_env?: string | null;
  api_key?: string | null;
}): Promise<AgentInfo> {
  const resp = await fetch("/api/agents/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = (await resp.json()) as { detail?: unknown };
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // 保留默认错误信息
    }
    throw new Error(`添加执行器失败：${detail}`);
  }
  return (await resp.json()) as AgentInfo;
}

export async function refreshAgentDetection(name: string): Promise<AgentInfo> {
  const resp = await fetch(`/api/agents/${encodeURIComponent(name)}/refresh`, {
    method: "POST",
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = (await resp.json()) as { detail?: unknown };
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // 保留默认错误信息
    }
    throw new Error(`「${name}」重新检测失败：${detail}`);
  }
  return (await resp.json()) as AgentInfo;
}

export async function fetchSession(): Promise<SessionResponse> {
  return fetchJson<SessionResponse>("/api/session");
}

export interface PersonaProfileCard {
  identity?: string;
  personality?: string;
  speech?: string;
  relationship?: string;
  preferences?: string;
  boundaries?: string;
  catchphrases?: string[];
  flaws?: string[];
  likes?: string[];
  dislikes?: string[];
}

export interface PersonaCard {
  id: string;
  name: string;
  kind: string;
  description: string;
  personality: string[];
  backstory: string;
  language: string;
  reply_style: string;
  avatar: string;
  voice: {
    provider?: string;
    model?: string;
    voice?: string;
    speed?: number;
    pitch?: number;
    emotion?: string;
    instruction?: string;
  };
  activation: {
    persona_name?: string;
    wake_prefixes?: string[];
    sleep_phrases?: string[];
  };
  llm?: {
    profile_id?: string;
  };
  profile?: PersonaProfileCard | null;
  preset?: "work" | "companion" | "service" | null;
  motion_family?: "human" | "animal" | "anime";
  art_style?: "realistic" | "anime" | "chibi" | "pixel" | null;
}

export type ModelProfileCategory = "text" | "multimodal" | "stt" | "tts";

export interface ModelProfile {
  id: string;
  name: string;
  category: ModelProfileCategory;
  provider: string;
  base_url: string;
  model: string;
  voice: string;
  enabled: boolean;
  is_default: boolean;
  api_key_configured: boolean;
}

export interface ModelProfilePayload {
  id: string;
  name: string;
  category: ModelProfileCategory;
  provider: string;
  base_url?: string;
  model?: string;
  api_key?: string;
  voice?: string;
  enabled: boolean;
  is_default: boolean;
}

export async function fetchModelProfiles(): Promise<ModelProfile[]> {
  const data = await fetchJson<{ items: ModelProfile[] }>("/api/model-profiles");
  return data.items;
}

export async function createModelProfile(payload: ModelProfilePayload): Promise<ModelProfile> {
  const resp = await fetch("/api/model-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as ModelProfile;
}

export async function updateModelProfile(id: string, payload: ModelProfilePayload): Promise<ModelProfile> {
  const resp = await fetch(`/api/model-profiles/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as ModelProfile;
}

export async function deleteModelProfile(id: string): Promise<void> {
  const resp = await fetch(`/api/model-profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(await readDetail(resp));
}

export interface ProviderModelList {
  available: boolean;
  models: string[];
  reason: string | null;
}

/** 拉取供应商的可用模型列表，供「模型名称」做下拉选择。

    编辑态可能还没保存，所以直接带上 base_url / api_key；
    传 profile_id 时后端退回该档案已存的地址与 Key。 */
export async function fetchProviderModels(params: {
  baseUrl?: string;
  apiKey?: string;
  profileId?: string;
}): Promise<ProviderModelList> {
  const query = new URLSearchParams();
  if (params.baseUrl?.trim()) query.set("base_url", params.baseUrl.trim());
  if (params.apiKey?.trim()) query.set("api_key", params.apiKey.trim());
  if (params.profileId) query.set("profile_id", params.profileId);
  return fetchJson<ProviderModelList>(`/api/model-profiles/models?${query.toString()}`, 20000);
}

export async function testModelProfile(id: string): Promise<{ ok: boolean; message: string }> {
  const resp = await fetch(`/api/model-profiles/${encodeURIComponent(id)}/test`, { method: "POST" });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as { ok: boolean; message: string };
}

export interface AppSettings {
  setup_completed: boolean;
  active_persona_id: string;
  ui: { language: string; theme: string };
  permission_level: string;
  performance_mode: "quality" | "balanced" | "lite";
  memory: {
    mode: string;
    budget_chars: number;
    obsidian_vault_path: string;
    obsidian_default_path: string;
    obsidian_configured: boolean;
  };
  llm: {
    provider: string;
    base_url: string;
    model: string;
    api_key_configured: boolean;
  };
  voice: {
    enabled: boolean;
    auto_speak: boolean;
    stt_provider: string;
    stt_model: string;
    tts_provider: string;
    tts_model: string;
    tts_voice: string;
    speed: number;
    pitch: number;
    volume: number;
    emotion: string;
    instruction: string;
    activation_enabled: boolean;
    activation_default_state: string;
    interruption_enabled: boolean;
    auto_barge_in: boolean;
    dashscope_configured: boolean;
    minimax_configured: boolean;
  };
}

export async function fetchSettings(): Promise<AppSettings> {
  return fetchJson<AppSettings>("/api/settings");
}

export async function updateSettings(body: Record<string, unknown>): Promise<AppSettings> {
  const resp = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as AppSettings;
}

export interface SetupStatus {
  completed: boolean;
  missing: string[];
  llm_configured: boolean;
  voice_configured: boolean;
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  return fetchJson<SetupStatus>("/api/setup/status");
}

export async function fetchPersonas(): Promise<PersonaCard[]> {
  const data = await fetchJson<{ items: PersonaCard[] }>("/api/personas");
  return data.items;
}

export async function createPersona(persona: PersonaCard): Promise<PersonaCard> {
  const resp = await fetch("/api/personas", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(persona),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as PersonaCard;
}

export async function updatePersona(persona: PersonaCard): Promise<PersonaCard> {
  const resp = await fetch(`/api/personas/${encodeURIComponent(persona.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(persona),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as PersonaCard;
}

export interface MotionActionOverride {
  id: string;
  className?: string;
  durationMs?: number;
  cooldownMs?: number;
  weight?: number;
  loop?: boolean;
  fx?: string;
}

export type MotionOverrides = Record<string, Record<string, MotionActionOverride[]>>;

export type VrmClipRef =
  | string
  | {
      clip: string;
      repeat?: number;
      timeScale?: number;
      /** 同一 trigger 多候选时的相对权重，缺省 1。 */
      weight?: number;
      /** 同一 trigger 多候选时的冷却毫秒，缺省 0。 */
      cooldownMs?: number;
    };

export interface VrmMotionConfig {
  loop_triggers?: string[];
  crossfade_ms?: number;
  /** 共享动作库（male / female）：配了先从库里解析，库里没有才回退角色自己的 vrma/。 */
  library?: string;
  /**
   * trigger → VRMA 候选。字符串即文件基名（缺省同名）；给数组即多候选，
   * 按 weight 加权随机挑一条，cooldownMs 挡刚播过的。
   */
  actions?: Record<string, VrmClipRef | VrmClipRef[]>;
}

export interface MotionConfig {
  actions: MotionOverrides | null;
  vrm: VrmMotionConfig | null;
  /** presentation.animations：idle_action_interval_ms / transition_ms / breath_rate / blink_interval_ms */
  animations?: Record<string, number> | null;
}

export async function fetchMotions(personaId: string): Promise<MotionConfig> {
  return fetchJson<MotionConfig>(`/api/personas/${encodeURIComponent(personaId)}/motions`);
}

export async function saveMotions(personaId: string, motions: MotionConfig): Promise<MotionConfig> {
  const resp = await fetch(`/api/personas/${encodeURIComponent(personaId)}/motions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(motions),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as MotionConfig;
}

/** 角色资产文件地址（layers.json / vrma / model.vrm）。 */
export function personaAssetUrl(personaId: string, file: string): string {
  const encoded = file.split("/").map(encodeURIComponent).join("/");
  return `/api/personas/${encodeURIComponent(personaId)}/asset/${encoded}`;
}

/** 共享动作库（male / female）只读地址。 */
export function motionLibraryUrl(variant: string, file: string): string {
  const encoded = file.split("/").map(encodeURIComponent).join("/");
  return `/api/motion-library/${encodeURIComponent(variant)}/${encoded}`;
}

export async function uploadPersonaAvatar(personaId: string, file: File): Promise<{ avatar: string }> {
  const resp = await fetch(`/api/personas/${encodeURIComponent(personaId)}/avatar`, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: file,
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as { avatar: string };
}

export interface Import3dResult {
  persona_id: string;
  vrm: string;
  vrma: string[];
  avatar: string | null;
  /** 非阻断的规格建议（缺缩略图、体积偏大、材质非双面等） */
  warnings?: string[];
}

export async function importPersona3d(personaId: string, file: File): Promise<Import3dResult> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`/api/personas/${encodeURIComponent(personaId)}/import3d`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as Import3dResult;
}

export async function fetchPersonaAssetTasks(limit = 20): Promise<AgentRun[]> {
  const data = await fetchJson<{ items: AgentRun[] }>(`/api/persona-tasks?limit=${limit}`);
  return data.items;
}

export async function deletePersona(id: string): Promise<void> {
  const resp = await fetch(`/api/personas/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(await readDetail(resp));
}

export async function createPersonaAssetTask(
  kind: "voice_clone" | "avatar_import",
  params: Record<string, unknown>,
): Promise<AgentRun> {
  const resp = await fetch("/api/persona-tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, params }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { run: AgentRun };
  return data.run;
}

export async function fetchMemoryOverview(): Promise<DocOverview[]> {
  const data = await fetchJson<{ items: DocOverview[] }>("/api/memories/overview");
  return data.items;
}

export async function fetchMemoryDoc(layer: string, key: string): Promise<MemoryDoc> {
  return fetchJson<MemoryDoc>(`/api/memories/docs/${encodeURIComponent(layer)}/${encodeURIComponent(key)}`);
}

export async function saveMemoryDoc(layer: string, key: string, markdown: string): Promise<MemoryDoc> {
  const resp = await fetch(`/api/memories/docs/${encodeURIComponent(layer)}/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ markdown }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as MemoryDoc;
}

export async function addMemoryEntry(layer: string, key: string, section: string, text: string): Promise<MemoryDoc> {
  const resp = await fetch(`/api/memories/docs/${encodeURIComponent(layer)}/${encodeURIComponent(key)}/entries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ section, text, refs: [] }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { doc: MemoryDoc };
  return data.doc;
}

export async function deleteMemoryEntry(entryId: string): Promise<void> {
  const resp = await fetch(`/api/memories/entries/${encodeURIComponent(entryId)}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(await readDetail(resp));
}

export async function searchMemories(query: string): Promise<SearchHit[]> {
  const data = await fetchJson<{ items: SearchHit[] }>(`/api/memories/search?q=${encodeURIComponent(query)}`);
  return data.items;
}

export async function fetchCompiledMemory(): Promise<CompiledMemory> {
  return fetchJson<CompiledMemory>("/api/memories/compiled");
}

export async function fetchMemoryExport(): Promise<{
  mode: string;
  generated_at: string;
  overview: DocOverview[];
  compiled: CompiledMemory;
  docs: MemoryDoc[];
  sessions: { date: string; markdown: string }[];
}> {
  return fetchJson<{
    mode: string;
    generated_at: string;
    overview: DocOverview[];
    compiled: CompiledMemory;
    docs: MemoryDoc[];
    sessions: { date: string; markdown: string }[];
  }>("/api/memories/export");
}

export interface ObsidianSearchResult {
  available: boolean;
  path: string;
  items: { path: string; title: string; matches: string[] }[];
}

export async function searchObsidian(query: string): Promise<ObsidianSearchResult> {
  return fetchJson<ObsidianSearchResult>(`/api/memories/obsidian/search?q=${encodeURIComponent(query)}`);
}

export interface MemoryVaultStatus {
  available: boolean;
  path: string | null;
  mirror_dir_exists: boolean;
  last_sync: string | null;
  doc_files: number;
}

export async function fetchMemoryVaultStatus(): Promise<MemoryVaultStatus> {
  return fetchJson<MemoryVaultStatus>("/api/memories/vault/status");
}

export interface ObsidianPathCheck {
  available: boolean;
  path: string;
  note_count: number;
}

export async function checkObsidianPath(path: string): Promise<ObsidianPathCheck> {
  return fetchJson<ObsidianPathCheck>(
    `/api/memories/obsidian/check?path=${encodeURIComponent(path)}`,
  );
}

export interface WidgetStatusReport {
  state: string;
  task_id: string | null;
  message: string | null;
  timestamp: string;
}

export interface PublishResponse {
  event: EventEnvelope;
  widget_state: WidgetStatusReport | null;
}

export interface StateResponse {
  widget_state: WidgetStatusReport | null;
}

export async function publishEvent(body: {
  event_type: string;
  source: string;
  task_id?: string | null;
  payload?: Record<string, unknown>;
}): Promise<PublishResponse> {
  const resp = await fetch("/api/events/publish", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`发布事件失败 HTTP ${resp.status}`);
  return (await resp.json()) as PublishResponse;
}

export async function fetchWidgetState(): Promise<WidgetStatusReport | null> {
  const data = await fetchJson<StateResponse>("/api/widget/state");
  return data.widget_state;
}


export interface ChatMessageView {
  role: string;
  content: string;
  created_at: string;
  attachments?: ChatAttachmentView[];
  skill_id?: string | null;
}

export interface ChatAttachmentView {
  name: string;
  path: string;
  size?: number;
  mime?: string;
}

export interface ConversationDetail {
  conversation_id: string;
  title: string;
  model_profile_id: string | null;
  project: string | null;
  project_name: string | null;
  messages: ChatMessageView[];
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  message_count: number;
  updated_at: string;
  project: string | null;
  project_name: string | null;
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const data = await fetchJson<{ items: ConversationSummary[] }>("/api/conversations");
  return data.items;
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  return fetchJson<ConversationDetail>(`/api/conversations/${id}`);
}

export async function uploadChatAttachments(
  files: File[],
): Promise<ChatAttachmentView[]> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const resp = await fetch("/api/chat/attachments", {
    method: "POST",
    body: form,
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { items: ChatAttachmentView[] };
  return data.items;
}

export async function bindConversationProject(
  id: string,
  project: string | null,
  name?: string | null,
): Promise<ConversationDetail> {
  const resp = await fetch(`/api/conversations/${encodeURIComponent(id)}/project`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, name: name ?? null }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as ConversationDetail;
}

export async function fetchAwaitingRuns(conversationId?: string | null): Promise<AgentRun[]> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
  const data = await fetchJson<{ items: AgentRun[] }>(`/api/agent-runs/awaiting${query}`);
  return data.items;
}

export interface TaskRouteResponse {
  task: Task;
}

export type AgentRunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentRun {
  run_id: string;
  task_id: string;
  executor: string;
  status: AgentRunStatus;
  session_id: string | null;
  mode: string;
  progress: string;
  result: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  task_input?: string;
  conversation_id?: string | null;
  project?: string | null;
}

export type AgentRunMode = "read-only" | "agent" | "agent-full-access";

export async function fetchTaskRun(taskId: string): Promise<AgentRun | null> {
  try {
    const data = await fetchJson<{ run: AgentRun }>(`/api/tasks/${encodeURIComponent(taskId)}/run`);
    return data.run;
  } catch {
    return null;
  }
}

export async function fetchRuns(limit = 50): Promise<AgentRun[]> {
  const data = await fetchJson<{ items: AgentRun[] }>(`/api/agent-runs?limit=${limit}`);
  return data.items;
}

export async function executeTask(
  taskId: string,
  body: { executor: string | null; mode: AgentRunMode },
): Promise<{ task: Task; run: AgentRun }> {
  const resp = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as { task: Task; run: AgentRun };
}

export async function cancelRun(runId: string): Promise<AgentRun> {
  const resp = await fetch(`/api/agent-runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { run: AgentRun };
  return data.run;
}

export async function decideRun(runId: string, decision: "approved" | "rejected"): Promise<AgentRun> {
  const resp = await fetch(`/api/agent-runs/${encodeURIComponent(runId)}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { run: AgentRun };
  return data.run;
}

export async function fetchTasks(limit = 50): Promise<Task[]> {
  const data = await fetchJson<{ items: Task[] }>(`/api/tasks?limit=${limit}`);
  return data.items;
}

export async function routeTask(input: string, conversationId?: string | null): Promise<TaskRouteResponse> {
  const resp = await fetch("/api/tasks/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input, conversation_id: conversationId ?? null }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as TaskRouteResponse;
}

export async function markTask(taskId: string, status: "running" | "awaiting_approval" | "completed" | "failed"): Promise<Task> {
  const resp = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/${status === "awaiting_approval" ? "approval" : status}`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  const data = (await resp.json()) as { task: Task };
  return data.task;
}

export async function streamChat(
  conversationId: string | null,
  message: string,
  onDelta: (content: string) => void,
  modelProfileId?: string | null,
  project?: string | null,
  projectName?: string | null,
  attachments?: ChatAttachmentView[],
  mode?: "auto" | "casual" | "work",
  onToolApproval?: (approval: ToolApprovalView) => void,
): Promise<{
  conversation_id: string;
  short: boolean;
  message: string;
  speak_text: string;
  interaction_kind: InteractionKind;
  skill_id: string | null;
}> {
  const resp = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      modality: "text",
      mode: mode ?? "auto",
      model_profile_id: modelProfileId ?? null,
      project: project ?? null,
      project_name: projectName ?? null,
      attachments: attachments ?? [],
    }),
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`对话接口 HTTP ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const readEvent = (chunk: string): void => {
    buffer += chunk;
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = raw.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      let obj: {
        type: string;
        content?: string;
        message?: string;
        conversation_id?: string;
        short?: boolean;
        speak_text?: string;
        interaction_kind?: InteractionKind;
        skill_id?: string | null;
        approval_id?: string;
        server?: string;
        tool?: string;
        arguments?: string;
      };
      try {
        obj = JSON.parse(dataLine.slice(6));
      } catch {
        continue;
      }
      if (obj.type === "delta" && obj.content) onDelta(obj.content);
      else if (obj.type === "error") throw new Error(obj.message ?? "模型调用失败");
      else if (obj.type === "tool_approval" && obj.approval_id) {
        onToolApproval?.({
          approval_id: obj.approval_id,
          server: obj.server ?? "",
          tool: obj.tool ?? "",
          arguments: obj.arguments ?? "",
        });
      }
      else if (obj.type === "done") {
        result = {
          conversation_id: obj.conversation_id ?? "",
          short: obj.short ?? true,
          message: obj.message ?? "",
          speak_text: obj.speak_text ?? obj.message ?? "",
          interaction_kind: obj.interaction_kind ?? "casual",
          skill_id: obj.skill_id ?? null,
        };
      }
    }
  };

  let result: {
    conversation_id: string;
    short: boolean;
    message: string;
    speak_text: string;
    interaction_kind: InteractionKind;
    skill_id: string | null;
  } | null = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    readEvent(decoder.decode(value, { stream: true }));
  }
  readEvent(decoder.decode());
  if (!result) throw new Error("对话未返回结果");
  return result;
}

export function connectEvents(
  wsUrl: string,
  onEvent: (env: EventEnvelope) => void,
  onState: (open: boolean) => void,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const open = () => {
    if (closed) return;
    ws = new WebSocket(wsUrl);
    ws.onopen = () => onState(true);
    ws.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data as string) as EventEnvelope);
      } catch {
        /* 忽略无法解析的消息 */
      }
    };
    ws.onclose = () => {
      onState(false);
      if (!closed) retryTimer = setTimeout(open, 3000);
    };
    ws.onerror = () => ws?.close();
  };
  open();

  return () => {
    closed = true;
    if (retryTimer) clearTimeout(retryTimer);
    ws?.close();
  };
}


// ── 语音（Step 4，与 /api/voice/* 对应）─────────────────────
export interface VoiceActivationStatus {
  enabled: boolean;
  default_state: "listening" | "sleeping";
  persona_name: string;
}

export interface VoiceEndpointStatus {
  enabled: boolean;
  auto_speak: boolean;
  language: string;
  interruption_enabled: boolean;
  activation: VoiceActivationStatus;
  stt: { provider: string; model: string; available: boolean };
  tts: {
    provider: string;
    model: string;
    voice: string;
    format: string;
    sample_rate: number;
    available: boolean;
  };
  params: Record<string, unknown> | null;
}

export async function fetchVoiceStatus(): Promise<VoiceEndpointStatus> {
  return fetchJson<VoiceEndpointStatus>("/api/voice/status");
}

export interface VoiceOption {
  id: string;
  name: string;
  kind: "system" | "cloned" | "preset";
}

export interface VoiceOptionList {
  provider: string;
  model: string;
  current: string;
  available: boolean;
  voices: VoiceOption[];
  reason: string | null;
}

/** 拉取语音合成供应商的可用音色，供设置页与角色卡绑定。

    传 profileId 时按该模型档案取（设置页编辑态）；不传按当前生效配置取（角色卡）。 */
export async function fetchVoiceOptions(profileId?: string): Promise<VoiceOptionList> {
  const query = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
  return fetchJson<VoiceOptionList>(`/api/voice/voices${query}`);
}

export interface VoicePreviewRequest {
  profile_id?: string;
  provider?: string;
  base_url?: string;
  model?: string;
  voice?: string;
  api_key?: string;
  text?: string;
}

/** 试听：用指定音色合成一句样音。会消耗供应商额度，只在用户点击时调用。 */
export async function previewVoice(payload: VoicePreviewRequest): Promise<Blob> {
  const resp = await fetch("/api/voice/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    throw new Error(await readDetail(resp));
  }
  return await resp.blob();
}

export async function acquireVoiceLease(force = false): Promise<boolean> {
  const resp = await fetch(`/api/voice/lease${force ? "?force=true" : ""}`, {
    method: "POST",
    headers: { "X-Voice-Client": "web" },
  });
  if (!resp.ok) return false;
  return ((await resp.json()) as { acquired: boolean }).acquired;
}

export async function heartbeatVoiceLease(): Promise<boolean> {
  const resp = await fetch("/api/voice/lease/heartbeat", {
    method: "POST",
    headers: { "X-Voice-Client": "web" },
  });
  return resp.ok;
}

export async function releaseVoiceLease(): Promise<void> {
  await fetch("/api/voice/lease", {
    method: "DELETE",
    headers: { "X-Voice-Client": "web" },
    keepalive: true,
  }).catch(() => {});
}

export interface VoiceIntentResponse {
  intent: "chat" | "wake" | "sleep";
  persona_name: string;
  reply: string | null;
  wake_texts: string[];
}

export async function apiVoiceIntent(text: string, client: "web" | "widget" = "web"): Promise<VoiceIntentResponse> {
  const resp = await fetch("/api/voice/intent", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Voice-Client": client },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) {
    throw new Error(await readDetail(resp));
  }
  return (await resp.json()) as VoiceIntentResponse;
}

async function readDetail(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { detail?: string };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* 非 JSON 错误体 */
  }
  return `HTTP ${resp.status}`;
}

export async function recognizeSpeech(audio: Blob, client: "web" | "widget" = "web"): Promise<{
  text: string;
  provider: string;
  available: boolean;
}> {
  const resp = await fetch("/api/voice/recognize?language=zh", {
    method: "POST",
    headers: { "Content-Type": "audio/wav", "X-Voice-Client": client },
    body: audio,
  });
  if (!resp.ok) {
    throw new Error(await readDetail(resp));
  }
  return (await resp.json()) as { text: string; provider: string; available: boolean };
}

export async function synthesizeSpeech(text: string, client: "web" | "widget" = "web"): Promise<Blob> {
  const resp = await fetch("/api/voice/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Voice-Client": client },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) {
    throw new Error(await readDetail(resp));
  }
  return await resp.blob();
}

export interface AudioChunk {
  index: number;
  format: string;
  sample_rate: number;
  audio: Blob;
}

/** 流式合成：返回 AsyncGenerator，逐句产出 AudioChunk。前端边收边播。 */
export async function synthesizeSpeechStream(
  text: string,
  client: "web" | "widget" = "web",
  signal?: AbortSignal,
): Promise<AsyncGenerator<AudioChunk>> {
  const resp = await fetch("/api/voice/synthesize/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Voice-Client": client },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!resp.ok) {
    throw new Error(await readDetail(resp));
  }
  return _parseAudioSSE(resp.body!);
}

/** SSE 行格式：data: {"index":0,"format":"wav","sample_rate":24000,"audio":"<base64>"} */
async function* _parseAudioSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<AudioChunk> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6);
      if (!payload) continue;
      try {
        const obj = JSON.parse(payload);
        if (obj.error) throw new Error(obj.error);
        if (obj.done) return;
        if (obj.audio) {
          const bytes = Uint8Array.from(atob(obj.audio), (c) => c.charCodeAt(0));
          yield {
            index: obj.index,
            format: obj.format || "wav",
            sample_rate: obj.sample_rate || 24000,
            audio: new Blob([bytes], { type: "audio/" + (obj.format || "wav") }),
          };
        }
      } catch (e) {
        if (!(e instanceof SyntaxError)) throw e;
      }
    }
  }
}
