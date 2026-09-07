import { useEffect, useRef, useState } from "react";
import {
  fetchConversation,
  fetchConversations,
  fetchSession,
  fetchVoiceStatus,
  apiVoiceIntent,
  publishEvent,
  recognizeSpeech,
  streamChat,
  synthesizeSpeech,
  type ChatMessageView,
  type VoiceEndpointStatus,
} from "./api";
import { startRecording, type MicRecorder } from "./recorder";
import {
  startAlwaysListener,
  type AlwaysListener,
  type AlwaysListenSegment,
} from "./alwaysListen";

// 语音模式：off（未监听）/ listening（聆听中）/ sleeping（静默，仅唤醒词可打断）
type VoiceMode = "off" | "listening" | "sleeping";

function normText(text: string): string {
  return text.replace(/[\s，。！？、,.!?'"“”]/g, "").toLowerCase();
}

export default function ChatPage() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageView[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [echoMode, setEchoMode] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceEndpointStatus | null>(null);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("off");
  const [personaName, setPersonaName] = useState("千问");
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [notice, setNotice] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const loadingRef = useRef(false);
  const recorderRef = useRef<MicRecorder | null>(null);
  const alwaysRef = useRef<AlwaysListener | null>(null);
  const segmentHandlerRef = useRef<(segment: AlwaysListenSegment) => void>(() => {});
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playbackRef = useRef<AudioBufferSourceNode | null>(null);
  const speakPendingRef = useRef(false);
  const speakingRef = useRef(false);
  const speakStartAtRef = useRef(0);
  const speakEndAtRef = useRef(0);
  const lastSpokenRef = useRef<string>("");
  const lastSpokenAtRef = useRef(0);
  const voiceModeRef = useRef<VoiceMode>("off");
  voiceModeRef.current = voiceMode;

  useEffect(() => {
    let alive = true;
    const init = async () => {
      try {
        const session = await fetchSession();
        if (alive) setEchoMode(session.model.echo_mode);
      } catch {
        /* 服务离线时由主页提示 */
      }
      try {
        const voice = await fetchVoiceStatus();
        if (alive) {
          setVoiceStatus(voice);
          if (voice.enabled && voice.activation) {
            setPersonaName(voice.activation.persona_name || "千问");
          }
        }
      } catch {
        /* 语音未启用时保持 null */
      }
      try {
        const list = await fetchConversations();
        if (!alive || list.length === 0) return;
        const conv = await fetchConversation(list[0].conversation_id);
        if (!alive) return;
        setConversationId(conv.conversation_id);
        setMessages(conv.messages);
      } catch {
        /* 首次进入无历史属正常 */
      }
    };
    void init();
    return () => {
      alive = false;
      recorderRef.current?.cancel();
      alwaysRef.current?.stop();
      playbackRef.current?.stop();
      audioCtxRef.current?.close().catch(() => {
        /* 忽略 */
      });
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

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
        /* 用户未交互前可能失败，后续 pointerdown 再恢复 */
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
    if (!voiceStatus?.enabled || speakingRef.current) return;
    const ctx = await ensureAudioContext();
    if (!ctx) {
      setNotice("语音播放不可用：浏览器不支持音频");
      return;
    }
    lastSpokenRef.current = text;
    lastSpokenAtRef.current = Date.now();
    speakingRef.current = true;
    speakStartAtRef.current = Date.now();
    speakEndAtRef.current = 0;
    setSpeaking(true);
    let source: AudioBufferSourceNode | null = null;
    try {
      const blob = await synthesizeSpeech(text);
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
        void publishEvent({ event_type: "speech.stopped", source: "speech", payload: {} });
      };
      source.start();
    } catch (e) {
      if (playbackRef.current === source) playbackRef.current = null;
      speakingRef.current = false;
      speakEndAtRef.current = Date.now();
      setSpeaking(false);
      setNotice(e instanceof Error ? `语音播报失败：${e.message}` : "语音播报失败");
    }
  };

  const submitMessage = async (text: string, speakReply: boolean): Promise<void> => {
    if (!text.trim() || busy) return;
    if (loadingRef.current) return;
    setBusy(true);
    setNotice("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text, created_at: new Date().toISOString() },
      { role: "assistant", content: "", created_at: "" },
    ]);

    try {
      const done = await streamChat(conversationId, text, (delta) => {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = { ...last, content: last.content + delta };
          }
          return next;
        });
      });
      setConversationId(done.conversation_id);
      if (speakReply && voiceStatus?.enabled) {
        // 短回复朗读全文；长回复朗读摘要（全文保留在消息里，可点 🔊 听全文）
        stopSpeaking();
        void speak(done.speak_text || done.message);
        setNotice(done.short ? "" : "已自动播报摘要，点消息下方 🔊 可朗读全文");
      } else if (!done.short) {
        setNotice("回复较长已展示在上方消息中");
      } else {
        setNotice("");
      }
    } catch (e) {
      setNotice(e instanceof Error ? `回复失败：${e.message}` : "回复失败");
    } finally {
      setBusy(false);
    }
  };

  const send = (): void => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    // 文字输入也播报短回复：桌面精灵要“会说话”，不是只在语音模式出声
    void submitMessage(text, true);
  };

  const toggleMic = async (): Promise<void> => {
    if (recording) {
      const recorder = recorderRef.current;
      recorderRef.current = null;
      setRecording(false);
      if (!recorder) return;
      setNotice("识别中…");
      const wav = await recorder.stop();
      if (!wav) {
        setNotice("未录到有效音频（或解码失败），请重试");
        return;
      }
      try {
        const { text } = await recognizeSpeech(wav);
        if (!text.trim()) {
          setNotice("没听清，再说一次？");
          return;
        }
        setInput("");
        void submitMessage(text.trim(), true);
      } catch (e) {
        setNotice(e instanceof Error ? `语音识别失败：${e.message}` : "语音识别失败");
      }
      return;
    }

    // 播报中开始录音 = 打断当前播报（barge-in 基础形态）
    stopSpeaking();
    if (!voiceStatus?.enabled) {
      setNotice("语音未配置：请在 config/settings.yaml 或 .env 配置 DASHSCOPE_API_KEY");
      return;
    }
    const recorder = await startRecording();
    if (!recorder) {
      setNotice("无法访问麦克风，请在浏览器 / 系统设置中授权后重试");
      return;
    }
    recorderRef.current = recorder;
    setRecording(true);
    setNotice("聆听中… 说完后再次点击🎤结束");
  };

  async function enableAlwaysListen(): Promise<void> {
    if (alwaysRef.current) return;
    if (!voiceStatus?.enabled) {
      setNotice("语音未配置，无法开启常开监听");
      return;
    }
    setNotice("正在开启常开监听…");
    const ctx = await ensureAudioContext();
    if (!ctx) {
      setNotice("无法启用音频：浏览器不支持 AudioContext");
      setVoiceMode("off");
      return;
    }
    const listener = await startAlwaysListener({
      // 不自动打断播报：扬声器回声会被 VAD 当起音，自动打断会把 TTS 掐断。
      // V1 抢话用界面「⏹ 停止」按钮；全双工引擎接入后再做真正的语音抢话。
      onSegment: (segment) => segmentHandlerRef.current(segment),
      onError: (message) => {
        setNotice(message);
        setVoiceMode("off");
      },
      onStop: () => {
        if (!alwaysRef.current) setVoiceMode("off");
      },
    }, ctx);
    if (!listener) return;
    alwaysRef.current = listener;
    setNotice("");
  }

  function disableAlwaysListen(): void {
    alwaysRef.current?.stop();
    alwaysRef.current = null;
    recorderRef.current?.cancel();
    recorderRef.current = null;
    setRecording(false);
    setVoiceMode("off");
    setNotice("已关闭常开监听（可手动按键说话）");
  }

  async function handleVoiceSegment(segment: AlwaysListenSegment): Promise<void> {
    if (busy) return;
    if (speakingRef.current) return; // 仍在播报，交给 onUtteranceStart 处理
    // 播报回采窗口内开始的语音：只做打断，不送识别（防止回声造成重复）
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
    } catch (e) {
      setNotice(e instanceof Error ? `语音识别失败：${e.message}` : "语音识别失败");
      return;
    }
    if (!text) return;

    // 自声回环抑制：刚播报过相似内容（扬声器回采）时忽略
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
    } catch {
      /* 意图接口失败按普通对话处理 */
    }

    const mode = voiceModeRef.current;
    if (intent === "sleep") {
      stopSpeaking();
      setVoiceMode("sleeping");
      setNotice("已静默：非唤醒内容不回应");
      void speak(reply ?? "好，我先安静一会儿。想找我的时候说唤醒词就好啦。");
      return;
    }
    if (intent === "wake" && mode === "sleeping") {
      stopSpeaking();
      setVoiceMode("listening");
      setNotice(`已唤醒（${personaName}）`);
      void speak(reply ?? `在呢～我是${personaName}，有什么想让我帮忙的？`);
      return;
    }
    if (mode === "sleeping") return; // 静默态非唤醒词：零回应

    setInput("");
    void submitMessage(text, true);
  }

  const toggleAlwaysListen = (): void => {
    if (voiceMode === "off") {
      void enableAlwaysListen();
    } else {
      disableAlwaysListen();
    }
  };

  const forceSilence = (): void => {
    stopSpeaking();
    setVoiceMode("sleeping");
    setNotice("已静默（按钮）：说唤醒词恢复");
  };

  const forceWake = (): void => {
    stopSpeaking();
    setVoiceMode("listening");
    setNotice(`已唤醒（${personaName}）`);
  };

  // 常开监听始终使用最新一轮的 handler（识别/意图/提交状态不过期）
  segmentHandlerRef.current = (segment) => void handleVoiceSegment(segment);

  useEffect(() => {
    if (!voiceStatus?.enabled || !voiceStatus.activation?.enabled) return;
    setVoiceMode((prev) => (prev === "off" ? voiceStatus.activation.default_state : prev));
    void enableAlwaysListen();
    const resumeOnce = (): void => {
      alwaysRef.current?.resume();
      void ensureAudioContext();
      window.removeEventListener("pointerdown", resumeOnce);
    };
    window.addEventListener("pointerdown", resumeOnce);
    return () => window.removeEventListener("pointerdown", resumeOnce);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceStatus?.enabled, voiceStatus?.activation?.enabled, voiceStatus?.activation?.default_state]);

  return (
    <section className="chat-panel">
      <div className="chat-toolbar">
        <span>对话历史保存在本地（data/conversations）</span>
        {echoMode && <em className="echo-tag">演示模式：未配置模型 API（echo）</em>}
        {voiceStatus && !voiceStatus.enabled && (
          <em className="echo-tag voice-off">语音未配置：设置 DASHSCOPE_API_KEY 后重启</em>
        )}
      </div>
      {voiceStatus?.enabled && voiceStatus.activation?.enabled && (
        <div className="voice-mode-row">
          <span
            className={`mode-chip ${
              voiceMode === "sleeping"
                ? "mode-sleep"
                : voiceMode === "listening"
                  ? "mode-listen"
                  : ""
            }`}
          >
            {voiceMode === "listening"
              ? "● 聆听中"
              : voiceMode === "sleeping"
                ? "💤 静默中"
                : "常开已关闭"}
          </span>
          <span className="wake-hint">唤醒词：你好，{personaName}</span>
          <button className="mini-btn" onClick={toggleAlwaysListen}>
            {voiceMode === "off" ? "常开：关" : "常开：开"}
          </button>
          <button className="mini-btn" onClick={forceSilence}>
            静默
          </button>
          <button className="mini-btn" onClick={forceWake}>
            唤醒
          </button>
        </div>
      )}
      <div className="chat-list">
        {messages.length === 0 && (
          <div className="chat-empty">
            输入任意内容开始对话。
            {echoMode && (
              <>
                <br />
                提示：以「长回复」开头可体验自动展开主界面。
              </>
            )}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={`${m.role}-${i}`} className={`msg ${m.role === "user" ? "msg-user" : "msg-bot"}`}>
            <div className="msg-name">{m.role === "user" ? "你" : "DeskMate"}</div>
            <div className="msg-body">
              {m.content ? (
                m.content
              ) : (
                <span className="typing">思考中…</span>
              )}
            </div>
            {m.role === "assistant" && m.content && voiceStatus?.enabled && (
              <button
                className="mini-btn msg-speak"
                onClick={() => {
                  stopSpeaking();
                  void speak(m.content.length > 1900 ? `${m.content.slice(0, 1900)}…` : m.content);
                }}
                title="播报这段回复"
              >
                🔊 播报
              </button>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      {notice && <div className="notice-line">{notice}</div>}
      <div className="chat-input-row">
        <button
          className={`mic-btn ${recording ? "recording" : ""}`}
          onClick={() => void toggleMic()}
          disabled={busy || voiceMode !== "off"}
          title={
            voiceMode !== "off"
              ? "常开监听中，直接说话即可；关闭常开后可按键说话"
              : voiceStatus?.enabled
                ? "语音对话（点击开始，再次点击结束并识别）"
                : "语音未配置"
          }
        >
          {recording ? "■" : "🎤"}
        </button>
        {speaking && (
          <button className="stop-btn" onClick={stopSpeaking} title="停止播报（打断）">
            ⏹ 停止
          </button>
        )}
        <textarea
          value={input}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          disabled={busy}
        />
        <button className="send-btn" onClick={send} disabled={busy || !input.trim()}>
          发送
        </button>
      </div>
    </section>
  );
}
