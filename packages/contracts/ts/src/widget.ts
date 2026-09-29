// 挂件状态契约 —— 镜像自 deskmate_contracts/widget.py。
import type { ArtStyle, MotionFamily } from "./character";

export type PersonaStyle = MotionFamily;

export type WidgetState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "executing"
  | "awaiting_approval"
  | "completed"
  | "interrupted";

export interface WidgetStatusReport {
  report_id: string;
  state: WidgetState;
  task_id: string | null;
  message: string | null;
  timestamp: string;
}

/** 单个动作的参数覆盖（动作实验室调参产物）。缺省字段回退 actions.ts 内置值。 */
export interface MotionActionOverride {
  id: string;
  className?: string;
  durationMs?: number;
  cooldownMs?: number;
  weight?: number;
  loop?: boolean;
  fx?: string;
}

/** 2D 动作参数覆盖：motion_family → trigger → 动作列表。 */
export type MotionOverrides = Record<string, Record<string, MotionActionOverride[]>>;

/** 3D VRMA 播放参数：同一 trigger 可给多条候选。 */
export type VrmClipRef =
  | string
  | {
      clip: string;
      repeat?: number;
      timeScale?: number;
      /** 多候选时的相对权重，缺省 1。 */
      weight?: number;
      /** 多候选时的冷却毫秒，缺省 0。 */
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
   * 例：{ click: { clip: "error", repeat: 2 }, idle: [{ clip: "idle" }, { clip: "idle_look", weight: 0.5 }] }
   */
  actions?: Record<string, VrmClipRef | VrmClipRef[]>;
}

export interface PersonaPresentation {
  persona_id: string;
  persona_name: string;
  style: PersonaStyle;
  motion_family: MotionFamily;
  art_style: ArtStyle | null;
  theme: Record<string, string>;
  animations: Record<string, number>;
  fx: Record<string, boolean>;
  actions?: MotionOverrides;
  vrm?: VrmMotionConfig | null;
  asset: Record<string, unknown> | null;
}
