// 主界面与 ai-service 通信（同源 /api；开发模式由 Vite 代理转发）。
import type { AgentInfo, AgentIntegrationStatus } from "@deskmate/contracts";
import type { EventEnvelope } from "@deskmate/contracts";
import type { CompiledMemory, DocOverview, MemoryDoc, SearchHit } from "@deskmate/contracts";
import type { Task, TaskCategory, TaskStatus } from "@deskmate/contracts";

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

export async function fetchSession(): Promise<SessionResponse> {
  return fetchJson<SessionResponse>("/api/session");
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
  };
  activation: {
    persona_name?: string;
    wake_prefixes?: string[];
    sleep_phrases?: string[];
  };
}

export interface AppSettings {
  active_persona_id: string;
  ui: { language: string; theme: string };
  permission_level: string;
  memory: {
    mode: string;
    budget_chars: number;
    obsidian_vault_path: string;
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
}

export interface ConversationDetail {
  conversation_id: string;
  title: string;
  messages: ChatMessageView[];
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  message_count: number;
  updated_at: string;
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const data = await fetchJson<{ items: ConversationSummary[] }>("/api/conversations");
  return data.items;
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  return fetchJson<ConversationDetail>(`/api/conversations/${id}`);
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
): Promise<{
  conversation_id: string;
  short: boolean;
  message: string;
  speak_text: string;
}> {
  const resp = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      modality: "text",
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
      };
      try {
        obj = JSON.parse(dataLine.slice(6));
      } catch {
        continue;
      }
      if (obj.type === "delta" && obj.content) onDelta(obj.content);
      else if (obj.type === "error") throw new Error(obj.message ?? "模型调用失败");
      else if (obj.type === "done") {
        result = {
          conversation_id: obj.conversation_id ?? "",
          short: obj.short ?? true,
          message: obj.message ?? "",
          speak_text: obj.speak_text ?? obj.message ?? "",
        };
      }
    }
  };

  let result: {
    conversation_id: string;
    short: boolean;
    message: string;
    speak_text: string;
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

export interface VoiceIntentResponse {
  intent: "chat" | "wake" | "sleep";
  persona_name: string;
  reply: string | null;
  wake_texts: string[];
}

export async function apiVoiceIntent(text: string): Promise<VoiceIntentResponse> {
  const resp = await fetch("/api/voice/intent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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

export async function recognizeSpeech(audio: Blob): Promise<{
  text: string;
  provider: string;
  available: boolean;
}> {
  const resp = await fetch("/api/voice/recognize?language=zh", {
    method: "POST",
    headers: { "Content-Type": "audio/wav" },
    body: audio,
  });
  if (!resp.ok) {
    throw new Error(await readDetail(resp));
  }
  return (await resp.json()) as { text: string; provider: string; available: boolean };
}

export async function synthesizeSpeech(text: string): Promise<Blob> {
  const resp = await fetch("/api/voice/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) {
    throw new Error(await readDetail(resp));
  }
  return await resp.blob();
}
