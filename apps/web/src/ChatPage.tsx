import { useEffect, useRef, useState } from "react";
import {
  fetchConversation,
  fetchConversations,
  fetchAwaitingRuns,
  fetchRuns,
  fetchModelProfiles,
  fetchPersonas,
  fetchSession,
  fetchSettings,
  fetchVoiceStatus,
  bindConversationProject,
  apiVoiceIntent,
  decideRun,
  decideToolApproval,
  cancelRun,
  publishEvent,
  recognizeSpeech,
  streamChat,
  synthesizeSpeech,
  synthesizeSpeechStream,
  uploadChatAttachments,
  type AgentRun,
  type ChatAttachmentView,
  type ChatMessageView,
  type ConversationSummary,
  type ModelProfile,
  type ToolApprovalView,
  type VoiceEndpointStatus,
} from "./api";
import MarkdownLite from "./MarkdownLite";
import { isTauri } from "@tauri-apps/api/core";
import { open as openFolderDialog } from "@tauri-apps/plugin-dialog";
import type { EventEnvelope } from "@deskmate/contracts";
import { startRecording, type MicRecorder } from "./recorder";
import {
  startAlwaysListener,
  type AlwaysListener,
  type AlwaysListenSegment,
} from "./alwaysListen";
import ModelProfileSelect from "./ModelProfileSelect";
import { Volume2, Save, Mic, Square, Paperclip, LoaderCircle } from "lucide-react";

// 语音模式：off（未监听）/ listening（聆听中）/ sleeping（静默，仅唤醒词可打断）
type VoiceMode = "off" | "listening" | "sleeping";

// WI-07：提示条按语义分级配色，失败/降级不再复用成功绿。
type NoticeKind = "ok" | "warn" | "error";

// 后台任务在对话页的实时状态（任务进展/结果另有消息落库）
type LiveTask = {
  taskId: string;
  runId: string | null;
  text: string;
  status: "running" | "awaiting_approval";
};

const TASK_EVENT_TYPES = [
  "task.started",
  "task.progress",
  "task.approval_required",
  "task.approval_reminder",
  "task.completed",
  "task.failed",
  "task.cancelled",
];

// 记忆深度三态：auto 交给分流，casual 轻量记忆，work 完整项目记忆
const CHAT_MODES = [
  { mode: "auto", label: "自动", hint: "按任务分流自动选择记忆深度" },
  { mode: "casual", label: "闲聊", hint: "轻量记忆" },
  { mode: "work", label: "工作", hint: "完整项目记忆" },
] as const;

const CURRENT_PROJECT_KEY = "deskmate.current.project.path";

const NOTICE_STYLE: Record<NoticeKind, string> = {
  ok: "text-ok bg-ok-50",
  warn: "text-warn bg-warn-50",
  error: "text-bad bg-bad-50",
};

function normText(text: string): string {
  return text.replace(/[\s，。！？、,.!?'"“”‘’；：:;…—\-()（）【】《》~～·]/g, "").toLowerCase();
}

function fmtChatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function ChatPage({
  voiceLeaseOwned,
  onOpenSettings,
  events = [],
}: {
  voiceLeaseOwned: boolean;
  onOpenSettings?: () => void;
  events?: EventEnvelope[];
}) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showProjects, setShowProjects] = useState(false);
  const [messages, setMessages] = useState<ChatMessageView[]>([]);
  const [projectInput, setProjectInput] = useState("");
  const [projectNameInput, setProjectNameInput] = useState("");
  const [projectDraftOpen, setProjectDraftOpen] = useState(false);
  const [attachments, setAttachments] = useState<ChatAttachmentView[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [awaitingRuns, setAwaitingRuns] = useState<AgentRun[]>([]);
  const [backgroundRuns, setBackgroundRuns] = useState<AgentRun[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [liveTask, setLiveTask] = useState<LiveTask | null>(null);
  const [toolApproval, setToolApproval] = useState<ToolApprovalView | null>(null);
  const [echoMode, setEchoMode] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceEndpointStatus | null>(null);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("off");
  const [personaName, setPersonaName] = useState("千问");
  const [speakerName, setSpeakerName] = useState("DeskMate");
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [memoryBubble, setMemoryBubble] = useState("");
  const [chatMode, setChatMode] = useState<"auto" | "casual" | "work">("auto");
  const [notice, setNoticeText] = useState("");
  const [noticeKind, setNoticeKind] = useState<NoticeKind>("ok");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const loadingRef = useRef(false);
  const busyRef = useRef(false);
  const conversationIdRef = useRef<string | null>(null);
  const pendingRefreshRef = useRef(false);
  // 进入页面时已有的事件视为「历史」，只处理本次挂载之后到达的任务事件
  const seenEventsRef = useRef<Set<string> | null>(null);
  if (seenEventsRef.current === null) {
    seenEventsRef.current = new Set(events.map((event) => event.event_id));
  }
  const recorderRef = useRef<MicRecorder | null>(null);
  const alwaysRef = useRef<AlwaysListener | null>(null);
  const segmentHandlerRef = useRef<(segment: AlwaysListenSegment) => void>(() => {});
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playbackRef = useRef<AudioBufferSourceNode | null>(null);
  const playbackAbortRef = useRef<AbortController | null>(null);
  const lastMemoryBubbleAtRef = useRef(0);
  const memoryBubbleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const speakPendingRef = useRef(false);
  const speakingRef = useRef(false);
  const speakStartAtRef = useRef(0);
  const speakEndAtRef = useRef(0);
  const lastSpokenRef = useRef<string>("");
  const lastSpokenAtRef = useRef(0);
  const voiceModeRef = useRef<VoiceMode>("off");
  voiceModeRef.current = voiceMode;
  busyRef.current = busy;
  conversationIdRef.current = conversationId;

  // 统一提示入口：省略 kind 即普通提示（沿用原有绿色），失败类显式传 "error"/"warn"。
  const setNotice = (text: string, kind: NoticeKind = "ok"): void => {
    setNoticeText(text);
    setNoticeKind(kind);
  };

  const reloadAwaitingRuns = async (cid: string | null = conversationIdRef.current): Promise<void> => {
    try {
      const items = await fetchAwaitingRuns(cid);
      setAwaitingRuns(items);
    } catch {
      /* 服务离线或会话暂无待授权任务时忽略 */
    }
  };

  const reloadBackgroundRuns = async (): Promise<void> => {
    try {
      const items = await fetchRuns(50);
      setBackgroundRuns(items.filter((run) => run.status === "running" || run.status === "awaiting_approval"));
    } catch {
      /* 服务离线时保留当前状态 */
    }
  };

  const reloadConversations = async (): Promise<void> => {
    try {
      setConversations(await fetchConversations());
    } catch {
      /* 服务离线时保留当前列表 */
    }
  };

  useEffect(() => {
    let alive = true;
    const init = async () => {
      let loadedProfiles: ModelProfile[] = [];
      let personaProfileId = "";
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
        const [profiles, appSettings, personas] = await Promise.all([
          fetchModelProfiles(),
          fetchSettings(),
          fetchPersonas(),
        ]);
        loadedProfiles = profiles.filter(
          (profile) => profile.enabled && (profile.category === "text" || profile.category === "multimodal"),
        );
        const activePersona = personas.find(
          (persona) => persona.id === appSettings.active_persona_id,
        );
        personaProfileId = activePersona?.llm?.profile_id ?? "";
        if (alive && activePersona?.name) setSpeakerName(activePersona.name);
        if (alive) setModelProfiles(loadedProfiles);
      } catch {
        /* 模型档案未配置时保持演示模式 */
      }
      try {
        const list = await fetchConversations();
        if (!alive) return;
        setConversations(list);
        if (list.length === 0) {
          const sharedProject = localStorage.getItem(CURRENT_PROJECT_KEY) ?? "";
          if (sharedProject) {
            setProjectInput(sharedProject);
            setProjectNameInput(sharedProject.split(/[\\/]/).filter(Boolean).pop() || "");
          }
          setSelectedProfileId(
            personaProfileId || loadedProfiles.find((profile) => profile.is_default)?.id || "",
          );
          return;
        }
        const conv = await fetchConversation(list[0].conversation_id);
        if (!alive) return;
        setConversationId(conv.conversation_id);
        conversationIdRef.current = conv.conversation_id;
        setMessages(conv.messages);
        setProjectInput(conv.project || "");
        setProjectNameInput(conv.project_name || "");
        if (conv.project) localStorage.setItem(CURRENT_PROJECT_KEY, conv.project);
        setSelectedProfileId(
          conv.model_profile_id ||
            personaProfileId ||
            loadedProfiles.find((profile) => profile.is_default)?.id ||
            "",
        );
        await reloadAwaitingRuns(conv.conversation_id);
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

  const onProjectChanged = (event: Event): void => {
    const path = (event as CustomEvent<{ path?: string }>).detail?.path?.trim() ?? "";
    if (!path || busyRef.current) return;
    setProjectInput(path);
    setProjectNameInput(path.split(/[\\/]/).filter(Boolean).pop() || "");
    setNotice(`当前项目已切换为「${path.split(/[\\/]/).filter(Boolean).pop() || path}」`);
  };

  useEffect(() => {
    window.addEventListener("deskmate-project-changed", onProjectChanged);
    return () => window.removeEventListener("deskmate-project-changed", onProjectChanged);
  }, []);

  useEffect(() => {
    void reloadBackgroundRuns();
    const timer = window.setInterval(() => void reloadBackgroundRuns(), 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, awaitingRuns.length]);

  const modelOptions = [
    { id: "", label: "跟随角色 / 全局" },
    ...modelProfiles.map((profile) => ({
      id: profile.id,
      label: `${profile.name} · ${profile.model || profile.provider}`,
    })),
  ];

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
    playbackAbortRef.current?.abort();
    playbackAbortRef.current = null;
    speakingRef.current = false;
    speakEndAtRef.current = Date.now();
    setSpeaking(false);
  };

  const speak = async (text: string): Promise<void> => {
    if (!voiceStatus?.enabled || speakingRef.current) return;
    const ctx = await ensureAudioContext();
    if (!ctx) {
      setNotice("语音播放不可用：浏览器不支持音频", "warn");
      return;
    }
    lastSpokenRef.current = text;
    lastSpokenAtRef.current = Date.now();
    speakingRef.current = true;
    speakStartAtRef.current = Date.now();
    speakEndAtRef.current = 0;
    setSpeaking(true);

    // ponytail: 短文本（<=1句）走全量合成，长文本走流式
    const shortText = text.length < 80 && !text.includes("。") && !text.includes("！") && !text.includes("？");
    try {
      if (shortText) {
        const blob = await synthesizeSpeech(text);
        await _playBlob(ctx, blob);
      } else {
        const abort = new AbortController();
        playbackAbortRef.current = abort;
        const stream = await synthesizeSpeechStream(text, "web", abort.signal);
        for await (const chunk of stream) {
          if (!speakingRef.current) break;
          await _playBlob(ctx, chunk.audio);
        }
        playbackAbortRef.current = null;
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        // barge-in 取消，正常
      } else {
        setNotice(e instanceof Error ? `语音播报失败：${e.message}` : "语音播报失败", "error");
      }
    } finally {
      playbackRef.current = null;
      speakingRef.current = false;
      speakEndAtRef.current = Date.now();
      setSpeaking(false);
      void publishEvent({ event_type: "speech.stopped", source: "speech", payload: {} });
    }
  };

  /** 播放单个 Blob，返回 Promise 在播放完成后 resolve。barge-in 通过 playbackRef 停止。 */
  const _playBlob = async (ctx: AudioContext, blob: Blob): Promise<void> => {
    const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    playbackRef.current = source;
    return new Promise<void>((resolve, reject) => {
      source.onended = () => {
        if (playbackRef.current === source) playbackRef.current = null;
        resolve();
      };
      source.start();
    });
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
      const files = attachments;
      const done = await streamChat(conversationId, text, (delta) => {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = { ...last, content: last.content + delta };
          }
          return next;
        });
      }, selectedProfileId || null, projectInput.trim() || null, projectNameInput.trim() || null, files, chatMode, (approval) => {
        setToolApproval(approval);
      });
      setConversationId(done.conversation_id);
      conversationIdRef.current = done.conversation_id;
      if (done.skill_id) {
        setMessages((prev) => {
          const next = [...prev];
          const last = next.length - 1;
          if (next[last]?.role === "assistant") {
            next[last] = { ...next[last], skill_id: done.skill_id };
          }
          return next;
        });
      }
      setAttachments([]);
      if (speakReply && voiceStatus?.enabled && voiceStatus.auto_speak) {
        // 短回复朗读全文；长回复朗读摘要（全文保留在消息里，可点播报听全文）
        stopSpeaking();
        void speak(done.speak_text || done.message);
        setNotice(done.short ? "" : "已自动播报摘要，点消息下方播报可朗读全文");
      } else if (!done.short) {
        setNotice("回复较长已展示在上方消息中");
      } else {
        setNotice("");
      }
    } catch (e) {
      setNotice(e instanceof Error ? `回复失败：${e.message}` : "回复失败", "error");
    } finally {
      setBusy(false);
      busyRef.current = false;
      void reloadConversations();
      // 流式期间到达的任务事件：等这一轮结束再补刷，避免覆盖正在输出的回复
      if (pendingRefreshRef.current) {
        pendingRefreshRef.current = false;
        void refreshConversation();
      }
    }
  };

  // 任务进展写回会话后刷新一次，让「已开始 / 需要授权 / 结果」出现在对话里
  const refreshConversation = async (): Promise<void> => {
    const cid = conversationIdRef.current;
    if (!cid) return;
    if (busyRef.current) {
      pendingRefreshRef.current = true;
      return;
    }
    try {
      const conv = await fetchConversation(cid);
      setMessages(conv.messages);
    } catch {
      /* 刷新失败不影响当前展示 */
    }
  };

  useEffect(() => {
    const seen = seenEventsRef.current ?? new Set<string>();
    seenEventsRef.current = seen;
    let needRefresh = false;
    for (const env of events) {
      if (seen.has(env.event_id)) continue;
      seen.add(env.event_id);
      if (env.source !== "task") continue;
      if (env.event_type === "memory.updated") {
        const memBubble = typeof env.payload?.bubble === "string" ? env.payload.bubble : "";
        if (memBubble && env.conversation_id === conversationId) {
          // ponytail: 5min rate limit
          const now = Date.now();
          if (now - lastMemoryBubbleAtRef.current > 300_000) {
            lastMemoryBubbleAtRef.current = now;
            setMemoryBubble(memBubble);
            if (memoryBubbleTimerRef.current) clearTimeout(memoryBubbleTimerRef.current);
            memoryBubbleTimerRef.current = window.setTimeout(() => setMemoryBubble(""), 5000);
          }
        }
        continue;
      }
      if (!TASK_EVENT_TYPES.includes(env.event_type)) continue;
      if (env.conversation_id !== conversationId) continue;
      const payload = env.payload as { bubble?: unknown; run?: { run_id?: unknown } } | undefined;
      const runId = typeof payload?.run?.run_id === "string" ? payload.run.run_id : null;
      const bubble = typeof payload?.bubble === "string" ? payload.bubble : "";
      const taskId = env.task_id ?? "";
      if (env.event_type === "task.progress") {
        setLiveTask((prev) =>
          prev && prev.taskId === taskId
            ? { ...prev, runId, text: bubble || "执行中…", status: "running" }
            : prev,
        );
        continue;
      }
      if (env.event_type === "task.approval_reminder") {
        setLiveTask((prev) =>
          prev && prev.taskId === taskId ? { ...prev, runId, status: "awaiting_approval" } : prev,
        );
      }
      if (env.event_type === "task.started") {
        setLiveTask({ taskId, runId, text: "已开始执行", status: "running" });
      } else if (env.event_type === "task.approval_required") {
        setLiveTask({ taskId, runId, text: bubble || "等待你的授权", status: "awaiting_approval" });
      } else {
        setLiveTask((prev) => (prev && prev.taskId === taskId ? null : prev));
        // auto-speak on task completion/failure
        const speakPayload = env.payload as { speak_text?: string } | undefined;
        if (speakPayload?.speak_text && voiceStatus?.enabled && voiceStatus.auto_speak) {
          void (async () => {
            try {
              await speak(speakPayload.speak_text!);
            } catch { /* silent */ }
          })();
        }
      }
      needRefresh = true;
    }
    if (needRefresh) {
      void refreshConversation();
      void reloadAwaitingRuns();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, conversationId]);

  const decideRunById = async (runId: string | null, decision: "approved" | "rejected"): Promise<void> => {
    if (!runId) return;
    try {
      await decideRun(runId, decision);
      setAwaitingRuns((prev) => prev.filter((run) => run.run_id !== runId));
      setBackgroundRuns((prev) => prev.filter((run) => run.run_id !== runId));
      setLiveTask((prev) => (prev?.runId === runId ? null : prev));
      setNotice(decision === "approved" ? "已批准当前操作" : "已拒绝当前操作");
      void refreshConversation();
    } catch (e) {
      setNotice(e instanceof Error ? `授权操作失败：${e.message}` : "授权操作失败", "error");
    }
  };

  const decideToolApprovalById = async (
    approvalId: string,
    decision: "approved" | "rejected",
  ): Promise<void> => {
    try {
      await decideToolApproval(approvalId, decision);
      setToolApproval(null);
      setNotice(decision === "approved" ? "已批准工具调用" : "已拒绝工具调用");
    } catch (e) {
      setNotice(e instanceof Error ? `工具授权操作失败：${e.message}` : "工具授权操作失败", "error");
    }
  };

  const cancelBackgroundRun = async (runId: string): Promise<void> => {
    try {
      await cancelRun(runId);
      setBackgroundRuns((prev) => prev.filter((run) => run.run_id !== runId));
      setNotice("已取消后台任务");
      void refreshConversation();
    } catch (e) {
      setNotice(e instanceof Error ? `取消失败：${e.message}` : "取消失败", "error");
    }
  };

  const newConversation = (): void => {
    if (busy) return;
    setConversationId(null);
    conversationIdRef.current = null;
    setMessages([]);
    setLiveTask(null);
    setAwaitingRuns([]);
    setAttachments([]);
    setInput("");
    setShowHistory(false);
    setShowProjects(false);
    setProjectDraftOpen(false);
    setNotice("已新建对话");
  };

  const clearProject = async (): Promise<void> => {
    if (busy) return;
    try {
      if (conversationId) await bindConversationProject(conversationId, null);
      setProjectInput("");
      setProjectNameInput("");
      setNotice("已解除当前对话的项目绑定");
    } catch (e) {
      setNotice(e instanceof Error ? `解除项目失败：${e.message}` : "解除项目失败", "error");
    }
  };

  const openConversation = async (id: string): Promise<void> => {
    if (busy || id === conversationIdRef.current) {
      setShowHistory(false);
      return;
    }
    try {
      const conv = await fetchConversation(id);
      setConversationId(conv.conversation_id);
      conversationIdRef.current = conv.conversation_id;
      setMessages(conv.messages);
      setProjectInput(conv.project || "");
      setProjectNameInput(conv.project_name || "");
      if (conv.project) localStorage.setItem(CURRENT_PROJECT_KEY, conv.project);
      setAttachments([]);
      setLiveTask(null);
      setShowHistory(false);
      setShowProjects(false);
      await reloadAwaitingRuns(conv.conversation_id);
    } catch (e) {
      setNotice(e instanceof Error ? `历史对话加载失败：${e.message}` : "历史对话加载失败", "error");
    }
  };

  const chooseProjectFolder = async (): Promise<void> => {
    if (!isTauri()) {
      setNotice("请在 DeskMate 桌面应用中使用原生文件夹选择", "warn");
      return;
    }
    try {
      const selected = await openFolderDialog({
        directory: true,
        multiple: false,
        title: "选择项目文件夹",
      });
      if (typeof selected === "string") {
        setProjectInput(selected);
        if (!projectNameInput.trim()) {
          setProjectNameInput(selected.split(/[\\/]/).filter(Boolean).pop() || "");
        }
      }
    } catch (e) {
      setNotice(e instanceof Error ? `选择文件夹失败：${e.message}` : "选择文件夹失败", "error");
    }
  };

  const createProjectConversation = (): void => {
    if (!projectInput.trim() || !projectNameInput.trim()) {
      setNotice("请填写项目名称并选择项目文件夹", "warn");
      return;
    }
    if (busy) return;
    newConversation();
    setProjectInput(projectInput.trim());
    setProjectNameInput(projectNameInput.trim());
    localStorage.setItem(CURRENT_PROJECT_KEY, projectInput.trim());
    window.dispatchEvent(new CustomEvent("deskmate-project-changed", { detail: { path: projectInput.trim() } }));
    setNotice(`已创建项目「${projectNameInput.trim()}」，输入第一条消息即可开始对话`);
  };

  const handleFilesPicked = async (fileList: FileList | null): Promise<void> => {
    if (!fileList || fileList.length === 0) return;
    setUploadingFiles(true);
    try {
      const items = await uploadChatAttachments(Array.from(fileList));
      setAttachments((prev) => [...prev, ...items]);
    } catch (e) {
      setNotice(e instanceof Error ? `附件上传失败：${e.message}` : "附件上传失败", "error");
    } finally {
      setUploadingFiles(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const removeAttachment = (path: string): void => {
    setAttachments((prev) => prev.filter((item) => item.path !== path));
  };

  const projectName = (path: string): string =>
    path.split(/[\\/]/).filter(Boolean).pop() || path;

  const projectConversations = Array.from(
    new Map(
      conversations
        .filter((item) => item.project)
        .map((item) => [item.project as string, item]),
    ).values(),
  ).map((item) => ({
    path: item.project as string,
    name: item.project_name || projectName(item.project as string),
  }));

  const openProject = async (path: string): Promise<void> => {
    const latest = conversations.find((item) => item.project === path);
    if (latest) {
      setProjectDraftOpen(false);
      await openConversation(latest.conversation_id);
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
        setNotice("未录到有效音频（或解码失败），请重试", "warn");
        return;
      }
      try {
        const { text } = await recognizeSpeech(wav);
        if (!text.trim()) {
          setNotice("没听清，再说一次？", "warn");
          return;
        }
        setInput("");
        void submitMessage(text.trim(), true);
      } catch (e) {
        setNotice(e instanceof Error ? `语音识别失败：${e.message}` : "语音识别失败", "error");
      }
      return;
    }

    // 播报中开始录音 = 打断当前播报（barge-in 基础形态）
    stopSpeaking();
    if (!voiceStatus?.enabled) {
      setNotice("语音未配置：请在 config/settings.yaml 或 .env 配置 DASHSCOPE_API_KEY", "warn");
      return;
    }
    const recorder = await startRecording();
    if (!recorder) {
      setNotice("无法访问麦克风，请在浏览器 / 系统设置中授权后重试", "error");
      return;
    }
    recorderRef.current = recorder;
    setRecording(true);
    setNotice("聆听中… 说完后再次点击麦克风按钮结束");
  };

  async function enableAlwaysListen(): Promise<void> {
    if (alwaysRef.current) return;
    if (!voiceLeaseOwned) {
      setNotice("当前语音由挂件占用", "warn");
      return;
    }
    if (!voiceStatus?.enabled) {
      setNotice("语音未配置，无法开启常开监听", "warn");
      return;
    }
    setNotice("正在开启常开监听…");
    const ctx = await ensureAudioContext();
    if (!ctx) {
      setNotice("无法启用音频：浏览器不支持 AudioContext", "error");
      setVoiceMode("off");
      return;
    }
    const listener = await startAlwaysListener({
      // 不自动打断播报：扬声器回声会被 VAD 当起音，自动打断会把 TTS 掐断。
      // V1 抢话用界面「⏹ 停止」按钮；全双工引擎接入后再做真正的语音抢话。
      onSegment: (segment) => segmentHandlerRef.current(segment),
      onError: (message) => {
        setNotice(message, "error");
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
      setNotice(e instanceof Error ? `语音识别失败：${e.message}` : "语音识别失败", "error");
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
    if (!voiceLeaseOwned || !voiceStatus?.enabled || !voiceStatus.activation?.enabled) return;
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
  }, [voiceLeaseOwned, voiceStatus?.enabled, voiceStatus?.activation?.enabled, voiceStatus?.activation?.default_state]);

  useEffect(() => {
    if (voiceLeaseOwned) return;
    alwaysRef.current?.stop();
    alwaysRef.current = null;
    recorderRef.current?.cancel();
    recorderRef.current = null;
    setRecording(false);
    setVoiceMode("off");
  }, [voiceLeaseOwned]);

  return (
    <section className="bg-white border border-line rounded-xl flex flex-col h-[calc(100vh-180px)] overflow-hidden shadow-card">
      {/* Toolbar */}
      <div className="relative z-20 flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-4 py-3 border-b border-line text-xs text-muted">
        <div className="flex items-center gap-2 min-w-0">
          <button
            className="rounded-lg border border-line bg-white px-2.5 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors disabled:opacity-50"
            onClick={newConversation}
            disabled={busy}
          >
            新对话
          </button>
          <button
            className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
              showProjects ? "border-brand bg-brand-50 text-brand" : "border-line bg-white text-ink hover:border-brand hover:text-brand"
            }`}
            onClick={() => {
              setShowProjects((prev) => !prev);
              setShowHistory(false);
            }}
          >
            项目工程
          </button>
          <button
            className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
              showHistory ? "border-brand bg-brand-50 text-brand" : "border-line bg-white text-ink hover:border-brand hover:text-brand"
            }`}
            onClick={() => {
              setShowHistory((prev) => !prev);
              setShowProjects(false);
            }}
          >
            对话历史
          </button>
          {projectInput ? (
            <span className="inline-flex max-w-[220px] items-center gap-1 rounded-full bg-brand-50 px-2.5 py-1 text-brand">
              <span className="shrink-0">项目：</span>
              <span className="truncate" title={projectInput}>
                {projectName(projectInput)}
              </span>
              <button
                className="ml-1 shrink-0 text-brand hover:text-bad"
                onClick={() => void clearProject()}
                title="解除当前对话的项目绑定"
                type="button"
              >
                ×
              </button>
            </span>
          ) : (
            <span className="whitespace-nowrap text-muted">未绑定项目</span>
          )}
          <span className="whitespace-nowrap">本地保存 · {conversationId ? "当前会话" : "未开始会话"}</span>
        </div>
        <div className="flex items-center gap-2 min-w-0">
          <span className="shrink-0">当前模型</span>
          {modelProfiles.length > 0 ? (
            <ModelProfileSelect
              value={selectedProfileId}
              options={modelOptions}
              onChange={setSelectedProfileId}
              ariaLabel="选择当前模型"
              buttonClassName="h-8 max-w-[240px] text-xs"
              menuClassName="left-0 w-72 max-w-[calc(100vw-2rem)] sm:left-auto sm:right-0"
            />
          ) : (
            <button className="rounded-lg border border-warn/40 bg-warn-50 px-2.5 py-1 text-xs text-warn" onClick={onOpenSettings}>
              未配置模型，去设置
            </button>
          )}
          {modelProfiles.length > 0 && onOpenSettings ? (
            <button className="text-brand hover:underline whitespace-nowrap" onClick={onOpenSettings}>
              管理模型
            </button>
          ) : null}
        </div>
        {echoMode && (
          <span className="text-warn bg-warn-50 px-2.5 py-1 rounded-full font-medium">
            演示模式：未配置模型 API（echo）
          </span>
        )}
        {voiceStatus && !voiceStatus.enabled && (
          <span className="text-warn bg-warn-50 px-2.5 py-1 rounded-full font-medium">
            语音未配置：设置 DASHSCOPE_API_KEY 后重启
          </span>
        )}
      </div>

      {showProjects && (
        <div className="border-b border-line bg-surface-secondary/60 px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-ink">项目工程</span>
            <button
              className="rounded-lg border border-line bg-white px-2.5 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors"
              onClick={() => setProjectDraftOpen((prev) => !prev)}
            >
              {projectDraftOpen ? "取消新建" : "新建"}
            </button>
          </div>
          {projectDraftOpen && (
            <div className="flex flex-wrap items-end gap-2 mb-2 rounded-lg border border-line bg-white p-2.5">
              <label className="flex min-w-[160px] flex-1 flex-col gap-1 text-[11px] text-muted">
                项目名称
                <input
                  className="w-full rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs text-ink focus:outline-none focus:border-brand"
                  value={projectNameInput}
                  onChange={(e) => setProjectNameInput(e.target.value)}
                  placeholder="例如：DeskMate"
                />
              </label>
              <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-[11px] text-muted">
                项目文件夹
                <input
                  className="w-full rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs text-ink focus:outline-none focus:border-brand"
                  value={projectInput}
                  readOnly
                  placeholder="点击右侧选择文件夹"
                />
              </label>
              <button
                className="rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs text-ink hover:border-brand hover:text-brand transition-colors"
                onClick={() => void chooseProjectFolder()}
              >
                选择文件夹
              </button>
              <button
                className="rounded-lg bg-brand px-2.5 py-1.5 text-xs font-medium text-white hover:bg-brand-600 transition-colors disabled:opacity-50"
                onClick={createProjectConversation}
                disabled={busy}
              >
                创建并开新对话
              </button>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {projectConversations.length === 0 && !projectDraftOpen ? (
              <p className="text-xs text-muted">暂无项目；点「新建」创建第一个项目。</p>
            ) : null}
            {projectConversations.map((project) => (
              <button
                key={project.path}
                className="rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs text-ink hover:border-brand hover:text-brand transition-colors"
                onClick={() => void openProject(project.path)}
              >
                {project.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {showHistory && (
        <div className="border-b border-line bg-surface-secondary/60 px-4 py-3 max-h-80 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-ink">历史对话</span>
            <button className="text-xs text-muted hover:text-ink transition-colors" onClick={() => setShowHistory(false)}>关闭</button>
          </div>
          {conversations.length === 0 && (
            <p className="text-xs text-muted">暂无历史对话</p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {[
              { title: "项目对话", items: conversations.filter((item) => item.project) },
              { title: "普通对话", items: conversations.filter((item) => !item.project) },
            ].map((group) => (
              <div key={group.title}>
                <p className="text-[11px] font-medium text-muted mb-1">{group.title} · {group.items.length}</p>
                <div className="flex flex-col gap-1">
                  {group.items.map((item) => (
                    <button
                      key={item.conversation_id}
                      className={`text-left rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                        item.conversation_id === conversationId
                          ? "border-brand bg-brand-50 text-brand"
                          : "border-line bg-white text-ink hover:border-brand"
                      }`}
                      onClick={() => void openConversation(item.conversation_id)}
                    >
                      <span className="block truncate">{item.title || "新对话"}</span>
                      <span className="block text-[10px] text-muted mt-0.5">
                        {item.message_count} 条 · {fmtChatTime(item.updated_at)}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Voice mode bar */}
      {voiceStatus?.enabled && voiceStatus.activation?.enabled && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-line-subtle">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
            voiceMode === "listening"
              ? "bg-ok-50 text-ok"
              : voiceMode === "sleeping"
                ? "bg-line-subtle text-muted"
                : "bg-surface-secondary text-muted"
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${
              voiceMode === "listening"
                ? "bg-ok animate-breathe"
                : voiceMode === "sleeping"
                  ? "bg-muted"
                  : "bg-line"
            }`} />
            {voiceMode === "listening"
              ? "聆听中"
              : voiceMode === "sleeping"
                ? "静默中"
                : "常开已关闭"}
          </span>
          <span className="text-xs text-muted whitespace-nowrap">唤醒词：你好，{personaName}</span>
          <button className="border border-line bg-white rounded-lg px-2.5 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors whitespace-nowrap" onClick={toggleAlwaysListen}>
            {voiceMode === "off" ? "常开：关" : "常开：开"}
          </button>
          <button className="border border-line bg-white rounded-lg px-2.5 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors whitespace-nowrap" onClick={forceSilence}>
            静默
          </button>
          <button className="border border-line bg-white rounded-lg px-2.5 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors whitespace-nowrap" onClick={forceWake}>
            唤醒
          </button>
        </div>
      )}

      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4 scroll-thin">
        {messages.length === 0 && (
          <div className="m-auto w-full max-w-md border border-dashed border-line rounded-xl p-6 text-center text-sm text-muted">
            输入任意内容开始对话。
            {echoMode && (
              <>
                <br />
                提示：以「长回复」开头可体验自动展开主界面。
              </>
            )}
          </div>
        )}
        {/* 待授权卡片在消息流末尾，见 bottomRef 前 */}
        {messages.map((m, i) => (
          <div key={`${m.role}-${i}`} className={`flex flex-col max-w-[78%] min-w-0 ${m.role === "user" ? "self-end items-end" : "self-start"}`}>
            <span className="text-[11px] text-muted mb-1 select-none" title={m.created_at}>
              {m.role === "user" ? "你" : m.role === "tool" ? "任务" : speakerName}
              {m.created_at ? ` · ${fmtChatTime(m.created_at)}` : ""}
            </span>
            <div className={`break-words break-anywhere min-w-0 px-3.5 py-2.5 text-sm leading-relaxed ${
              m.role === "user"
                ? "bg-brand text-white rounded-xl rounded-br-sm"
                : m.role === "tool"
                  ? "bg-surface-secondary border border-line text-ink rounded-xl rounded-bl-sm"
                  : "bg-surface-chat text-ink rounded-xl rounded-bl-sm"
            }`}>
              {m.content ? (
                m.role === "user" ? (
                  m.content
                ) : (
                  <MarkdownLite text={m.content} collapsible={m.content.length > 1400} />
                )
              ) : (
                <span className="text-muted animate-typing">思考中…</span>
              )}
            </div>
            {m.role === "assistant" && m.skill_id && (
              <span className="self-start mt-1 text-[10px] text-brand bg-brand-50 rounded-full px-2 py-0.5">
                技能 · {m.skill_id}
              </span>
            )}
            {m.role === "assistant" && m.content && voiceStatus?.enabled && (
              <button
                className="border border-line bg-white rounded-lg px-2 py-1 text-xs text-ink hover:border-brand hover:text-brand transition-colors self-start mt-1.5"
                onClick={() => {
                  stopSpeaking();
                  void speak(m.content.length > 1900 ? `${m.content.slice(0, 1900)}…` : m.content);
                }}
                title="播报这段回复"
              >
                <Volume2 size={12} strokeWidth={2} className="inline mr-1 -mt-0.5" />
                播报
              </button>
            )}
          </div>
        ))}
        {awaitingRuns.filter((run) => run.status === "awaiting_approval").map((run) => (
          <div
            key={run.run_id}
            className="self-start flex flex-col gap-2 max-w-[78%] min-w-0 rounded-xl rounded-bl-sm border border-warn/40 bg-warn-50 px-3.5 py-2.5"
          >
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-warn">
              <span className="w-1.5 h-1.5 rounded-full bg-warn animate-pulse" />
              等待授权
            </span>
            <p className="text-sm text-ink break-anywhere">
              {run.progress || `${run.executor} · ${run.mode}`}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                className="rounded-md border border-ok-50 bg-ok-50 px-2.5 py-1 text-xs text-ok transition-opacity hover:opacity-80"
                onClick={() => void decideRunById(run.run_id, "approved")}
                type="button"
              >
                批准
              </button>
              <button
                className="rounded-md border border-bad-50 bg-bad-50 px-2.5 py-1 text-xs text-bad transition-opacity hover:opacity-80"
                onClick={() => void decideRunById(run.run_id, "rejected")}
                type="button"
              >
                拒绝
              </button>
            </div>
          </div>
        ))}
        {toolApproval && (
          <div className="self-start flex flex-col gap-2 max-w-[78%] min-w-0 rounded-xl rounded-bl-sm border border-warn/40 bg-warn-50 px-3.5 py-2.5">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-warn">
              <span className="w-1.5 h-1.5 rounded-full bg-warn animate-pulse" />
              工具调用等待授权
            </span>
            <p className="text-sm text-ink break-anywhere">
              {toolApproval.server}.{toolApproval.tool}
            </p>
            {toolApproval.arguments && (
              <p className="text-xs text-muted break-anywhere font-mono">
                {toolApproval.arguments}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                className="rounded-md border border-ok-50 bg-ok-50 px-2.5 py-1 text-xs text-ok transition-opacity hover:opacity-80"
                onClick={() => void decideToolApprovalById(toolApproval.approval_id, "approved")}
                type="button"
              >
                批准
              </button>
              <button
                className="rounded-md border border-bad-50 bg-bad-50 px-2.5 py-1 text-xs text-bad transition-opacity hover:opacity-80"
                onClick={() => void decideToolApprovalById(toolApproval.approval_id, "rejected")}
                type="button"
              >
                拒绝
              </button>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {notice && (
        <div
          className={`px-4 py-2 text-xs ${NOTICE_STYLE[noticeKind]}`}
          role={noticeKind === "error" ? "alert" : "status"}
        >
          {notice}
        </div>
      )}

      {/* 记忆写入气泡（ponytail：简单 toast，5s 自动消失） */}
      {memoryBubble && (
        <div className="px-4 py-2 text-xs bg-blue-50 text-blue-700 border-t border-blue-200 transition-opacity">
          <Save size={12} className="inline mr-1 -mt-0.5" />
          {memoryBubble}
        </div>
      )}

      {backgroundRuns.some((run) => run.conversation_id !== conversationId) && (
        <div className="border-t border-line-subtle px-4 py-2.5 space-y-2">
          <div className="text-xs font-semibold text-ink">其他后台任务</div>
          {backgroundRuns
            .filter((run) => run.conversation_id !== conversationId)
            .map((run) => {
              const project = run.project ? run.project.split(/[/\\]/).pop() : "普通对话";
              const awaiting = run.status === "awaiting_approval";
              return (
                <div key={run.run_id} className="flex flex-wrap items-center gap-2 text-xs">
                  <span className={`h-1.5 w-1.5 rounded-full ${awaiting ? "bg-warn" : "bg-brand animate-breathe"}`} />
                  <span className="text-muted">{project}</span>
                  <span className="min-w-0 flex-1 truncate text-ink" title={run.task_input}>
                    {run.task_input || "后台任务"}
                  </span>
                  {awaiting ? (
                    <>
                      <button
                        className="text-ok hover:underline"
                        onClick={() => void decideRunById(run.run_id, "approved")}
                        type="button"
                      >
                        批准
                      </button>
                      <button
                        className="text-bad hover:underline"
                        onClick={() => void decideRunById(run.run_id, "rejected")}
                        type="button"
                      >
                        拒绝
                      </button>
                    </>
                  ) : (
                    <button
                      className="text-muted hover:text-bad"
                      onClick={() => void cancelBackgroundRun(run.run_id)}
                      type="button"
                    >
                      取消
                    </button>
                  )}
                </div>
              );
            })}
        </div>
      )}

      {/* 后台任务实时状态：仅进行中；待授权已升级为消息流卡片 */}
      {liveTask && liveTask.status === "running" && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-t border-line-subtle text-xs">
          <span
            className="inline-flex items-center gap-1.5 font-medium text-brand"
          >
            <span
              className="w-1.5 h-1.5 rounded-full bg-brand animate-breathe"
            />
            后台执行中：{liveTask.text}
          </span>
        </div>
      )}

      {/* Input row */}
      <div className="flex items-end gap-2.5 p-3 border-t border-line">
        <button
          className={`h-[46px] min-w-[46px] px-2.5 rounded-xl border text-lg transition-colors ${
            recording
              ? "bg-bad text-white border-bad animate-typing"
              : "bg-white border-line hover:border-brand"
          } disabled:opacity-50 disabled:cursor-default`}
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
          {recording ? (
            <Square size={18} strokeWidth={2.2} fill="currentColor" />
          ) : (
            <Mic size={18} strokeWidth={2} />
          )}
        </button>
        {speaking && (
          <button className="h-[46px] px-3.5 rounded-xl border border-bad text-bad text-sm hover:bg-bad-50 transition-colors" onClick={stopSpeaking} title="停止播报（打断）">
            <Square size={13} strokeWidth={2.2} fill="currentColor" className="inline mr-1.5 -mt-0.5" />
            停止
          </button>
        )}
        <button
          type="button"
          className="h-[46px] min-w-[46px] px-2.5 rounded-xl border border-line bg-white hover:border-brand transition-colors disabled:opacity-50 disabled:cursor-default"
          onClick={() => fileInputRef.current?.click()}
          disabled={busy || uploadingFiles}
          title="添加附件（Excel / Word / PPT / PDF / 图片）"
        >
          {uploadingFiles ? (
            <LoaderCircle size={18} className="animate-spin" />
          ) : (
            <Paperclip size={18} strokeWidth={2} />
          )}
        </button>
        <div className="flex-1 min-w-0 flex flex-col gap-1.5">
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {attachments.map((attachment) => (
                <span key={attachment.path} className="inline-flex items-center gap-1 rounded-lg bg-surface-secondary px-2 py-1 text-xs text-ink max-w-[220px]">
                  <span className="truncate">{attachment.name}</span>
                  <button
                    type="button"
                    className="text-muted hover:text-bad"
                    onClick={() => removeAttachment(attachment.path)}
                    title="移除附件"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-1 text-xs text-muted">
            <span className="whitespace-nowrap">记忆</span>
            {CHAT_MODES.map((item) => (
              <button
                key={item.mode}
                type="button"
                title={`记忆深度：${item.hint}`}
                aria-label={`记忆深度：${item.hint}`}
                onClick={() => setChatMode(item.mode)}
                className={`rounded-md border px-1.5 py-0.5 transition-colors ${
                  chatMode === item.mode
                    ? "border-brand bg-brand-50 text-brand"
                    : "border-line bg-white text-muted hover:border-brand hover:text-brand"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <textarea
            className="w-full flex-1 min-h-[52px] max-h-[140px] resize-none rounded-xl border border-line px-3.5 py-2.5 text-sm leading-relaxed focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20 disabled:opacity-60"
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
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".xlsx,.xls,.docx,.doc,.pptx,.ppt,.pdf,.txt,.csv,.md,.png,.jpg,.jpeg"
          className="hidden"
          onChange={(e) => void handleFilesPicked(e.target.files)}
        />
        <button className="h-[46px] px-5 rounded-xl bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-50 disabled:cursor-default" onClick={send} disabled={busy || !input.trim()}>
          发送
        </button>
      </div>
    </section>
  );
}
