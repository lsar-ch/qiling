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

export interface HealthResponse {
  status: string;
  version: string;
}

export async function pollHealth(url: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    const resp = await fetch(`${url}api/health`, { signal: controller.signal });
    clearTimeout(timer);
    return resp.ok;
  } catch {
    return false;
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
  };
  return map[eventType] ?? null;
}

export interface WsMessage {
  event_type: string;
  task_id?: string | null;
  timestamp?: string;
  payload?: Record<string, unknown>;
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

export async function apiVoiceIntent(text: string): Promise<VoiceIntentResponse> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/intent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as VoiceIntentResponse;
}

export async function recognizeSpeech(audio: Blob): Promise<{
  text: string;
  provider: string;
  available: boolean;
}> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/recognize?language=zh`, {
    method: "POST",
    headers: { "Content-Type": "audio/wav" },
    body: audio,
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return (await resp.json()) as { text: string; provider: string; available: boolean };
}

export async function synthesizeSpeech(text: string): Promise<Blob> {
  const resp = await fetch(`${SERVICE_BASE}/api/voice/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error(await readDetail(resp));
  return await resp.blob();
}

export async function streamChat(
  conversationId: string | null,
  message: string,
  onDelta: (content: string) => void,
): Promise<ChatStreamDone> {
  const resp = await fetch(`${SERVICE_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      modality: "text",
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
