// 桌面前端：事件连接 + 服务健康探测
export type WidgetState =
  | "idle" | "listening" | "thinking" | "speaking"
  | "executing" | "awaiting_approval" | "completed" | "interrupted";

export interface WidgetStatusReport {
  state: string;
  task_id: string | null;
  message: string | null;
  timestamp: string;
}


// ── Step 9.5: 统一表现事件流 ─────────────────────────────────────────────

export type ExpressionEmotion =
  | "neutral" | "attentive" | "thinking"
  | "confused" | "success" | "error";

export interface ExpressionBubble {
  text: string;
  duration_ms: number;
  style: "info" | "success" | "warning" | "error";
}

export interface ExpressionEvent {
  state: WidgetState;
  task_id: string | null;
  timestamp: string;
  emotion: ExpressionEmotion;
  bubble?: ExpressionBubble | null;
}

export interface PersonaPresentation {
  persona_id: string;
  persona_name: string;
  style: "human" | "animal";
  theme: {
    primary: string;
    aura: string;
    accent: string;
  };
  animations: {
    breath_rate: number;
    blink_interval_ms: number;
    idle_action_interval_ms: number;
    transition_ms: number;
  };
  fx: {
    thinking_bubble: boolean;
    music_note: boolean;
    success_sparkle: boolean;
  };
  asset?: {
    avatar_url?: string;
    width?: number;
    height?: number;
  } | null;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export async function pollHealth(url: string): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const resp = await fetch(`${url}api/health`, { signal: controller.signal });
    return resp.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export interface PersonaAssetMetrics {
  personaId: string;
  /** 归一化画布尺寸（contentBbox 以此为坐标系） */
  canvasWidth: number;
  canvasHeight: number;
  /** [x0, y0, x1, y1]，画布像素；拿不到时为 null */
  contentBbox: [number, number, number, number] | null;
}

export async function fetchActivePersonaAsset(): Promise<{
  avatar: string;
  style: "human" | "animal";
} & PersonaAssetMetrics> {
  const settingsResp = await fetch(`${SERVICE_BASE}/api/settings`);
  if (!settingsResp.ok) throw new Error(await readDetail(settingsResp));
  const settings = await settingsResp.json() as { active_persona_id: string };
  const personasResp = await fetch(`${SERVICE_BASE}/api/personas`);
  if (!personasResp.ok) throw new Error(await readDetail(personasResp));
  const personas = await personasResp.json() as {
    items: Array<{ id: string; avatar?: string; kind?: string }>;
  };
  const persona = personas.items.find((item) => item.id === settings.active_persona_id);
  const animalKinds = new Set(["cat", "dog", "bird", "rabbit", "animal"]);
  return {
    avatar: persona?.avatar ?? "",
    style: animalKinds.has(persona?.kind?.toLowerCase() ?? "") ? "animal" : "human",
    ...(await fetchPersonaAssetMetrics(settings.active_persona_id)),
  };
}

/**
 * 读取角色素材清单里的内容包围盒。挂件靠它推算贴边隐藏的保留量，
 * 免得把某一版立绘的透明边距写死成常量；任何一步失败都退回 null，
 * 由 Rust 侧的默认值兜底。
 */
export async function fetchPersonaAssetMetrics(personaId: string): Promise<PersonaAssetMetrics> {
  const fallback: PersonaAssetMetrics = {
    personaId,
    canvasWidth: 0,
    canvasHeight: 0,
    contentBbox: null,
  };
  if (!personaId) return fallback;
  try {
    const resp = await fetch(
      `${SERVICE_BASE}/api/personas/${encodeURIComponent(personaId)}/asset-manifest`,
    );
    if (!resp.ok) return fallback;
    const manifest = await resp.json() as { width?: number; height?: number; content_bbox?: unknown };
    const raw = manifest.content_bbox;
    const bbox =
      Array.isArray(raw) &&
      raw.length === 4 &&
      raw.every((value) => typeof value === "number" && Number.isFinite(value))
        ? ([raw[0], raw[1], raw[2], raw[3]] as [number, number, number, number])
        : null;
    return {
      personaId,
      canvasWidth: typeof manifest.width === "number" ? manifest.width : 0,
      canvasHeight: typeof manifest.height === "number" ? manifest.height : 0,
      contentBbox: bbox,
    };
  } catch {
    return fallback;
  }
}

export function eventToState(eventType: string): WidgetState | null {
  const map: Record<string, WidgetState> = {
    "speech.started": "listening",
    "conversation.input": "thinking",
    "conversation.transcript": "thinking",
    "conversation.response": "speaking",
    "conversation.completed": "completed",
    "task.started": "executing",
    "task.progress": "executing",
    "task.approval_required": "awaiting_approval",
    "speech.interrupted": "interrupted",
    "task.completed": "completed",
    "task.failed": "completed",
    "task.cancelled": "completed",
    "task.approval_reminder": "awaiting_approval",
    "task.timed_out": "completed",
  };
  return map[eventType] ?? null;
}

export interface WsMessage {
  event_type: string;
  task_id?: string | null;
  timestamp?: string;
  payload?: Record<string, unknown>;
  expression?: ExpressionEvent | null;
  presentation?: PersonaPresentation | null;
}

export const SERVICE_BASE = "http://127.0.0.1:8736";

async function readDetail(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* 非 JSON 错误体 */
  }
  return `HTTP ${resp.status}`;
}

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
  activation: VoiceActivationStatus | null;
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

export interface VoiceIntentResponse {
  intent: "chat" | "wake" | "sleep";
  persona_name: string;
  reply: string | null;
  wake_texts: string[];
}

export interface ChatStreamDone {
  conversation_id: string;
  short: boolean;
  message: string;
  speak_text: string;
}

export async function fetchVoiceStatus(): Promise<VoiceEndpointStatus> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/status`);
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as VoiceEndpointStatus;
}

export async function acquireVoiceLease(): Promise<boolean> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/lease`, {
    method: "POST",
    headers: { "X-Voice-Client": "widget" },
  });
  if (!resp.ok) return false;
  return ((await resp.json()) as { acquired: boolean }).acquired;
}

export async function heartbeatVoiceLease(): Promise<boolean> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/lease/heartbeat`, {
    method: "POST",
    headers: { "X-Voice-Client": "widget" },
  });
  return resp.ok;
}

export async function releaseVoiceLease(): Promise<void> {
  await fetch(`${SERVICE_BASE}/api/voice/lease`, {
    method: "DELETE",
    headers: { "X-Voice-Client": "widget" },
    keepalive: true,
  }).catch(() => {});
}

export async function apiVoiceIntent(text: string, client: "web" | "widget" = "widget"): Promise<VoiceIntentResponse> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/intent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Voice-Client": client },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as VoiceIntentResponse;
}

export async function recognizeSpeech(audio: Blob, client: "web" | "widget" = "widget"): Promise<{
  text: string;
  provider: string;
  available: boolean;
}> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/recognize?language=zh`, {
    method: "POST",
    headers: { "Content-Type": "audio/wav", "X-Voice-Client": client },
    body: audio,
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as { text: string; provider: string; available: boolean };
}

export async function synthesizeSpeech(text: string, client: "web" | "widget" = "widget"): Promise<Blob> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Voice-Client": client },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return await resp.blob();
}

export interface AudioChunk {
  index: number;
  format: string;
  sample_rate: number;
  audio: Blob;
}

/** 流式合成：返回 AsyncGenerator，逐句产出 AudioChunk。挂件边收边播，不再等整段。 */
export async function synthesizeSpeechStream(
  text: string,
  client: "web" | "widget" = "widget",
  signal?: AbortSignal,
): Promise<AsyncGenerator<AudioChunk>> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/synthesize/stream`, {
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

export async function streamChat(
  conversationId: string | null,
  message: string,
  onDelta: (content: string) => void,
  mode: "auto" | "casual" | "work" = "auto",
): Promise<ChatStreamDone> {
  const resp = await fetch(`${SERVICE_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      modality: "text",
      mode,
    }),
  });
  if (!resp.ok || !resp.body) throw new Error(await readDetail(resp));

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ChatStreamDone | null = null;
  let streamError = "";

  const consumeChunk = (chunk: string): void => {
    buffer += chunk;
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = raw.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      let obj: {
        type?: string;
        content?: string;
        message?: string;
        conversation_id?: string;
        short?: boolean;
        speak_text?: string;
      };
      try {
        obj = JSON.parse(dataLine.slice(6)) as typeof obj;
      } catch {
        continue;
      }
      if (obj.type === "delta" && typeof obj.content === "string") {
        onDelta(obj.content);
      } else if (obj.type === "error" && typeof obj.message === "string") {
        streamError = obj.message;
      } else if (obj.type === "done") {
        result = {
          conversation_id: obj.conversation_id ?? "",
          short: obj.short ?? true,
          message: obj.message ?? "",
          speak_text: obj.speak_text ?? obj.message ?? "",
        };
      }
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    consumeChunk(decoder.decode(value, { stream: true }));
  }
  consumeChunk(decoder.decode());
  if (!result) throw new Error(streamError || "对话未返回结果");
  if (streamError) throw new Error(streamError);
  return result;
}

export function connectEvents(
  wsUrl: string,
  onMessage: (msg: WsMessage) => void,
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
        onMessage(JSON.parse(msg.data as string) as WsMessage);
      } catch {
        /* ignore */
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
