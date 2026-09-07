import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  apiVoiceIntent,
  connectEvents,
  eventToState,
  fetchVoiceStatus,
  recognizeSpeech,
  streamChat,
  synthesizeSpeech,
  type VoiceEndpointStatus,
  type WsMessage,
  type WidgetState,
} from "../api";
import {
  startAlwaysListener,
  type AlwaysListener,
  type AlwaysListenSegment,
} from "../voiceCapture";
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

function normText(text: string): string {
  return text.replace(/[\s，。！？、,.!?'"“”]/g, "").toLowerCase();
}

export default function Widget() {
  const [state, setState] = useState<WidgetState>("idle");
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

  const inputRef = useRef<HTMLInputElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const bubbleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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

  busyRef.current = busy;
  voiceModeRef.current = voiceMode;
  voiceStatusRef.current = voiceStatus;
  personaNameRef.current = personaName;
  activeRef.current = active;
  inputOpenRef.current = inputOpen;

  const showBrief = (text: string, ms = 3200): void => {
    if (bubbleTimerRef.current) clearTimeout(bubbleTimerRef.current);
    setBubble(text);
    bubbleTimerRef.current = setTimeout(() => {
      setBubble(persistentHintRef.current || "");
    }, ms);
  };

  const setPersistentHint = (text: string): void => {
    if (bubbleTimerRef.current) clearTimeout(bubbleTimerRef.current);
    persistentHintRef.current = text;
    setBubble(text);
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

  const speak = async (text: string): Promise<void> => {
    const voice = voiceStatusRef.current;
    if (!voice?.enabled || !voice.tts.available || speakingRef.current) return;
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
      const blob = await synthesizeSpeech(text.length > 1900 ? `${text.slice(0, 1900)}…` : text);
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
        showBrief(done.message || done.speak_text, 3600);
        if (speakReply && voiceStatusRef.current?.enabled && voiceModeRef.current !== "off") {
          stopSpeaking();
          void speak(done.speak_text || done.message);
        }
      }
    } catch (e) {
      showBrief(e instanceof Error ? `回复失败：${e.message}` : "回复失败", 3800);
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
      const r = await recognizeSpeech(segment.wav);
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
      if (!next) return;
      setState(next);
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
      try {
        const voice = await fetchVoiceStatus();
        if (!alive) return;
        setVoiceStatus(voice);
        if (voice.activation?.persona_name) {
          const name = voice.activation.persona_name;
          setPersonaName(name);
          personaNameRef.current = name;
        }
      } catch {
        /* 服务未就绪时由连接状态提示 */
      }
    };
    void loadVoice();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
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
  }, [voiceStatus]);

  useEffect(() => {
    void invoke("place_widget_bottom_right").catch(() => {
      /* Rust 已处理 */
    });
  }, []);

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

  const startStageDrag = (event: React.MouseEvent): void => {
    if (event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest("[data-no-drag]")) return;
    void getCurrentWindow().startDragging().catch(() => {
      /* 忽略非 Tauri 环境 */
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
        title="点击激活 · 双击打开主界面 · 按住拖动"
        onMouseDown={startStageDrag}
        onClick={activateStage}
        onDoubleClick={() => void openMainUi()}
      >
        <div
          className="bubble"
          data-visible={bubble && !inputOpen ? "1" : "0"}
          aria-live="polite"
        >
          {bubble}
        </div>
        <div className="aura" />
        <svg
          className="mascot"
          viewBox="0 0 200 200"
          aria-label={`DeskMate ${bubble || (connected ? "状态正常" : "服务未连接")}`}
        >
          <defs>
            <radialGradient id="bodyGrad" cx="50%" cy="38%" r="75%">
              <stop offset="0%" stopColor="#ffe6bd" />
              <stop offset="100%" stopColor="#ffca85" />
            </radialGradient>
            <linearGradient id="bellyGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fff6e6" />
              <stop offset="100%" stopColor="#ffe7c2" />
            </linearGradient>
          </defs>

          <g className="ears">
            <path
              d="M58 66 Q44 22 30 34 Q26 58 46 84 Z"
              fill="url(#bodyGrad)"
              stroke="#ecb877"
              strokeWidth="3"
              strokeLinejoin="round"
            />
            <path
              d="M142 66 Q156 22 170 34 Q174 58 154 84 Z"
              fill="url(#bodyGrad)"
              stroke="#ecb877"
              strokeWidth="3"
              strokeLinejoin="round"
            />
            <path className="inner-ear" d="M52 60 Q44 34 36 40 Q35 56 50 76 Z" fill="#ffb0a1" />
            <path className="inner-ear" d="M148 60 Q156 34 164 40 Q165 56 150 76 Z" fill="#ffb0a1" />
          </g>

          <ellipse className="body" cx="100" cy="122" rx="70" ry="64" fill="url(#bodyGrad)" stroke="#ecb877" strokeWidth="3.5" />
          <ellipse className="belly" cx="100" cy="140" rx="42" ry="36" fill="url(#bellyGrad)" />

          <ellipse className="cheek" cx="62" cy="106" rx="10" ry="6.5" fill="#ffad9e" opacity="0.6" />
          <ellipse className="cheek" cx="138" cy="106" rx="10" ry="6.5" fill="#ffad9e" opacity="0.6" />

          <g className="eyes">
            <ellipse className="eye" cx="78" cy="96" rx="7.5" ry="9" fill="#3a2c22" />
            <ellipse className="eye" cx="122" cy="96" rx="7.5" ry="9" fill="#3a2c22" />
            <circle className="eye-glint" cx="81" cy="92.5" r="2.4" fill="#fff" />
            <circle className="eye-glint" cx="125" cy="92.5" r="2.4" fill="#fff" />
          </g>

          <g className="mouth-smile">
            <path d="M90 120 Q100 129 110 120" fill="none" stroke="#7a4a3a" strokeWidth="3.4" strokeLinecap="round" />
          </g>
          <g className="mouth-ah">
            <path d="M90 118 Q100 134 110 118 Z" fill="#8c4f3d" />
            <path d="M93 122 Q100 129 107 122 Z" fill="#ff9d8c" />
          </g>
          <g className="mouth-o">
            <ellipse cx="100" cy="122" rx="6.5" ry="9" fill="#8c4f3d" />
          </g>

          <ellipse className="foot" cx="78" cy="182" rx="12" ry="6" fill="#ecb877" opacity="0.9" />
          <ellipse className="foot" cx="122" cy="182" rx="12" ry="6" fill="#ecb877" opacity="0.9" />
        </svg>

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
    </div>
  );
}
