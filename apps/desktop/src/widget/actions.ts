import type { ExpressionEmotion, MotionFamily, MotionOverrides, WidgetState } from "../api";
import { DEFAULT_ACTIONS } from "@qiling/contracts";
import type { ActionSpec, ActionTrigger, FxKind } from "@qiling/contracts";

export type { ActionSpec, ActionTrigger, FxKind } from "@qiling/contracts";

export interface ActionSelection {
  id: string;
  className: string;
  durationMs: number;
  loop: boolean;
  fx?: FxKind;
}

export const ACTIONS: Record<MotionFamily, Record<ActionTrigger, ActionSpec[]>> = DEFAULT_ACTIONS;

// 动作实验室调参覆盖：persona 级，motion_family → trigger → 动作列表。
let overrides: MotionOverrides = {};

export function setMotionOverrides(next: MotionOverrides | undefined): void {
  overrides = next ?? {};
}

/** 合并内置 ACTIONS 与 persona 覆盖；覆盖按 id 补全缺省字段。 */
export function effectiveActions(): Record<MotionFamily, Record<ActionTrigger, ActionSpec[]>> {
  if (Object.keys(overrides).length === 0) return ACTIONS;
  const merged: Record<MotionFamily, Record<ActionTrigger, ActionSpec[]>> = { ...ACTIONS };
  for (const [family, triggers] of Object.entries(overrides)) {
    const fam = family as MotionFamily;
    if (!merged[fam]) continue;
    for (const [trigger, specs] of Object.entries(triggers)) {
      const trig = trigger as ActionTrigger;
      if (!merged[fam][trig]) continue;
      const base = merged[fam][trig];
      merged[fam] = {
        ...merged[fam],
        [trig]: specs.map((s) => {
          const existing = base.find((b) => b.id === s.id);
          return {
            id: s.id,
            className: s.className ?? existing?.className ?? "",
            durationMs: s.durationMs ?? existing?.durationMs ?? 1000,
            cooldownMs: s.cooldownMs ?? existing?.cooldownMs ?? 1000,
            weight: s.weight ?? existing?.weight ?? 1,
            loop: s.loop ?? existing?.loop,
            fx: (s.fx as ActionSpec["fx"]) ?? existing?.fx,
          };
        }),
      };
    }
  }
  return merged;
}

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
  weightMultiplier: (actionId: string) => number = () => 1.0,
): ActionSelection | null {
  const table = effectiveActions();
  const candidates = (table[family] ?? {})[trigger] ?? [];
  const available = candidates.filter(
    (item) => now - (playedAt[item.id] ?? Number.NEGATIVE_INFINITY) >= item.cooldownMs,
  );
  if (available.length === 0) return null;
  
  // Phase 4: 应用时间权重调整
  const adjustedAvailable = available.map(item => ({
    ...item,
    weight: item.weight * weightMultiplier(item.id),
  }));
  
  const total = adjustedAvailable.reduce((sum, item) => sum + item.weight, 0);
  let roll = Math.max(0, Math.min(total - Number.EPSILON, random() * total));
  for (const item of adjustedAvailable) {
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
  const last = adjustedAvailable[adjustedAvailable.length - 1];
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

// Phase 2: 动画过渡平滑
// 在两个动作之间插入中性位过渡，避免"跳切"感
export const TRANSITION_MS = 250;

export function smoothTransition(
  el: HTMLElement,
  fromClass: string,
  toClass: string,
  transitionMs: number = TRANSITION_MS,
): Promise<void> {
  return new Promise((resolve) => {
    // 先移除当前动作，进入中性位（data-action 设为空）
    if (fromClass && fromClass !== toClass) {
      el.dataset.action = "";
    }

    // 等待过渡时长后设置新动作
    const timer = setTimeout(() => {
      el.dataset.action = toClass;
      resolve();
    }, transitionMs);

    // 如果组件卸载，清理定时器（通过 Promise.race 模式）
    // 这里简化处理：假设调用方会在卸载时取消 Promise
  });
}
