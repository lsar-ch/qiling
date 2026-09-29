// 动作调度表（前端共享数据）：桌面挂件与动作实验室共用同一份事实源。
// 这里的参数是"默认值"；persona 级覆盖通过 PersonaPresentation.actions 下发。

export type ActionTrigger =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "executing"
  | "awaiting_approval"
  | "success"
  | "error"
  | "click"
  | "project"
  | "hover";

export type FxKind = "sparkle" | "magic" | "speed" | "thought" | "question" | "note";

export interface ActionSpec {
  id: string;
  className: string;
  durationMs: number;
  loop?: boolean;
  cooldownMs: number;
  weight: number;
  fx?: FxKind;
}

type MotionFamily = "human" | "animal" | "anime";

export type MotionTable = Record<MotionFamily, Record<ActionTrigger, ActionSpec[]>>;

const spec = (
  id: string,
  className: string,
  durationMs: number,
  cooldownMs: number,
  weight = 1,
  fx?: FxKind,
): ActionSpec => ({ id, className, durationMs, cooldownMs, weight, fx });

export const DEFAULT_ACTIONS: MotionTable = {
  human: {
    idle: [
      spec("human-breathe", "act-breath", 3600, 4000, 2),
      spec("human-look", "act-human-look", 2200, 9000, 1),
      spec("human-stretch", "act-human-stretch", 1800, 14000, 0.6),
      spec("human-yawn", "act-human-yawn", 2400, 30000, 0.4),
      spec("human-glance", "act-human-glance", 1400, 12000, 0.8),
    ],
    listening: [spec("human-attend", "act-human-attend", 1100, 4000, 1)],
    thinking: [spec("human-think", "act-human-think", 2000, 5000, 1)],
    speaking: [spec("human-speak", "act-speak", 1200, 2000, 1)],
    executing: [spec("human-execute", "act-execute", 1500, 2000, 1)],
    awaiting_approval: [spec("human-question", "act-question", 1600, 3000, 1, "question")],
    success: [spec("human-wave", "act-human-wave", 1400, 6000, 1, "sparkle")],
    project: [spec("human-project", "act-human-wave", 1400, 7000, 1, "sparkle")],
    error: [spec("human-shrug", "act-error-shake", 900, 5000, 1)],
    click: [spec("human-shrug", "act-error-shake", 900, 3000, 1)],
    hover: [spec("human-lean", "act-human-lean", 700, 1500, 1)],
  },
  animal: {
    idle: [
      spec("animal-breathe", "act-breath", 3600, 4000, 2),
      spec("animal-tail", "act-animal-tail", 2000, 8000, 1),
      spec("animal-ear", "act-animal-ear", 1200, 6000, 1),
      spec("animal-yawn", "act-animal-yawn", 2400, 30000, 0.4),
      spec("animal-scratch", "act-animal-scratch", 1800, 15000, 0.6),
    ],
    listening: [spec("animal-attend", "act-animal-attend", 1000, 4000, 1)],
    thinking: [spec("animal-tilt", "act-animal-tilt", 1800, 5000, 1, "thought")],
    speaking: [spec("animal-speak", "act-speak", 1200, 2000, 1)],
    executing: [spec("animal-scurry", "act-animal-scurry", 1400, 2000, 1, "speed")],
    awaiting_approval: [spec("animal-question", "act-question", 1600, 3000, 1, "question")],
    success: [spec("animal-jump", "act-animal-jump", 1200, 6000, 1, "sparkle")],
    project: [spec("animal-project", "act-animal-jump", 1200, 7000, 1, "sparkle")],
    error: [spec("animal-crouch", "act-animal-crouch", 1100, 5000, 1)],
    click: [spec("animal-hop", "act-animal-hop", 800, 3000, 1)],
    hover: [spec("animal-head", "act-animal-head", 700, 1500, 1)],
  },
  anime: {
    idle: [
      spec("anime-breathe", "act-breath", 3600, 4000, 2),
      spec("anime-float", "act-anime-float", 2600, 8000, 1, "sparkle"),
      spec("anime-turn", "act-anime-turn", 1400, 9000, 0.8),
      spec("anime-yawn", "act-anime-yawn", 2400, 30000, 0.4),
      spec("anime-sparkle", "act-anime-sparkle", 1600, 10000, 0.6, "sparkle"),
    ],
    listening: [spec("anime-attend", "act-human-attend", 1000, 4000, 1)],
    thinking: [spec("anime-think", "act-anime-think", 2000, 5000, 1, "thought")],
    speaking: [spec("anime-speak", "act-speak", 1200, 2000, 1, "note")],
    executing: [spec("anime-magic", "act-anime-magic", 1600, 2500, 1, "magic")],
    awaiting_approval: [spec("anime-question", "act-question", 1600, 3000, 1, "question")],
    success: [spec("anime-flash", "act-anime-flash", 1300, 6000, 1, "magic")],
    project: [spec("anime-project", "act-anime-flash", 1300, 7000, 1, "magic")],
    error: [spec("anime-dizzy", "act-anime-dizzy", 1200, 5000, 1)],
    click: [spec("anime-spark", "act-anime-turn", 900, 3000, 1, "sparkle")],
    hover: [spec("anime-look", "act-anime-look", 700, 1500, 1)],
  },
};
