import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { currentMonitor, getCurrentWindow } from "@tauri-apps/api/window";
import {
  apiVoiceIntent,
  connectEvents,
  eventToState,
  fetchActivePersonaAsset,
  fetchVoiceStatus,
  acquireVoiceLease,
  heartbeatVoiceLease,
  releaseVoiceLease,
  recognizeSpeech,
  SERVICE_BASE,
  streamChat,
  synthesizeSpeech,
  type ExpressionEmotion,
  type ExpressionEvent,
  type PersonaPresentation,
  type VoiceEndpointStatus,
  type WsMessage,
  type WidgetState,
} from "../api";
import {
  startAlwaysListener,
  type AlwaysListener,
  type AlwaysListenSegment,
} from "../voiceCapture";
import defaultMascotArt from "../assets/personas/default/main.png";
import "./widget.css";

const STATE_LABEL: Record<string, string> = {
  idle: "空闲",
  listening: "聆听中",
  thinking: "思考中",
  speaking: "说话中",
  executing: "执行中",
  awaiting_approval: "需要授权",
  completed: "完成",
  interrupted: "已打断",
};

type VoiceMode = "off" | "starting" | "listening" | "sleeping";

// 一次性情绪动画的停留时长：动画播完由前端回落 neutral。
// 后端只在事件到达时下发情绪、不自动复位，长驻情绪会让弹跳/抖动停不下来。
const EMOTION_HOLD_MS: Partial<Record<ExpressionEmotion, number>> = {
  attentive: 1100,
  success: 1900,
  error: 1400,
};

type WidgetPreferences = {
  x: number | null;
  y: number | null;
  monitor: string | null;
  autoHide: boolean;
  scale: number;
};

type DragStart = {
  pointerId: number;
  x: number;
  y: number;
};

function normText(text: string): string {
  return text.replace(/[\s，。！？、,.!?'"“”]/g, "").toLowerCase();
}

// 气泡显示时长随文字长度变化：短提示至少约 6s，长文本最多 20s
const bubbleDuration = (text: string): number => {
  const len = text.trim().length;
  return Math.min(20000, Math.max(6000, 3500 + len * 120));
};

// 挂件窗口基础尺寸（空态、无气泡时与 tauri.conf 中 widget 窗口一致）
const BASE_WINDOW_H = 480;
const MASCOT_BASE_SIZE = 338;
const WIDGET_DRAG_THRESHOLD_PX = 7;
const WIDGET_CLICK_SUPPRESS_MS = 120;
const WIDGET_SCALE_MIN = 0.75;
const WIDGET_SCALE_MAX = 1.15;
const CONTEXT_MENU_WIDTH = 188;
const CONTEXT_MENU_HEIGHT = 170;

function applyPresentation(pres: PersonaPresentation): void {
  const root = document.querySelector<HTMLDivElement>(".w-root");
  if (!root) return;
  root.style.setProperty("--dm-primary", pres.theme.primary);
  root.style.setProperty("--dm-accent", pres.theme.accent);
  root.style.setProperty("--dm-breath-rate", String(pres.animations.breath_rate));
  root.style.setProperty("--dm-blink-ms", `${pres.animations.blink_interval_ms}ms`);
  root.style.setProperty("--dm-transition-ms", `${pres.animations.transition_ms}ms`);
}

function resolveMascotUrl(url: string | undefined): string {
  if (!url) return defaultMascotArt;
  if (url.startsWith("/")) return `${SERVICE_BASE}${url}`;
  return url;
}

export default function Widget() {
  const [state, setState] = useState<WidgetState>("idle");
  const [emotion, setEmotion] = useState<ExpressionEmotion>("neutral");
  const [presentation, setPresentation] = useState<PersonaPresentation | null>(null);
  const [mascotArt, setMascotArt] = useState(defaultMascotArt);
  const [bubble, setBubble] = useState("");
  const [connected, setConnected] = useState(false);
  const [active, setActive] = useState(false);
  const [inputOpen, setInputOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceEndpointStatus | null>(null);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("off");
  const [personaName, setPersonaName] = useState("DeskMate");
  const [speaking, setSpeaking] = useState(false);
  const [voiceLeaseOwned, setVoiceLeaseOwned] = useState(false);
  const [alert, setAlert] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);
  const [preferences, setPreferences] = useState<WidgetPreferences>({
    x: null,
    y: null,
    monitor: null,
    autoHide: true,
    scale: 1,
  });

  const inputRef = useRef<HTMLInputElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const bubbleRef = useRef<HTMLDivElement | null>(null);
  const bubbleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emotionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resizeRafRef = useRef<number | null>(null);
  const persistentHintRef = useRef("");
  const conversationIdRef = useRef<string | null>(null);
  const busyRef = useRef(false);
  const alwaysRef = useRef<AlwaysListener | null>(null);
  const segmentHandlerRef = useRef<(segment: AlwaysListenSegment) => void>(() => {});
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playbackRef = useRef<AudioBufferSourceNode | null>(null);
  const speakingRef = useRef(false);
  const speakStartAtRef = useRef(0);
  const speakEndAtRef = useRef(0);
  const lastSpokenRef = useRef("");
  const lastSpokenAtRef = useRef(0);
  const voiceModeRef = useRef<VoiceMode>("off");
  const voiceStatusRef = useRef<VoiceEndpointStatus | null>(null);
  const personaNameRef = useRef("DeskMate");
  const activeRef = useRef(false);
  const inputOpenRef = useRef(false);
  const autoVoiceRef = useRef(false);
  const widgetTurnRef = useRef(false);
  const dragStartRef = useRef<DragStart | null>(null);
  const draggingRef = useRef(false);
  const suppressClickUntilRef = useRef(0);
  const dragFallbackTimerRef = useRef<number | null>(null);

  busyRef.current = busy;
  voiceModeRef.current = voiceMode;
  voiceStatusRef.current = voiceStatus;
  personaNameRef.current = personaName;
  activeRef.current = active;
  inputOpenRef.current = inputOpen;

  const resizeToBubble = async (): Promise<void> => {
    const el = bubbleRef.current;
    if (!el) return;
    try {
      const showing = el.getAttribute("data-visible") === "1" && (el.textContent ?? "").trim().length > 0;
      const rect = el.getBoundingClientRect();
      // 挂件宽度固定：气泡不超出挂件自身，仅在有气泡时按内容高度向上生长
      const wantH = showing
        ? Math.max(BASE_WINDOW_H, Math.ceil(rect.height) + BASE_WINDOW_H - 48)
        : BASE_WINDOW_H;
      await invoke("resize_widget_height", { height: wantH });
    } catch {
      /* 非 Tauri 环境或窗口调整失败时保持现状 */
    }
  };

  useLayoutEffect(() => {
    if (resizeRafRef.current) cancelAnimationFrame(resizeRafRef.current);
    resizeRafRef.current = requestAnimationFrame(() => {
      void resizeToBubble();
    });
    return () => {
      if (resizeRafRef.current) cancelAnimationFrame(resizeRafRef.current);
    };
  }, [bubble, inputOpen]);

  const showBrief = (text: string, ms = bubbleDuration(text)): void => {
    if (bubbleTimerRef.current) clearTimeout(bubbleTimerRef.current);
    setBubble(text);
    const clearBubble = (): void => {
      // 语音播报期间保持文字气泡可见，播完后再停留一小会儿隐藏
      if (speakingRef.current) {
        bubbleTimerRef.current = setTimeout(clearBubble, 1200);
        return;
      }
      setBubble(persistentHintRef.current || "");
    };
    bubbleTimerRef.current = setTimeout(clearBubble, ms);
  };

  const setPersistentHint = (text: string): void => {
    if (bubbleTimerRef.current) clearTimeout(bubbleTimerRef.current);
    persistentHintRef.current = text;
    setBubble(text);
  };

  /** 设置情绪；一次性情绪播完自动回落 neutral。 */
  const applyEmotion = (next: ExpressionEmotion): void => {
    if (emotionTimerRef.current) {
      window.clearTimeout(emotionTimerRef.current);
      emotionTimerRef.current = null;
    }
    setEmotion(next);
    const hold = EMOTION_HOLD_MS[next];
    if (hold) {
      emotionTimerRef.current = window.setTimeout(() => {
        emotionTimerRef.current = null;
        setEmotion("neutral");
      }, hold);
    }
  };

  const closeComposer = (deactivate = true): void => {
    setInput("");
    setInputOpen(false);
    inputOpenRef.current = false;
    if (deactivate) {
      setActive(false);
      activeRef.current = false;
    }
  };

  const openMainUi = async (): Promise<void> => {
    try {
      await invoke("open_main_ui");
    } catch {
      /* 桌面调用失败时静默，保留当前挂件 */
    }
  };

  const ensureAudioContext = async (): Promise<AudioContext | null> => {
    const AC =
      window.AudioContext ??
      (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new AC();
    }
    if (audioCtxRef.current.state === "suspended") {
      try {
        await audioCtxRef.current.resume();
      } catch {
        /* 未授权前由点击事件恢复 */
      }
    }
    return audioCtxRef.current;
  };

  const stopSpeaking = (): void => {
    playbackRef.current?.stop();
    playbackRef.current = null;
    speakingRef.current = false;
    speakEndAtRef.current = Date.now();
    setSpeaking(false);
  };

  /** 通知服务端「用户打断」：挂件徽标与主界面状态同步回落（V1 按钮打断）。 */
  const notifySpeechInterrupted = async (): Promise<void> => {
    try {
      await fetch(`${SERVICE_BASE}/api/events/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_type: "speech.interrupted",
          source: "speech",
          payload: {},
        }),
      });
    } catch {
      /* 服务不可用时只做本地停止 */
    }
  };

  const speak = async (text: string): Promise<void> => {
    const voice = voiceStatusRef.current;
    if (!voiceLeaseOwned || !voice?.enabled || !voice.tts.available || speakingRef.current) return;
    const ctx = await ensureAudioContext();
    if (!ctx) return;

    lastSpokenRef.current = text;
    lastSpokenAtRef.current = Date.now();
    speakingRef.current = true;
    speakStartAtRef.current = Date.now();
    speakEndAtRef.current = 0;
    setSpeaking(true);

    let source: AudioBufferSourceNode | null = null;
    try {
      const blob = await synthesizeSpeech(text.length > 1900 ? `${text.slice(0, 1900)}…` : text, "widget");
      const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
      source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      playbackRef.current = source;
      source.onended = () => {
        if (playbackRef.current === source) playbackRef.current = null;
        speakingRef.current = false;
        speakEndAtRef.current = Date.now();
        setSpeaking(false);
      };
      source.start();
    } catch {
      if (playbackRef.current === source) playbackRef.current = null;
      speakingRef.current = false;
      speakEndAtRef.current = Date.now();
      setSpeaking(false);
    }
  };

  const submitText = async (text: string, speakReply: boolean): Promise<void> => {
    const clean = text.trim();
    if (!clean || busyRef.current) return;
    setBusy(true);
    setInput("");
    setInputOpen(false);
    inputOpenRef.current = false;
    setBubble("正在思考…");
    widgetTurnRef.current = true;

    try {
      const done = await streamChat(conversationIdRef.current, clean, () => {
        /* 挂件只展示短回复，不渲染流式全文 */
      });
      conversationIdRef.current = done.conversation_id;
      if (!done.short) {
        void openMainUi();
      } else {
        showBrief(done.message || done.speak_text);
        if (speakReply && voiceStatusRef.current?.enabled && voiceStatusRef.current.auto_speak && voiceModeRef.current !== "off") {
          stopSpeaking();
          void speak(done.speak_text || done.message);
        }
      }
    } catch (e) {
      showBrief(e instanceof Error ? `回复失败：${e.message}` : "回复失败");
    } finally {
      widgetTurnRef.current = false;
      setBusy(false);
    }
  };

  const handleSend = (): void => {
    const text = input.trim();
    if (!text || busy) return;
    void submitText(text, true);
  };

  const stopVoiceResources = (): void => {
    const listener = alwaysRef.current;
    alwaysRef.current = null;
    if (listener) listener.stop();
    playbackRef.current?.stop();
    playbackRef.current = null;
  };

  const disableAlwaysListen = (): void => {
    stopVoiceResources();
    speakingRef.current = false;
    setSpeaking(false);
    setVoiceMode("off");
  };

  const enableAlwaysListen = async (mode: VoiceMode): Promise<void> => {
    if (alwaysRef.current) return;
    if (!voiceLeaseOwned) return;
    const voice = voiceStatusRef.current;
    if (!voice?.enabled) {
      setVoiceMode("off");
      showBrief("语音未配置，可使用文字输入", 2800);
      return;
    }
    setVoiceMode("starting");
    const ctx = await ensureAudioContext();
    if (!ctx) {
      setVoiceMode("off");
      showBrief("音频不可用", 2800);
      return;
    }
    const listener = await startAlwaysListener({
      onSegment: (segment) => void segmentHandlerRef.current(segment),
      onError: (message) => {
        alwaysRef.current = null;
        setVoiceMode("off");
        showBrief(message, 3600);
      },
    }, ctx);
    if (!listener) {
      setVoiceMode("off");
      return;
    }
    alwaysRef.current = listener;
    setVoiceMode(mode);
  };

  const toggleVoiceState = (): void => {
    const mode = voiceModeRef.current;
    if (mode === "off" || mode === "starting") {
      void enableAlwaysListen("listening");
    } else if (mode === "listening") {
      stopSpeaking();
      setVoiceMode("sleeping");
      setPersistentHint("");
    } else {
      const existing = alwaysRef.current;
      if (existing) existing.resume();
      setVoiceMode("listening");
      setPersistentHint("");
    }
  };

  const handleVoiceSegment = async (segment: AlwaysListenSegment): Promise<void> => {
    if (busyRef.current) return;
    if (speakingRef.current) return;
    if (
      speakStartAtRef.current > 0 &&
      segment.startedAt >= speakStartAtRef.current - 150 &&
      segment.startedAt <= (speakEndAtRef.current || Date.now()) + 900
    ) {
      return;
    }

    let text = "";
    try {
      const r = await recognizeSpeech(segment.wav, "widget");
      text = (r.text || "").trim();
    } catch {
      // 监听/静默态由状态动画提示即可；背景噪音产生的无效音频不弹气泡。
      return;
    }
    if (!text) return;

    const spoken = lastSpokenRef.current;
    if (spoken && Date.now() - lastSpokenAtRef.current < 5000) {
      const a = normText(text);
      const b = normText(spoken);
      if (a && b && (a.includes(b) || b.includes(a))) return;
    }

    let intent = "chat";
    let reply: string | null = null;
    try {
      const resp = await apiVoiceIntent(text);
      intent = resp.intent;
      reply = resp.reply;
      if (resp.persona_name) personaNameRef.current = resp.persona_name;
    } catch {
      /* 意图接口失败按普通对话处理 */
    }

    const mode = voiceModeRef.current;
    if (intent === "sleep") {
      stopSpeaking();
      setVoiceMode("sleeping");
      void speak(reply ?? "好，我先安静一会儿。");
      return;
    }
    if (intent === "wake" && mode === "sleeping") {
      stopSpeaking();
      setVoiceMode("listening");
      void speak(reply ?? `在呢～我是${personaNameRef.current}，有什么想让我帮忙的？`);
      return;
    }
    if (mode === "sleeping") return;

    void submitText(text, true);
  };

  useEffect(() => {
    let alive = true;
    void fetchActivePersonaAsset()
      .then((asset) => {
        if (!alive) return;
        setMascotArt(resolveMascotUrl(asset.avatar));
        setPresentation((current) => current ? { ...current, style: asset.style } : current);
      })
      .catch(() => {
        /* WebSocket 的 persona.presentation 仍会提供角色资产 */
      });
    const wsUrl = "ws://127.0.0.1:8736/api/events";

    const onMsg = (msg: WsMessage) => {
      if (!alive) return;
      if (msg.event_type === "system.health") {
        const wsState = msg.payload?.widget_state as
          | { state?: string; message?: string | null }
          | undefined;
        if (wsState?.state && (wsState.state as WidgetState)) {
          setState(wsState.state as WidgetState);
        }
        if (wsState?.message) showBrief(String(wsState.message), 3000);
        setConnected(true);
        return;
      }

      const next = eventToState(msg.event_type);
      if (!next) {
        // persona.presentation 事件：更新角色呈现
        if (msg.event_type === "persona.presentation" && msg.presentation) {
          setPresentation(msg.presentation);
          applyPresentation(msg.presentation);
          setMascotArt(resolveMascotUrl(msg.presentation.asset?.avatar_url));
        }
        return;
      }
      setState(next);

      // Step 9.5: 从 expression 载荷提取情绪和气泡
      const expr = msg.expression as ExpressionEvent | undefined;
      if (expr) {
        applyEmotion(expr.emotion);
        if (expr.bubble) {
          showBrief(expr.bubble.text, expr.bubble.duration_ms);
        }
      }

      // 任务事件气泡播报（Step 9：外部项目借鉴 — 任务状态挂件主动播报）
      const bubble = msg.payload?.bubble as string | undefined;
      switch (msg.event_type) {
        case "task.started":
          showBrief(bubble || "任务开始执行…", 3000);
          break;
        case "task.progress":
          showBrief(bubble || "执行中…", 2400);
          break;
        case "task.approval_required":
          showBrief(bubble || "需要你确认", 8000);
          break;
        case "task.approval_reminder": {
          const reminderText = bubble || "等待确认已 30 秒，需要你决定";
          showBrief(reminderText, 8000);
          setAlert(true);
          window.setTimeout(() => setAlert(false), 3200);
          if (!voiceStatusRef.current?.auto_speak) break;
          void synthesizeSpeech(reminderText)
            .then(async (blob) => {
              const ctx = await ensureAudioContext();
              if (!ctx || !blob.size) return;
              const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
              const src = ctx.createBufferSource();
              src.buffer = buf;
              src.connect(ctx.destination);
              src.start();
            })
            .catch(() => { /* TTS 不可用时静默，保留视觉提醒 */ });
          break;
        }
        case "task.completed":
          showBrief(bubble || "✓ 任务完成", 4000);
          break;
        case "task.failed":
          showBrief(bubble || "✗ 任务失败", 4000);
          break;
        case "task.cancelled":
          showBrief(bubble || "已取消", 3000);
          break;
      }

      if (msg.event_type === "conversation.completed") {
        if (msg.payload?.expand_ui === true && widgetTurnRef.current) {
          void openMainUi();
        }
      }

      if (next === "interrupted") {
        window.setTimeout(async () => {
          try {
            const resp = await fetch("http://127.0.0.1:8736/api/widget/state");
            const body = (await resp.json()) as {
              widget_state?: { state?: string } | null;
            };
            if (body.widget_state?.state) {
              setState(body.widget_state.state as WidgetState);
            }
          } catch {
            setState("listening");
          }
        }, 1300);
      }
      if (next === "completed") {
        window.setTimeout(() => {
          setState((cur) => (cur === "completed" ? "idle" : cur));
        }, 3200);
      }
    };

    const stop = connectEvents(wsUrl, onMsg, (open) => {
      if (!alive) return;
      setConnected(open);
      if (!open) {
        setPersistentHint("服务未连接");
      } else {
        setPersistentHint("");
      }
    });
    return () => {
      alive = false;
      stop();
      stopVoiceResources();
      audioCtxRef.current?.close().catch(() => {
        /* 忽略 */
      });
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const loadVoice = async (): Promise<void> => {
      // 冷启动时 AI 服务可能尚未就绪：失败后自动重试，避免语音芯片缺失
      for (let attempt = 0; alive && attempt < 12; attempt += 1) {
        try {
          const voice = await fetchVoiceStatus();
          if (!alive) return;
          setVoiceStatus(voice);
          if (voice.activation?.persona_name) {
            const name = voice.activation.persona_name;
            setPersonaName(name);
            personaNameRef.current = name;
          }
          return;
        } catch {
          if (!alive) return;
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
    };
    void loadVoice();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const image = new Image();
    image.src = mascotArt;
  }, [mascotArt]);

  useEffect(() => {
    let alive = true;
    const refreshLease = async (): Promise<void> => {
      const [owned, voice] = await Promise.all([
        acquireVoiceLease(),
        fetchVoiceStatus().catch(() => null),
      ]);
      if (!alive) return;
      if (voice && voice.auto_speak !== voiceStatusRef.current?.auto_speak) {
        setVoiceStatus(voice);
      }
      setVoiceLeaseOwned(owned);
      if (!owned) {
        stopVoiceResources();
        setVoiceMode("off");
      }
    };
    void refreshLease();
    const timer = setInterval(() => void refreshLease(), 4000);
    return () => {
      alive = false;
      clearInterval(timer);
      stopVoiceResources();
      void releaseVoiceLease();
    };
  }, []);

  useEffect(() => {
    if (!voiceLeaseOwned) {
      autoVoiceRef.current = false;
      stopVoiceResources();
      setVoiceMode("off");
      return;
    }
    if (!voiceStatus?.enabled || voiceStatus.activation?.enabled === false) return;
    if (autoVoiceRef.current) return;
    autoVoiceRef.current = true;
    const mode = voiceStatus.activation?.default_state === "sleeping" ? "sleeping" : "listening";
    void enableAlwaysListen(mode);
    const resumeOnce = (): void => {
      alwaysRef.current?.resume();
      void ensureAudioContext();
      window.removeEventListener("pointerdown", resumeOnce);
    };
    window.addEventListener("pointerdown", resumeOnce);
    return () => window.removeEventListener("pointerdown", resumeOnce);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceLeaseOwned, voiceStatus]);

  useEffect(() => {
    let disposed = false;
    let unlisten: UnlistenFn | undefined;
    void invoke<WidgetPreferences>("get_widget_preferences")
      .then((next) => {
        if (!disposed) setPreferences(next);
      })
      .catch(() => {
        /* 非 Tauri 环境或配置不可用时使用默认值 */
      });
    void listen<WidgetPreferences>("widget-drag-settled", (event) => {
      if (dragFallbackTimerRef.current !== null) {
        window.clearTimeout(dragFallbackTimerRef.current);
        dragFallbackTimerRef.current = null;
      }
      draggingRef.current = false;
      dragStartRef.current = null;
      suppressClickUntilRef.current = Date.now() + WIDGET_CLICK_SUPPRESS_MS;
      setPreferences(event.payload);
    })
      .then((stop) => {
        if (disposed) stop();
        else unlisten = stop;
      })
      .catch(() => {
        /* 非 Tauri 环境没有事件通道 */
      });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent): void => {
      const start = dragStartRef.current;
      if (!start || draggingRef.current || event.pointerId !== start.pointerId) return;
      if ((event.buttons & 1) !== 1) {
        dragStartRef.current = null;
        return;
      }
      const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
      if (distance < WIDGET_DRAG_THRESHOLD_PX) return;

      draggingRef.current = true;
      dragStartRef.current = null;
      setCtxMenu(null);
      void invoke("start_widget_drag")
        .then(() => {
          dragFallbackTimerRef.current = window.setTimeout(() => {
            if (!draggingRef.current) return;
            suppressClickUntilRef.current = Date.now() + WIDGET_CLICK_SUPPRESS_MS;
            void invoke("finish_widget_drag").catch(() => {
              draggingRef.current = false;
              void invoke("cancel_widget_drag").catch(() => {
                /* 非 Tauri 环境忽略 */
              });
            });
          }, 2000);
        })
        .catch(() => {
          draggingRef.current = false;
          void invoke("cancel_widget_drag").catch(() => {
            /* 非 Tauri 环境忽略 */
          });
        });
    };
    const onPointerUp = (event: PointerEvent): void => {
      if (draggingRef.current) {
        suppressClickUntilRef.current = Date.now() + WIDGET_CLICK_SUPPRESS_MS;
        void invoke("finish_widget_drag").catch(() => {
          draggingRef.current = false;
        });
        return;
      }
      if (dragStartRef.current?.pointerId === event.pointerId) dragStartRef.current = null;
    };
    const onWindowBlur = (): void => {
      if (!draggingRef.current) dragStartRef.current = null;
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    window.addEventListener("blur", onWindowBlur);
    return () => {
      if (dragFallbackTimerRef.current !== null) {
        window.clearTimeout(dragFallbackTimerRef.current);
        dragFallbackTimerRef.current = null;
      }
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
      window.removeEventListener("blur", onWindowBlur);
    };
  }, []);

  useEffect(() => {
    const suppressNativeContextMenu = (event: MouseEvent): void => {
      if (event.target instanceof Element && event.target.closest(".composer")) return;
      event.preventDefault();
    };
    window.addEventListener("contextmenu", suppressNativeContextMenu, true);
    return () =>
      window.removeEventListener("contextmenu", suppressNativeContextMenu, true);
  }, []);

  useEffect(() => {
    if (!ctxMenu) return;
    const onPointerDown = (event: PointerEvent): void => {
      const target = event.target;
      if (
        target instanceof Element &&
        (target.closest(".ctx-menu") || target.closest(".stage"))
      ) {
        return;
      }
      setCtxMenu(null);
    };
    const onBlur = (): void => setCtxMenu(null);
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("blur", onBlur);
    };
  }, [ctxMenu]);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent): void => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable === true;
      if (event.code === "Space" && !typing && !inputOpenRef.current) {
        event.preventDefault();
        setInputOpen(true);
        inputOpenRef.current = true;
      } else if (event.key === "Escape" && inputOpenRef.current) {
        event.preventDefault();
        closeComposer();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  useEffect(() => {
    if (inputOpen) {
      window.requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [inputOpen]);

  segmentHandlerRef.current = (segment) => void handleVoiceSegment(segment);

  const activateStage = (): void => {
    if (inputOpenRef.current) {
      closeComposer();
      return;
    }
    setActive(true);
    void getCurrentWindow().setFocus().catch(() => {
      /* 忽略非 Tauri 环境 */
    });
  };

  const startStageDrag = (event: React.PointerEvent): void => {
    if (event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest("[data-no-drag]")) return;
    dragStartRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
    };
  };

  const clickSuppressed = (): boolean => Date.now() < suppressClickUntilRef.current;

  const toggleAutoHide = (): void => {
    const previous = preferences;
    const autoHide = !preferences.autoHide;
    setPreferences((current) => ({ ...current, autoHide }));
    void invoke<WidgetPreferences>("set_widget_auto_hide", { autoHide })
      .then(setPreferences)
      .catch(() => setPreferences(previous));
  };

  const changeScale = (scale: number): void => {
    setPreferences((current) => ({ ...current, scale }));
    void invoke<WidgetPreferences>("set_widget_scale", { scale })
      .then(setPreferences)
      .catch(() => {
        /* 保存失败时保留当前会话的预览值 */
      });
  };

  const openContextMenu = (event: React.MouseEvent): void => {
    event.preventDefault();
    const fallback = {
      x: Math.max(4, Math.min(event.clientX, window.innerWidth - CONTEXT_MENU_WIDTH)),
      y: Math.max(4, Math.min(event.clientY, window.innerHeight - CONTEXT_MENU_HEIGHT)),
    };
    setCtxMenu(fallback);

    const desktopWindow = getCurrentWindow();
    void Promise.all([
      desktopWindow.outerPosition(),
      currentMonitor(),
    ])
      .then(([position, monitor]) => {
        if (!monitor) return;
        const scale = monitor.scaleFactor;
        const minX = monitor.workArea.position.x + 4 * scale;
        const maxX =
          monitor.workArea.position.x +
          monitor.workArea.size.width -
          (CONTEXT_MENU_WIDTH + 4) * scale;
        const minY = monitor.workArea.position.y + 4 * scale;
        const maxY =
          monitor.workArea.position.y +
          monitor.workArea.size.height -
          (CONTEXT_MENU_HEIGHT + 4) * scale;
        const desiredX = position.x + event.clientX * scale;
        const desiredY = position.y + event.clientY * scale;
        setCtxMenu({
          x: (Math.max(minX, Math.min(desiredX, maxX)) - position.x) / scale,
          y: (Math.max(minY, Math.min(desiredY, maxY)) - position.y) / scale,
        });
      })
      .catch(() => {
        /* 非 Tauri 环境保留窗口内回退位置 */
      });
  };

  const voiceEnabled = voiceStatus?.enabled === true;
  const chipText =
    voiceMode === "listening"
      ? "听"
      : voiceMode === "sleeping"
        ? "静"
        : voiceMode === "starting"
          ? "·"
          : voiceEnabled
            ? "关"
            : "无";
  const chipTitle = voiceEnabled
    ? voiceMode === "listening"
      ? "聆听中：点击静默，右键关闭"
      : voiceMode === "sleeping"
        ? "静默中：点击唤醒"
        : "语音未开启：点击开启"
    : "语音未配置";

  return (
    <div
      className="w-root"
      data-state={state}
      data-emotion={emotion}
      data-persona-style={presentation?.style ?? "human"}
        data-alert={alert ? "1" : "0"}
      data-voice={voiceMode}
      data-speaking={speaking ? "1" : "0"}
      data-connected={connected}
      data-active={active ? "1" : "0"}
      data-input-open={inputOpen ? "1" : "0"}
    >
      {inputOpen && (
        <div className="composer" data-no-drag ref={composerRef}>
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onBlur={() => {
              window.setTimeout(() => {
                if (!composerRef.current?.contains(document.activeElement)) {
                  closeComposer();
                }
              }, 0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              } else if (e.key === "Escape") {
                e.preventDefault();
                closeComposer();
              }
            }}
            placeholder="输入短消息…"
            aria-label="输入短消息"
          />
          <button
            className="send-button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={handleSend}
            disabled={!connected || busy || !input.trim()}
          >
            发送
          </button>
        </div>
      )}

      <div
        className="stage"
        data-active={active ? "1" : "0"}
        title="点击激活（播报中点击打断）· 双击打开主界面 · 按住拖动 · 右键菜单"
        onPointerDown={startStageDrag}
        onMouseEnter={() => applyEmotion("attentive")}
        onMouseLeave={() => {
          if (state === "idle") applyEmotion("neutral");
        }}
        onMouseUp={() => {
          if (state === "idle") applyEmotion("neutral");
        }}
        onClick={(event) => {
          if (clickSuppressed()) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          // 播报中点击 = 打断当前语音（与主界面 ⏹ 停止等价）
          if (speakingRef.current) {
            stopSpeaking();
            showBrief("已打断", 1600);
            void notifySpeechInterrupted();
            setCtxMenu(null);
            return;
          }
          activateStage();
          setCtxMenu(null);
        }}
        onDoubleClick={(event) => {
          if (clickSuppressed()) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          void openMainUi();
        }}
        onContextMenu={(e) => {
          openContextMenu(e);
        }}
      >
        <div
          className="bubble"
          ref={bubbleRef}
          data-visible={bubble && !inputOpen ? "1" : "0"}
          aria-live="polite"
        >
          {bubble}
        </div>
        <img
          className="mascot"
          src={mascotArt}
          alt={`DeskMate ${bubble || (connected ? "状态正常" : "服务未连接")}`}
          draggable={false}
          style={{
            width: `${MASCOT_BASE_SIZE * preferences.scale}px`,
            height: `${MASCOT_BASE_SIZE * preferences.scale}px`,
          }}
        />

        <div className="badge">
          <span className="badge-thinking">···</span>
          <span className="badge-question">?</span>
          <span className="badge-warn">!</span>
          <span className="badge-done">✓</span>
          <span className="badge-ring" />
        </div>

        <div className="waves" aria-hidden="true">
          <i /><i /><i />
        </div>

        {voiceStatus && (
          <button
            className={`voice-chip voice-${voiceMode}`}
            data-no-drag
            title={chipTitle}
            aria-label={chipTitle}
            onClick={(e) => {
              e.stopPropagation();
              toggleVoiceState();
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              disableAlwaysListen();
            }}
          >
            <span className="voice-dot" />
            <span>{chipText}</span>
          </button>
        )}
      </div>
      {/* 右键菜单 */}
      {ctxMenu && (
        <div
          className="ctx-menu"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          data-no-drag
        >
          <button
            onClick={() => {
              setCtxMenu(null);
              void openMainUi();
            }}
          >
            打开主界面
          </button>
          <button
            className="ctx-toggle"
            onClick={toggleAutoHide}
          >
            {preferences.autoHide ? "✓ 靠近边缘自动隐藏" : "靠近边缘自动隐藏"}
          </button>
          <div className="ctx-range">
            <label htmlFor="widget-scale">
              <span>角色大小</span>
              <span>{Math.round(preferences.scale * 100)}%</span>
            </label>
            <input
              id="widget-scale"
              type="range"
              min={WIDGET_SCALE_MIN}
              max={WIDGET_SCALE_MAX}
              step="0.05"
              value={preferences.scale}
              onChange={(event) => changeScale(Number(event.target.value))}
            />
          </div>
          <button
            className="ctx-danger"
            onClick={() => {
              setCtxMenu(null);
              void invoke("quit_app");
            }}
          >
            退出 DeskMate
          </button>
        </div>
      )}
    </div>
  );
}
