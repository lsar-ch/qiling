import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { currentMonitor, getCurrentWindow } from "@tauri-apps/api/window";
import {
  apiVoiceIntent,
  connectEvents,
  eventToState,
  fetchActivePersonaAsset,
  fetchPersonaAssetManifest,
  fetchVoiceStatus,
  acquireVoiceLease,
  personaAssetUrl,
  releaseVoiceLease,
  recognizeSpeech,
  SERVICE_BASE,
  streamChat,
  synthesizeSpeechStream,
  type ExpressionEmotion,
  type ExpressionEvent,
  type InteractionKind,
  type MotionFamily,
  type PersonaAssetMetrics,
  type PersonaLayer,
  type PersonaSpriteSheet,
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
import { lipSyncBus } from "../widget/lipSync";
import {
  pickAction,
  triggerFor,
  smoothTransition,
  TRANSITION_MS,
  setMotionOverrides,
  type ActionSelection,
  type ActionTrigger,
} from "../widget/actions";
import { attachMouseFollow, detachMouseFollow } from "../widget/mouseFollow";
import { attachBeatDetect, detachBeatDetect } from "../widget/beatDetect";
import {
  advanceDrive,
  clampWeight,
  createDriveState,
  driveWeightMultiplier,
  noteStateChange,
  type DriveState,
} from "../widget/internalState";


// Phase 4: 时间感知 - 根据时间段调整待机动作权重
type TimePeriod = "morning" | "afternoon" | "evening" | "night";

function getTimePeriod(): TimePeriod {
  const hour = new Date().getHours();
  if (hour >= 6 && hour < 12) return "morning";
  if (hour >= 12 && hour < 18) return "afternoon";
  if (hour >= 18 && hour < 23) return "evening";
  return "night";
}

/**
 * 上下文权重：时间段 + 内在驱动。收在一处，避免两套乘数各算各的。
 * 内在驱动只在低优先级动作（idle/hover/click）上生效，任务类动作权重不受影响；
 * 结果统一夹在 [0.5, 3]，防刷仍由动作表里的 cooldownMs 负责。
 */
function getContextWeightMultiplier(
  actionId: string,
  timePeriod: TimePeriod,
  drive: DriveState,
  lowPriority: boolean,
): number {
  let multiplier = 1;
  if (timePeriod === "night" && actionId.includes("yawn")) {
    multiplier *= 2.0; // 深夜更容易打哈欠
  } else if (timePeriod === "morning" && actionId.includes("glance")) {
    multiplier *= 2.0; // 早晨更容易左右看看
  }
  if (lowPriority) {
    multiplier *= driveWeightMultiplier(actionId, drive);
  }
  return clampWeight(multiplier);
}

// three 依赖较重（~600KB），仅 VRM persona 才动态加载
const VrmStage = lazy(() => import("../widget/VrmStage"));

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

const ERROR_STATES = new Set<WidgetState>(["interrupted"]);

type VoiceMode = "off" | "starting" | "listening" | "sleeping";

// 情绪衰减：先满强度停留 holdMs，再进入 fading 淡化 fadeMs，最后回落 neutral。
// 覆盖全部非 neutral 情绪——thinking / confused 的动画是 infinite，
// 原先没有停留时长会一直浮动，状态回到 idle 也停不下来。
const EMOTION_DECAY_MS: Record<Exclude<ExpressionEmotion, "neutral">, { holdMs: number; fadeMs: number }> = {
  attentive: { holdMs: 1100, fadeMs: 600 },
  thinking: { holdMs: 1800, fadeMs: 900 },
  confused: { holdMs: 2400, fadeMs: 900 },
  success: { holdMs: 1900, fadeMs: 800 },
  error: { holdMs: 1400, fadeMs: 900 },
  happy: { holdMs: 1900, fadeMs: 800 },
  sad: { holdMs: 1700, fadeMs: 1000 },
  surprised: { holdMs: 1200, fadeMs: 600 },
};

// 这三个情绪同时也是某个持续状态的视觉代理：状态还在就续期，别让长任务中途动画消失。
const EMOTION_STATE_PAIR: Partial<Record<ExpressionEmotion, WidgetState>> = {
  attentive: "listening",
  thinking: "thinking",
  confused: "awaiting_approval",
};

type WidgetPreferences = {
  x: number | null;
  y: number | null;
  monitor: string | null;
  autoHide: boolean;
  scale: number;
  /** 贴在上边缘且平台不允许窗口越过工作区顶部时为 "top"，角色需在窗口内上移。 */
  hiddenEdge?: string | null;
};

type DragStart = {
  pointerId: number;
  x: number;
  y: number;
};

/** 挂件窗口逻辑坐标（CSS px）下的矩形。 */
type InteractiveBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

function normText(text: string): string {
  return text.replace(/[\s，。！？、,.!?'"“”‘’；：:;…—\-()（）【】《》~～·]/g, "").toLowerCase();
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
// 贴边隐藏后角色仍需露在屏幕内的「抓手」宽度（逻辑像素），按角色实际内容尺寸等比推算。
const WIDGET_HIDE_HANDLE_MIN = 64;
const WIDGET_HIDE_HANDLE_MAX = 140;
const WIDGET_HIDE_HANDLE_RATIO = 0.34;
// 判定鼠标是否落在挂件可交互区域时给的额外容差，便于隐藏后把角色拖回来。
const WIDGET_INTERACTIVE_PADDING = 16;
// 同一轮对话里 submitText 与 conversation.completed 都会要求展开主界面，去重窗口。
const MAIN_UI_AUTO_DEDUPE_MS = 2000;
// 交互模式调整空闲动作节奏：casual 更活跃、work 更克制、project 居中。
const INTERACTION_RHYTHM: Record<InteractionKind, number> = {
  work: 1.2,
  casual: 0.8,
  project: 1.0,
};

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

function FramedLayer({
  personaId,
  layer,
  trigger,
  state,
}: {
  personaId: string;
  layer: PersonaLayer;
  trigger: ActionTrigger;
  state: WidgetState;
}) {
  const [index, setIndex] = useState(0);
  const frameSet = layer.frames?.[trigger] ?? layer.frames?.[state];
  const fps = layer.frame_fps?.[trigger] ?? layer.frame_fps?.[state] ?? 8;
  useEffect(() => {
    if (!frameSet || frameSet.length <= 1) return;
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % frameSet.length);
    }, Math.max(50, Math.round(1000 / fps)));
    return () => window.clearInterval(timer);
  }, [frameSet, fps]);
  return (
    <img
      className={`mascot-layer ${layer.role ? `role-${layer.role}` : "role-static"}`}
      src={personaAssetUrl(personaId, frameSet?.[index] ?? layer.file)}
      alt=""
      draggable={false}
      style={{ zIndex: layer.z }}
    />
  );
}

function SpriteSheetStage({
  personaId,
  sheet,
}: {
  personaId: string;
  sheet: PersonaSpriteSheet;
}) {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setFrame((current) => (current + 1) % sheet.frames);
    }, Math.max(50, Math.round(1000 / sheet.fps)));
    return () => window.clearInterval(timer);
  }, [sheet.file, sheet.frames, sheet.fps]);
  const aspect = sheet.frame_height > 0 ? sheet.frame_width / sheet.frame_height : 1;
  return (
    <div
      className="mascot-sprite"
      style={{
        width: `calc(var(--mascot-size) * ${aspect})`,
        height: "var(--mascot-size)",
      }}
    >
      <img
        src={personaAssetUrl(personaId, sheet.file)}
        alt=""
        draggable={false}
        style={{
          display: "block",
          height: "100%",
          width: "auto",
          maxWidth: "none",
          transform: `translateX(-${(frame / sheet.frames) * 100}%)`,
        }}
      />
    </div>
  );
}

export default function Widget() {
  const [state, setState] = useState<WidgetState>("idle");
  const stateRef = useRef<WidgetState>("idle");
  const [emotion, setEmotion] = useState<ExpressionEmotion>("neutral");
  const [emotionDecaying, setEmotionDecaying] = useState(false);
  const [action, setAction] = useState<ActionSelection | null>(null);
  const [motionFamily, setMotionFamily] = useState<MotionFamily>("human");
  const [idleActionIntervalMs, setIdleActionIntervalMs] = useState(8000);
  const [transitionMs, setTransitionMs] = useState(TRANSITION_MS);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [interactionKind, setInteractionKind] = useState<InteractionKind>("casual");
  const [layers, setLayers] = useState<PersonaLayer[] | null>(null);
  const [spritesheets, setSpritesheets] = useState<PersonaSpriteSheet[]>([]);
  const [layersPersonaId, setLayersPersonaId] = useState<string | null>(null);
  // 当前角色走 VRM：avatar 是 T-pose 占位图，不能用它当立绘显示
  const [vrmDriven, setVrmDriven] = useState(false);
  // VRM 一次性反馈动作（点击/悬停）：seq 递增触发重播，不参与状态机
  const [vrmOneShot, setVrmOneShot] = useState<{ trigger: ActionTrigger; seq: number } | null>(null);
  const oneShotSeqRef = useRef(0);
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
  const [assetMetrics, setAssetMetrics] = useState<PersonaAssetMetrics | null>(null);
  const [preferences, setPreferences] = useState<WidgetPreferences>({
    x: null,
    y: null,
    monitor: null,
    autoHide: true,
    scale: 1,
  });
  /** 上边缘隐藏时角色要上移的像素（窗口逻辑坐标）。 */
  const [topPeekOffset, setTopPeekOffset] = useState(0);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const bubbleRef = useRef<HTMLDivElement | null>(null);
  const bubbleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emotionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emotionFadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const driveRef = useRef<DriveState>(createDriveState());
  const driveLastStateRef = useRef<WidgetState>("idle");
  const actionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playedActionsRef = useRef<Record<string, number>>({});
  const actionActiveRef = useRef(false);
  const actionLowRef = useRef(false);
  const motionFamilyRef = useRef<MotionFamily>("human");
  const projectRef = useRef<string | null>(null);
  const layersLoadedRef = useRef<string | null>(null);
  const resizeRafRef = useRef<number | null>(null);
  const persistentHintRef = useRef("");
  const conversationIdRef = useRef<string | null>(null);
  const busyRef = useRef(false);
  const alwaysRef = useRef<AlwaysListener | null>(null);
  const segmentHandlerRef = useRef<(segment: AlwaysListenSegment) => void>(() => {});
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playbackRef = useRef<AudioBufferSourceNode | null>(null);
  const playbackAbortRef = useRef<AbortController | null>(null);
  const speakingRef = useRef(false);
  const announceQueueRef = useRef<string[]>([]);
  const announceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const announceActiveRef = useRef(false);
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
  const stageRef = useRef<HTMLDivElement | null>(null);
  const mascotRef = useRef<HTMLImageElement | null>(null);
  const ctxMenuRef = useRef<HTMLDivElement | null>(null);
  const mainUiOpenedAtRef = useRef(0);
  const leaseOwnerEventRef = useRef<(owner: string | null) => void>(() => {});
  // 供 window.resize 监听拿到最新一版同步函数（闭包里要用最新的 assetMetrics）。
  const syncOverlayRef = useRef<() => void>(() => {});

  stateRef.current = state;
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

  useEffect(() => {
    motionFamilyRef.current = motionFamily;
  }, [motionFamily]);

  // Phase 1: 鼠标视线跟随
  useEffect(() => {
    attachMouseFollow();
    return () => detachMouseFollow();
  }, []);

  // Phase 5: 音乐感知→节奏动画
  useEffect(() => {
    attachBeatDetect();
    return () => detachBeatDetect();
  }, []);

  // Step C: 统一动作播放；低优先级（idle/hover/click）不打断状态动作
  const playTrigger = useCallback((trigger: ActionTrigger): void => {
    const now = Date.now();
    const low = trigger === "idle" || trigger === "hover" || trigger === "click";
    if (actionActiveRef.current) {
      if (low && !actionLowRef.current) return;
      if (trigger === "idle") return;
    }
    // Phase 4: 传入时间段；内在驱动只调制空闲类动作（low），任务类动作权重不变
    const timePeriod = getTimePeriod();
    const selection = pickAction(
      motionFamilyRef.current,
      trigger,
      playedActionsRef.current,
      now,
      undefined,
      (actionId) => getContextWeightMultiplier(actionId, timePeriod, driveRef.current, low),
    );
    if (!selection) return;
    playedActionsRef.current[selection.id] = now;
    actionActiveRef.current = true;
    actionLowRef.current = low;

    // Phase 2: 动画过渡平滑 - 先回中性位，再设置新动作
    const hasCurrentAction = action !== null && action.className !== "";
    if (hasCurrentAction) {
      setAction(null); // 进入中性位
      setTimeout(() => {
        setAction(selection);
        if (actionTimerRef.current) clearTimeout(actionTimerRef.current);
        actionTimerRef.current = setTimeout(() => {
          actionActiveRef.current = false;
          actionLowRef.current = false;
          setAction((current) => (current?.id === selection.id ? null : current));
        }, selection.durationMs);
      }, transitionMs);
    } else {
      setAction(selection);
      if (actionTimerRef.current) clearTimeout(actionTimerRef.current);
      actionTimerRef.current = setTimeout(() => {
        actionActiveRef.current = false;
        actionLowRef.current = false;
        setAction((current) => (current?.id === selection.id ? null : current));
      }, selection.durationMs);
    }
  }, [action, transitionMs]);

  /**
   * VRM 一次性反馈动作：仅空闲、非播报时推给 3D。
   * 播报中点击=打断语音，不该顺带做动作；非空闲态（思考/执行）不加花。
   */
  const vrmOneShotFeedback = useCallback((trigger: ActionTrigger): void => {
    if (trigger !== "click" && trigger !== "hover") return;
    if (speakingRef.current) return;
    if (trigger === "click" && stateRef.current !== "idle") return;
    oneShotSeqRef.current += 1;
    setVrmOneShot({ trigger, seq: oneShotSeqRef.current });
  }, []);

  // 分层资产：每个 persona 只加载一次，失败或缺失时回退单图
  const loadLayersFor = useCallback((personaId: string): void => {
    if (!personaId || layersLoadedRef.current === personaId) return;
    layersLoadedRef.current = personaId;
    setLayers(null);
    setSpritesheets([]);
    setLayersPersonaId(personaId);
    void fetchPersonaAssetManifest(personaId)
      .then((manifest) => {
        setLayers(manifest.layers);
        setSpritesheets(manifest.spritesheets);
      })
      .catch(() => {
        setLayers(null);
        setSpritesheets([]);
      });
  }, []);

  // 状态/情绪变化触发动作
  useEffect(() => {
    playTrigger(triggerFor(state, emotion));
  }, [emotion, motionFamily, playTrigger, state]);

  // 内在驱动：状态切换的瞬时效应（开始互动清零无聊，任务完成回一点精力）
  useEffect(() => {
    noteStateChange(driveRef.current, driveLastStateRef.current, state);
    driveLastStateRef.current = state;
  }, [state]);

  // 内在驱动：按真实经过时间缓慢推进，定时器被节流也不会算错
  useEffect(() => {
    let last = Date.now();
    const timer = window.setInterval(() => {
      const now = Date.now();
      advanceDrive(driveRef.current, now - last, stateRef.current);
      last = now;
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  // 空闲调度器：只在 idle 且无动作时播放，间隔按 presentation 配置加随机抖动
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = (): void => {
      if (!disposed && state === "idle" && !actionActiveRef.current && !document.hidden) {
        playTrigger("idle");
      }
      timer = setTimeout(
        tick,
        idleActionIntervalMs * INTERACTION_RHYTHM[interactionKind] * (0.8 + Math.random() * 0.4),
      );
    };
    timer = setTimeout(
      tick,
      idleActionIntervalMs * INTERACTION_RHYTHM[interactionKind] * (0.8 + Math.random() * 0.4),
    );
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
  }, [idleActionIntervalMs, interactionKind, playTrigger, state]);

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

  /** 设置情绪；停留期满后先进入 fading 淡化，再回落 neutral。 */
  const applyEmotion = (next: ExpressionEmotion): void => {
    if (emotionTimerRef.current) {
      window.clearTimeout(emotionTimerRef.current);
      emotionTimerRef.current = null;
    }
    if (emotionFadeTimerRef.current) {
      window.clearTimeout(emotionFadeTimerRef.current);
      emotionFadeTimerRef.current = null;
    }
    setEmotionDecaying(false);
    setEmotion(next);
    if (next === "neutral") return;

    const decay = EMOTION_DECAY_MS[next];
    emotionTimerRef.current = window.setTimeout(() => {
      emotionTimerRef.current = null;
      if (EMOTION_STATE_PAIR[next] === stateRef.current) {
        applyEmotion(next); // 状态仍在，续期
        return;
      }
      setEmotionDecaying(true);
      emotionFadeTimerRef.current = window.setTimeout(() => {
        emotionFadeTimerRef.current = null;
        setEmotionDecaying(false);
        setEmotion("neutral");
      }, decay.fadeMs);
    }, decay.holdMs);
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

  const openMainUi = async (page?: string): Promise<void> => {
    try {
      await invoke("open_main_ui", { page: page ?? null });
      showBrief("已打开主界面", 2000);
    } catch (err) {
      const detail =
        typeof err === "string"
          ? err
          : err instanceof Error
            ? err.message
            : "未知错误";
      showBrief(`打开主界面失败：${detail}`, 4000);
    }
  };

  /**
   * 自动展开（长回复落地到对话页）会同时从 submitText 和 conversation.completed
   * 两条路径触发，过去一轮对话会开出两个标签页 —— 这里按时间窗去重。
   */
  const openMainUiAuto = (page?: string): void => {
    const now = Date.now();
    if (now - mainUiOpenedAtRef.current < MAIN_UI_AUTO_DEDUPE_MS) return;
    mainUiOpenedAtRef.current = now;
    void openMainUi(page);
  };

  /** 用户主动打开（双击 / 右键菜单）：始终放行，并占用去重窗口避免紧接着再自动弹一次。 */
  const openMainUiManual = (page?: string): void => {
    mainUiOpenedAtRef.current = Date.now();
    void openMainUi(page);
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
    playbackAbortRef.current?.abort();
    playbackAbortRef.current = null;
    playbackRef.current?.stop();
    playbackRef.current = null;
    speakingRef.current = false;
    speakEndAtRef.current = Date.now();
    setSpeaking(false);
  };

  /** 播放单个音频 Blob；返回 Promise 在当前块播放结束后 resolve。barge-in 由 playbackRef 停止。 */
  const _playAudioBlob = async (ctx: AudioContext, blob: Blob): Promise<void> => {
    const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    // 口型同步取数点：source → analyser → destination（对 2D 路径无副作用）
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0;
    source.connect(analyser);
    analyser.connect(ctx.destination);
    lipSyncBus.analyser = analyser;
    playbackRef.current = source;
    return new Promise<void>((resolve) => {
      source.onended = () => {
        if (playbackRef.current === source) playbackRef.current = null;
        if (lipSyncBus.analyser === analyser) lipSyncBus.analyser = null;
        resolve();
      };
      source.start();
    });
  };

  /** 任务事件短播报：2s 内多条合并成一句，不占语音租约、不打断正在朗读的回复。 */
  const playTts = (text: string, emotion?: ExpressionEmotion): void => {
    if (!voiceStatusRef.current?.auto_speak) return;
    announceQueueRef.current.push(text);
    if (emotion && emotion !== "neutral") {
      applyEmotion(emotion);
    }
    if (announceTimerRef.current) window.clearTimeout(announceTimerRef.current);
    announceTimerRef.current = window.setTimeout(() => void flushAnnouncements(), 2000);
  };

  const flushAnnouncements = async (): Promise<void> => {
    if (announceActiveRef.current) return;
    if (speakingRef.current) {
      announceTimerRef.current = window.setTimeout(() => void flushAnnouncements(), 1200);
      return;
    }
    const items = announceQueueRef.current.splice(0);
    if (!items.length) return;
    announceActiveRef.current = true;
    try {
      await playTtsOnce(items.join("，"));
    } finally {
      announceActiveRef.current = false;
      if (announceQueueRef.current.length) void flushAnnouncements();
    }
  };

  const playTtsOnce = async (text: string, emotion?: ExpressionEmotion): Promise<void> => {
    const ctx = await ensureAudioContext();
    if (!ctx) return;
    const abort = new AbortController();
    playbackAbortRef.current = abort;
    const startedAt = performance.now();
    let firstChunk = true;
    try {
      const stream = await synthesizeSpeechStream(text, "widget", abort.signal, emotion);
      for await (const chunk of stream) {
        if (abort.signal.aborted) break;
        if (firstChunk) {
          firstChunk = false;
          if (import.meta.env.DEV) console.info("[widget-tts] first chunk ms:", Math.round(performance.now() - startedAt));
        }
        await _playAudioBlob(ctx, chunk.audio);
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        /* TTS 不可用时静默，保留视觉提醒 */
      }
    } finally {
      if (playbackAbortRef.current === abort) playbackAbortRef.current = null;
    }
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

  const speak = async (text: string, emotion?: ExpressionEmotion): Promise<void> => {
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
    const abort = new AbortController();
    playbackAbortRef.current = abort;
    const startedAt = performance.now();
    let firstChunk = true;

    try {
      const stream = await synthesizeSpeechStream(
        text.length > 1900 ? `${text.slice(0, 1900)}…` : text,
        "widget",
        abort.signal,
        emotion,
      );
      for await (const chunk of stream) {
        if (!speakingRef.current) break;
        if (firstChunk) {
          firstChunk = false;
          if (import.meta.env.DEV) console.info("[widget-tts] first chunk ms:", Math.round(performance.now() - startedAt));
        }
        await _playAudioBlob(ctx, chunk.audio);
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        /* TTS 不可用或供应商失败时静默，气泡仍保留 */
      }
    } finally {
      if (playbackAbortRef.current === abort) playbackAbortRef.current = null;
      playbackRef.current = null;
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
      // 长回复只把摘要放进气泡并朗读，全文交给对话页。早先这里跳过气泡，
      // 挂件会一直停在「正在思考…」并且一句话都不播报。
      showBrief(done.short ? done.message || done.speak_text : done.speak_text || done.message);
      if (done.emotion && done.emotion !== "neutral") applyEmotion(done.emotion);
      if (speakReply && voiceStatusRef.current?.enabled && voiceStatusRef.current.auto_speak) {
        stopSpeaking();
        void speak(done.speak_text || done.message, done.emotion);
      }
      if (!done.short) {
        // 长回复直接落到对话页，用户不用再手点一次
        openMainUiAuto("chat");
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
    if (announceTimerRef.current) {
      window.clearTimeout(announceTimerRef.current);
      announceTimerRef.current = null;
    }
    announceQueueRef.current = [];
    const listener = alwaysRef.current;
    alwaysRef.current = null;
    if (listener) listener.stop();
    playbackRef.current?.stop();
    playbackRef.current = null;
  };

  /** 只关麦克风（owner 被主页抢走时）：不打断正在播放的播报。 */
  const stopMicOnly = (): void => {
    const listener = alwaysRef.current;
    alwaysRef.current = null;
    if (listener) listener.stop();
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
    } catch (error) {
      const message = error instanceof Error ? error.message : "语音识别失败";
      if (!message.includes("未识别到有效语音内容")) {
        showBrief(`语音识别失败：${message}`, 5000);
      }
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
        setVrmDriven(asset.vrm);
        setPresentation((current) => current ? { ...current, style: asset.style, motion_family: asset.motion_family ?? asset.style } : current);
        setMotionFamily(asset.motion_family ?? asset.style);
        loadLayersFor(asset.personaId);
        setAssetMetrics({
          personaId: asset.personaId,
          canvasWidth: asset.canvasWidth,
          canvasHeight: asset.canvasHeight,
          contentBbox: asset.contentBbox,
        });
      })
      .catch(() => {
        /* WebSocket 的 persona.presentation 仍会提供角色资产 */
      });
    const wsUrl = "ws://127.0.0.1:8736/api/events";

    const onMsg = (msg: WsMessage) => {
      if (!alive) return;
      if (msg.event_type === "voice.lease.changed") {
        const owner = (msg.payload?.owner as string | null | undefined) ?? null;
        leaseOwnerEventRef.current(owner);
        return;
      }
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

      // 主动提醒：久坐/长工作/备忘录/任务，不进状态机，只气泡+语音
      if (msg.event_type === "reminder.triggered") {
        const bubble = typeof msg.payload?.bubble === "string" ? msg.payload.bubble : "";
        const speakText = typeof msg.payload?.speak_text === "string" ? msg.payload.speak_text : bubble;
        if (bubble) {
          showBrief(bubble, 8000);
          void playTts(speakText || bubble, "attentive");
        }
        return;
      }

      // T3 主动监督：阻塞/里程碑/无进展提醒，不进状态机，只气泡+语音
      if (
        msg.event_type === "project.blocked" ||
        msg.event_type === "project.milestone" ||
        msg.event_type === "task.stale"
      ) {
        const text = typeof msg.payload?.bubble === "string" ? msg.payload.bubble : "";
        if (text) {
          showBrief(text, 6000);
          void playTts(text);
        }
        return;
      }

      const next = eventToState(msg.event_type);
      if (!next) {
        // D 步：task.classified 带 interaction_kind 与 project，作为挂件项目上下文单通道
        if (msg.event_type === "task.classified") {
          const payload = msg.payload ?? {};
          const rawKind = payload.interaction_kind;
          if (rawKind === "work" || rawKind === "casual" || rawKind === "project") {
            setInteractionKind(rawKind);
          }
          const projectPath =
            typeof payload.project === "string" && payload.project ? payload.project : null;
          const key = projectPath ?? "";
          if (key === projectRef.current) return;
          const previous = projectRef.current;
          projectRef.current = key;
          const name =
            projectPath ? projectPath.split(/[\\/]/).filter(Boolean).pop() ?? null : null;
          setProjectName(name);
          if (previous !== null) {
            playTrigger("project");
            showBrief(name ? `已切换到项目：${name}` : "已回到普通对话", 3000);
          }
          return;
        }
        // persona.presentation 事件：更新角色呈现
        if (msg.event_type === "persona.presentation" && msg.presentation) {
          setPresentation(msg.presentation);
          applyPresentation(msg.presentation);
          setMotionOverrides(msg.presentation.actions);
          setTransitionMs(Math.max(0, msg.presentation.animations?.transition_ms ?? 250));
          setMotionFamily(msg.presentation.motion_family ?? msg.presentation.style);
          setIdleActionIntervalMs(Math.max(2000, msg.presentation.animations?.idle_action_interval_ms ?? 8000));
          loadLayersFor(msg.presentation.persona_id);
          setMascotArt(resolveMascotUrl(msg.presentation.asset?.avatar_url));
          setVrmDriven(Boolean(msg.presentation.asset?.vrm_path));
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
          void playTts(reminderText);
          break;
        }
        case "task.completed":
          showBrief(bubble || "✓ 任务完成", 4000);
          void playTts(bubble || "任务完成");
          break;
        case "task.failed":
          showBrief(bubble || "✗ 任务失败", 4000);
          void playTts(bubble || "任务执行失败，请到对话页查看原因");
          break;
        case "task.cancelled":
          showBrief(bubble || "已取消", 3000);
          break;
      }

      if (msg.event_type === "conversation.completed") {
        if (msg.payload?.expand_ui === true && widgetTurnRef.current) {
          // 与 submitText 里的长回复分支保持一致，落到对话页（重复触发由去重窗口吸收）
          openMainUiAuto("chat");
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

  // 主动健康提醒：每 30s 上报系统空闲秒数，后端据此判断久坐/长时间工作。
  useEffect(() => {
    let alive = true;
    const reportActivity = async (): Promise<void> => {
      try {
        const idle_seconds = await invoke<number>("system_idle_seconds");
        await fetch(`${SERVICE_BASE}/api/events/publish`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            event_type: "widget.activity",
            source: "widget",
            payload: { idle_seconds },
          }),
        });
      } catch {
        /* 服务未连接或桌面端能力不可用时静默 */
      }
    };
    const timer = window.setInterval(() => void reportActivity(), 30000);
    void reportActivity();
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const image = new Image();
    image.src = mascotArt;
  }, [mascotArt]);

  useEffect(() => {
    let alive = true;
    let prevOwned = false;
    const reclaim = async (attempts: number, delayMs: number): Promise<void> => {
      // 主页释放与挂件收回同刻并发，短重试几次即时拿回，不干等轮询。
      for (let attempt = 0; attempt < attempts && alive; attempt += 1) {
        const owned = await acquireVoiceLease();
        if (!alive) return;
        if (owned) {
          prevOwned = true;
          setVoiceLeaseOwned(true);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    };
    const refreshLease = async (): Promise<void> => {
      const owned = await acquireVoiceLease();
      if (!alive) return;
      if (owned === prevOwned) return;
      prevOwned = owned;
      setVoiceLeaseOwned(owned);
      if (!owned) {
        stopMicOnly();
        setVoiceMode("off");
      }
    };
    void reclaim(6, 250);
    const timer = setInterval(() => void refreshLease(), 4000);
    // owner 变更广播：被抢立即关麦；主页释放后立即尝试收回。
    leaseOwnerEventRef.current = (owner) => {
      if (owner === "web") {
        if (prevOwned) {
          prevOwned = false;
          setVoiceLeaseOwned(false);
          stopMicOnly();
          setVoiceMode("off");
        }
      } else {
        // owner 为 widget（抢占成功）或 null（主页释放）：立即收回
        void reclaim(6, 250);
      }
    };
    return () => {
      alive = false;
      clearInterval(timer);
      leaseOwnerEventRef.current = () => {};
      stopMicOnly();
      void releaseVoiceLease();
    };
  }, []);

  useEffect(() => {
    if (!voiceLeaseOwned) {
      autoVoiceRef.current = false;
      stopMicOnly();
      setVoiceMode("off");
      return;
    }
    if (!voiceStatus?.enabled || voiceStatus.activation?.enabled === false) {
      autoVoiceRef.current = false;
      stopMicOnly();
      setVoiceMode("off");
      setState((current) => (current === "listening" ? "idle" : current));
      return;
    }
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
      playTrigger("hover");
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

  /**
   * 把素材清单里的内容包围盒换算成窗口逻辑坐标矩形。
   * 用 stage 的 getBoundingClientRect（含 translateX(-50%)）叠加 img 的 offset 系列，
   * 既含舞台定位偏移、又不含呼吸缩放动画，测量值不会随动画抖动。
   */
  const measureContentBox = (): InteractiveBox | null => {
    const img = mascotRef.current;
    const stage = stageRef.current;
    const metrics = assetMetrics;
    if (!img || !stage || !metrics?.contentBbox) return null;
    const baseW = metrics.canvasWidth || img.naturalWidth;
    const baseH = metrics.canvasHeight || img.naturalHeight;
    const boxW = img.offsetWidth;
    const boxH = img.offsetHeight;
    if (!baseW || !baseH || !boxW || !boxH) return null;
    // .mascot 是 object-fit: contain —— 图片在元素内等比居中绘制
    const drawScale = Math.min(boxW / baseW, boxH / baseH);
    const stageRect = stage.getBoundingClientRect();
    const drawX = stageRect.left + img.offsetLeft + (boxW - baseW * drawScale) / 2;
    const drawY = stageRect.top + img.offsetTop + (boxH - baseH * drawScale) / 2;
    const [x0, y0, x1, y1] = metrics.contentBbox;
    return {
      x: drawX + x0 * drawScale,
      y: drawY + y0 * drawScale,
      width: Math.max(1, (x1 - x0 + 1) * drawScale),
      height: Math.max(1, (y1 - y0 + 1) * drawScale),
    };
  };

  /** 角色内容 + 展开中的右键菜单的并集：贴边隐藏后这块区域不穿透鼠标，保证还能抓回来。 */
  const interactiveArea = (box: InteractiveBox | null): InteractiveBox | null => {
    const rects: InteractiveBox[] = [];
    if (box) rects.push(box);
    const menu = ctxMenuRef.current?.getBoundingClientRect();
    if (menu && menu.width > 0 && menu.height > 0) {
      rects.push({ x: menu.left, y: menu.top, width: menu.width, height: menu.height });
    }
    if (rects.length === 0) return null;
    const pad = WIDGET_INTERACTIVE_PADDING;
    const left = Math.min(...rects.map((r) => r.x)) - pad;
    const top = Math.min(...rects.map((r) => r.y)) - pad;
    const right = Math.max(...rects.map((r) => r.x + r.width)) + pad;
    const bottom = Math.max(...rects.map((r) => r.y + r.height)) + pad;
    return { x: left, y: top, width: right - left, height: bottom - top };
  };

  /**
   * 把「贴边保留量」和「鼠标穿透区域」回传给 Rust 侧。
   * 旧实现把保留量写死成四个常量（假设立绘左侧有大片透明区），换角色或调大小后
   * 切边位置立刻错位，极端情况下整个角色被推出屏幕、拖不回来；现在按实际内容包围盒推算。
   */
  const syncWidgetOverlayGeometry = (includeEdges: boolean): void => {
    const box = measureContentBox();
    if (includeEdges && box) {
      const handle = Math.min(
        WIDGET_HIDE_HANDLE_MAX,
        Math.max(
          WIDGET_HIDE_HANDLE_MIN,
          Math.round(Math.min(box.width, box.height) * WIDGET_HIDE_HANDLE_RATIO),
        ),
      );
      const edges = {
        // 吸附到屏幕左 / 右边缘时保留的宽度
        whenLeft: Math.round(window.innerWidth - box.x - box.width + handle),
        whenRight: Math.round(box.x + handle),
        // 吸附到屏幕上 / 下边缘时保留的高度
        whenTop: Math.round(window.innerHeight - box.y - box.height + handle),
        whenBottom: Math.round(box.y + handle),
      };
      // 上边缘隐藏时角色上移这么多，窗口底部 [whenTop, innerHeight] 那段正好落到窗口顶部。
      setTopPeekOffset(Math.max(0, Math.round(window.innerHeight - edges.whenTop)));
      void invoke("set_widget_visible_edges", { edges }).catch(() => {
        /* 非 Tauri 环境或后端不支持时忽略 */
      });
    }
    void invoke("set_widget_interactive_area", { area: interactiveArea(box) }).catch(() => {
      /* 同上 */
    });
  };
  syncOverlayRef.current = () => syncWidgetOverlayGeometry(true);

  // 素材 / 缩放 / 气泡 / 输入条变化会同时改变内容位置与窗口高度，需重新测量。
  useLayoutEffect(() => {
    syncWidgetOverlayGeometry(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetMetrics, mascotArt, preferences.scale, preferences.autoHide, bubble, inputOpen]);

  // 右键菜单展开时把菜单本身并入可交互区域。
  useLayoutEffect(() => {
    syncWidgetOverlayGeometry(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctxMenu]);

  useEffect(() => {
    const onResize = (): void => syncOverlayRef.current();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const openContextMenu = (event: React.MouseEvent): void => {
    event.preventDefault();
    const clampToWindow = (x: number, y: number, width: number, height: number) => ({
      x: Math.max(4, Math.min(x, Math.max(4, window.innerWidth - width - 4))),
      y: Math.max(4, Math.min(y, Math.max(4, window.innerHeight - height - 4))),
    });
    setCtxMenu(clampToWindow(event.clientX, event.clientY, CONTEXT_MENU_WIDTH, CONTEXT_MENU_HEIGHT));

    const desktopWindow = getCurrentWindow();
    void Promise.all([desktopWindow.outerPosition(), currentMonitor()])
      .then(([position, monitor]) => {
        if (!monitor) return;
        const scale = monitor.scaleFactor;
        // 菜单是窗口内的 fixed 元素：既不能超出显示器工作区，也不能被挂件窗口自身裁掉。
        // 两个约束换算到窗口逻辑坐标后取交集，交集为空（挂件被贴边切掉大半）时以窗口为准。
        const localMinX = (monitor.workArea.position.x + 4 * scale - position.x) / scale;
        const localMaxX =
          (monitor.workArea.position.x +
            monitor.workArea.size.width -
            (CONTEXT_MENU_WIDTH + 4) * scale -
            position.x) /
          scale;
        const localMinY = (monitor.workArea.position.y + 4 * scale - position.y) / scale;
        const localMaxY =
          (monitor.workArea.position.y +
            monitor.workArea.size.height -
            (CONTEXT_MENU_HEIGHT + 4) * scale -
            position.y) /
          scale;
        const intersect = (
          windowRange: [number, number],
          monitorRange: [number, number],
        ): [number, number] =>
          windowRange[0] > monitorRange[1] || monitorRange[0] > windowRange[1]
            ? windowRange
            : [Math.max(windowRange[0], monitorRange[0]), Math.min(windowRange[1], monitorRange[1])];
        const [minX, maxX] = intersect(
          [4, Math.max(4, window.innerWidth - CONTEXT_MENU_WIDTH - 4)],
          [localMinX, localMaxX],
        );
        const [minY, maxY] = intersect(
          [4, Math.max(4, window.innerHeight - CONTEXT_MENU_HEIGHT - 4)],
          [localMinY, localMaxY],
        );
        setCtxMenu({
          x: Math.max(minX, Math.min(event.clientX, maxX)),
          y: Math.max(minY, Math.min(event.clientY, maxY)),
        });
      })
      .catch(() => {
        /* 非 Tauri 环境保留窗口内回退位置 */
      });
  };

  // 菜单高度随内容与角色缩放浮动，渲染后按实测尺寸再收一次窗口边界，
  // 确保最下面的「退出 DeskMate」不会被挂件窗口裁掉。
  useLayoutEffect(() => {
    if (!ctxMenu) return;
    const el = ctxMenuRef.current;
    if (!el) return;
    const width = el.offsetWidth || CONTEXT_MENU_WIDTH;
    const height = el.offsetHeight || CONTEXT_MENU_HEIGHT;
    const x = Math.max(4, Math.min(ctxMenu.x, Math.max(4, window.innerWidth - width - 4)));
    const y = Math.max(4, Math.min(ctxMenu.y, Math.max(4, window.innerHeight - height - 4)));
    if (x !== ctxMenu.x || y !== ctxMenu.y) setCtxMenu({ x, y });
  }, [ctxMenu]);

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

  const vrmPath = presentation?.asset?.vrm_path;
  const vrmPersonaId = presentation?.persona_id;
  const activeTrigger = triggerFor(state, emotion);
  const activeSpriteSheet =
    spritesheets.find((sheet) => sheet.state_name === activeTrigger) ??
    spritesheets.find((sheet) => sheet.state_name === state) ??
    null;

  return (
    <div
      className="w-root"
      data-state={state}
      data-emotion={emotion}
      data-emotion-decay={emotionDecaying ? "fading" : "full"}
      data-vrm={vrmPath ? "1" : "0"}
      data-persona-style={presentation?.style ?? motionFamily}
      data-motion-family={motionFamily}
      data-interaction={interactionKind}
      data-action={action?.className ?? ""}
      data-fx={action?.fx ?? ""}
      data-alert={alert ? "1" : "0"}
      data-voice={voiceMode}
      data-speaking={speaking ? "1" : "0"}
      data-connected={connected}
      data-active={active ? "1" : "0"}
      data-input-open={inputOpen ? "1" : "0"}
      data-hidden-edge={preferences.hiddenEdge === "top" ? "top" : undefined}
      style={{ "--top-peek-offset": `${topPeekOffset}px` } as CSSProperties}
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
        ref={stageRef}
        data-active={active ? "1" : "0"}
        style={{ "--mascot-size": `${MASCOT_BASE_SIZE * preferences.scale}px` } as CSSProperties}
        title="点击激活（播报中点击打断）· 双击打开主界面 · 按住拖动 · 右键菜单"
        onPointerDown={startStageDrag}
        onMouseEnter={() => playTrigger("hover")}
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
          playTrigger("click");
          // 播报中点击 = 打断当前语音（与主界面 ⏹ 停止等价）
          if (speakingRef.current) {
            stopSpeaking();
            showBrief("已打断", 1600);
            void notifySpeechInterrupted();
            setCtxMenu(null);
            return;
          }
          // VRM：空闲时点击给一次性反馈动作（动画播完自动回当前状态）
          vrmOneShotFeedback("click");
          activateStage();
          setCtxMenu(null);
        }}
        onDoubleClick={(event) => {
          if (clickSuppressed()) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          void openMainUiManual("chat");
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
        <div
          className="widget-context"
          data-visible={projectName || ERROR_STATES.has(state) ? "1" : "0"}
          aria-hidden="true"
        >
          {projectName && <span className="widget-context-project">{projectName}</span>}
          {ERROR_STATES.has(state) && (
            <span className="widget-context-state">{STATE_LABEL[state] ?? state}</span>
          )}
        </div>
        {vrmPath && vrmPersonaId ? (
          <div className="mascot mascot-wrap" data-vrm="1">
            <img
              className="mascot-base"
              ref={mascotRef}
              src={mascotArt}
              alt={`DeskMate ${bubble || (connected ? "状态正常" : "服务未连接")}`}
              draggable={false}
              data-hidden="1"
            />
            <Suspense fallback={null}>
              <VrmStage
                personaId={vrmPersonaId}
                vrmPath={vrmPath}
                trigger={activeTrigger}
                emotion={emotion}
                vrmConfig={presentation?.vrm}
                idleIntervalMs={idleActionIntervalMs}
                oneShot={vrmOneShot}
              />
            </Suspense>
          </div>
        ) : activeSpriteSheet && layersPersonaId ? (
          <div className="mascot mascot-wrap" data-sprite="1">
            <img
              className="mascot-base"
              ref={mascotRef}
              src={mascotArt}
              alt={`DeskMate ${bubble || (connected ? "状态正常" : "服务未连接")}`}
              draggable={false}
              data-hidden="1"
            />
            <div className="mascot-sprite-stage">
              <SpriteSheetStage
                personaId={layersPersonaId}
                sheet={activeSpriteSheet}
              />
            </div>
          </div>
        ) : layers && layersPersonaId ? (
          <div className="mascot mascot-wrap" data-layers="1">
            <img
              className="mascot-base"
              ref={mascotRef}
              src={mascotArt}
              alt={`DeskMate ${bubble || (connected ? "状态正常" : "服务未连接")}`}
              draggable={false}
              data-hidden="1"
            />
            <div className="mascot-layers">
              {layers.map((layer) => (
                <FramedLayer
                  key={layer.id || `${layer.z}-${layer.file}`}
                  personaId={layersPersonaId}
                  layer={layer}
                  trigger={activeTrigger}
                  state={state}
                />
              ))}
            </div>
          </div>
        ) : vrmDriven ? null : (
          <img
            className="mascot"
            ref={mascotRef}
            src={mascotArt}
            alt={`DeskMate ${bubble || (connected ? "状态正常" : "服务未连接")}`}
            draggable={false}
          />
        )}

        {/* Phase 3: 触摸/悬停区域反应 */}
        <div 
          className="hover-zone hover-zone-head"
          onMouseEnter={() => {
            playTrigger("hover");
            showBrief("❤", 1200);
          }}
          aria-hidden="true"
        />
        <div 
          className="hover-zone hover-zone-body"
          onMouseEnter={() => {
            playTrigger("hover");
            showBrief("...", 1000);
          }}
          aria-hidden="true"
        />

        <div className="fx-layer" aria-hidden="true">
          <span className="fx-sparkle" />
          <span className="fx-magic" />
          <span className="fx-speed" />
          <span className="fx-thought" />
          <span className="fx-question" />
          <span className="fx-note" />
        </div>

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

        {voiceEnabled && (
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
          ref={ctxMenuRef}
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          data-no-drag
        >
          <button
            onClick={() => {
              setCtxMenu(null);
              void openMainUiManual("chat");
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
