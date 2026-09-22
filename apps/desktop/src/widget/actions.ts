import type { ExpressionEmotion, MotionFamily, WidgetState } from "../api";

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

export interface ActionSelection {
  id: string;
  className: string;
  durationMs: number;
  loop: boolean;
  fx?: FxKind;
}

const spec = (
  id: string,
  className: string,
  durationMs: number,
  cooldownMs: number,
  weight = 1,
  fx?: FxKind,
): ActionSpec => ({ id, className, durationMs, cooldownMs, weight, fx });

export const ACTIONS: Record<MotionFamily, Record<ActionTrigger, ActionSpec[]>> = {
  human: {
    idle: [
      spec("human-breathe", "act-breath", 3600, 4000, 2),
      spec("human-look", "act-human-look", 2200, 9000, 1),
      spec("human-stretch", "act-human-stretch", 1800, 14000, 0.6),
    ],
    listening: [spec("human-attend", "act-human-attend", 1100, 4000, 1)],
    thinking: [spec("human-think", "act-human-think", 2000, 5000, 1)],
    speaking: [spec("human-speak", "act-speak", 1200, 2000, 1)],
    executing: [spec("human-execute", "act-execute", 1500, 2000, 1)],
    awaiting_approval: [spec("human-question", "act-question", 1600, 3000, 1, "question")],
    success: [spec("human-wave", "act-human-wave", 1400, 6000, 1, "sparkle")],
    project: [spec("human-project", "act-human-wave", 1400, 7000, 1, "sparkle")],
    error: [spec("human-shrug", "act-error-shake", 900, 5000, 1)],
    click: [spec("human-nod", "act-human-nod", 900, 3000, 1)],
    hover: [spec("human-lean", "act-human-lean", 700, 1500, 1)],
  },
  animal: {
    idle: [
      spec("animal-breathe", "act-breath", 3600, 4000, 2),
      spec("animal-tail", "act-animal-tail", 2000, 8000, 1),
      spec("animal-ear", "act-animal-ear", 1200, 6000, 1),
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

export function triggerFor(state: WidgetState, emotion: ExpressionEmotion): ActionTrigger {
  if (emotion === "success") return "success";
  if (emotion === "error") return "error";
  if (emotion === "happy") return "success";
  if (emotion === "sad") return "error";
  if (emotion === "surprised") return "awaiting_approval";
  if (emotion === "thinking") return "thinking";
  if (emotion === "confused") return "awaiting_approval";
  if (emotion === "attentive") return "listening";
  switch (state) {
    case "idle":
      return "idle";
    case "listening":
      return "listening";
    case "thinking":
      return "thinking";
    case "speaking":
      return "speaking";
    case "executing":
      return "executing";
    case "awaiting_approval":
      return "awaiting_approval";
    case "completed":
      return "success";
    case "interrupted":
      return "idle";
  }
  return "idle";
}

export function pickAction(
  family: MotionFamily,
  trigger: ActionTrigger,
  playedAt: Record<string, number>,
  now: number,
  random: () => number = Math.random,
): ActionSelection | null {
  const candidates = (ACTIONS[family] ?? {})[trigger] ?? [];
  const available = candidates.filter(
    (item) => now - (playedAt[item.id] ?? Number.NEGATIVE_INFINITY) >= item.cooldownMs,
  );
  if (available.length === 0) return null;
  const total = available.reduce((sum, item) => sum + item.weight, 0);
  let roll = Math.max(0, Math.min(total - Number.EPSILON, random() * total));
  for (const item of available) {
    roll -= item.weight;
    if (roll < 0) {
      return {
        id: item.id,
        className: item.className,
        durationMs: item.durationMs,
        loop: item.loop ?? trigger === "idle",
        fx: item.fx,
      };
    }
  }
  const last = available[available.length - 1];
  return {
    id: last.id,
    className: last.className,
    durationMs: last.durationMs,
    loop: last.loop ?? trigger === "idle",
    fx: last.fx,
  };
}

export function demo(): void {
  const families: MotionFamily[] = ["human", "animal", "anime"];
  const triggers: ActionTrigger[] = [
    "idle", "listening", "thinking", "speaking", "executing",
    "awaiting_approval", "success", "error", "click", "project", "hover",
  ];
  for (const family of families) {
    for (const trigger of triggers) {
      if (!ACTIONS[family][trigger].length) {
        throw new Error(`missing action table: ${family}/${trigger}`);
      }
    }
  }
  const played: Record<string, number> = {};
  const first = pickAction("human", "idle", played, 1000, () => 0);
  if (!first) throw new Error("idle pick must return an action");
  const blocked = pickAction("human", "idle", { [first.id]: 1000 }, 1100, () => 0);
  if (blocked?.id === first.id) throw new Error("cooldown must block the same action");
  if (triggerFor("completed", "neutral") !== "success") throw new Error("trigger mapping broken");
}
