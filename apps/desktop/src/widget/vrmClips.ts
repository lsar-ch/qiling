/**
 * VRM 动作候选挑选：一个 trigger 可以挂多条 vrma，按 weight 随机、按 cooldownMs 挡重复。
 *
 * 只做纯逻辑，不碰 three / DOM —— 自检：`npx tsx apps/desktop/src/widget/vrmClips.ts`
 */
import type { VrmClipRef } from "@qiling/contracts";

export interface VrmClipChoice {
  clip: string;
  repeat: number;
  timeScale: number;
}

interface Candidate extends VrmClipChoice {
  weight: number;
  cooldownMs: number;
}

function toArray(refs: VrmClipRef | VrmClipRef[] | undefined): VrmClipRef[] {
  if (refs == null) return [];
  return Array.isArray(refs) ? refs : [refs];
}

/** 单条候选归一成完整参数；字符串 / 对象两种写法都吃。 */
function normalize(ref: VrmClipRef, fallback: string): Candidate {
  const base: Candidate = { clip: fallback, repeat: 1, timeScale: 1, weight: 1, cooldownMs: 0 };
  if (typeof ref === "string") {
    return { ...base, clip: ref || fallback };
  }
  return {
    clip: ref.clip || fallback,
    repeat: Math.max(1, Math.floor(ref.repeat ?? 1)),
    timeScale: ref.timeScale && ref.timeScale > 0 ? ref.timeScale : 1,
    weight: ref.weight == null ? 1 : Math.max(0, ref.weight),
    cooldownMs: Math.max(0, ref.cooldownMs ?? 0),
  };
}

/** 未配候选时的默认：与 trigger 同名的文件。 */
function defaultCandidates(trigger: string): Candidate[] {
  return [{ clip: trigger, repeat: 1, timeScale: 1, weight: 1, cooldownMs: 0 }];
}

function candidatesFor(trigger: string, refs: VrmClipRef | VrmClipRef[] | undefined): Candidate[] {
  const list = toArray(refs);
  if (list.length === 0) return defaultCandidates(trigger);
  return list.map((ref) => normalize(ref, trigger));
}

/** 取第一条候选（动作实验室预览、one-shot 用）。 */
export function resolveClipRef(
  refs: VrmClipRef | VrmClipRef[] | undefined,
  trigger: string,
): VrmClipChoice {
  const [first] = candidatesFor(trigger, refs);
  return { clip: first.clip, repeat: first.repeat, timeScale: first.timeScale };
}

/**
 * 按权重挑一条候选。weight <= 0 视为弃用；冷却内的候选直接排除。
 * 全部冷却中时返回 null —— 调用方保持当前动作，不硬切。
 */
export function pickVrmClip(
  trigger: string,
  refs: VrmClipRef | VrmClipRef[] | undefined,
  playedAt: Record<string, number>,
  now: number,
  random: () => number = Math.random,
): VrmClipChoice | null {
  const available = candidatesFor(trigger, refs).filter(
    (item) =>
      item.weight > 0 && now - (playedAt[item.clip] ?? Number.NEGATIVE_INFINITY) >= item.cooldownMs,
  );
  if (available.length === 0) return null;

  const total = available.reduce((sum, item) => sum + item.weight, 0);
  let roll = Math.max(0, Math.min(total - Number.EPSILON, random() * total));
  for (const item of available) {
    roll -= item.weight;
    if (roll < 0) return { clip: item.clip, repeat: item.repeat, timeScale: item.timeScale };
  }
  const last = available[available.length - 1];
  return { clip: last.clip, repeat: last.repeat, timeScale: last.timeScale };
}

/** 自检：改动本模块后跑一次。 */
export function demo(): void {
  if (resolveClipRef(undefined, "idle").clip !== "idle") throw new Error("默认应回退同名文件");
  if (resolveClipRef("", "hover").clip !== "hover") throw new Error("空字符串应回退 trigger");

  const single = resolveClipRef({ clip: "error", repeat: 2, timeScale: 0.7 }, "click");
  if (single.clip !== "error" || single.repeat !== 2 || Math.abs(single.timeScale - 0.7) > 1e-9) {
    throw new Error("对象写法参数丢失");
  }

  const refs: VrmClipRef[] = [{ clip: "idle" }, { clip: "idle_look", weight: 3 }];
  const seen = new Set<string>();
  for (let i = 0; i < 200; i += 1) {
    seen.add(pickVrmClip("idle", refs, {}, i, () => i / 200)?.clip ?? "");
  }
  if (seen.size !== 2) throw new Error("两条候选都应有机会被挑到");
  if ([...seen].some((id) => id !== "idle" && id !== "idle_look")) throw new Error("挑出了候选外的动作");

  const only = pickVrmClip("idle", [{ clip: "idle", weight: 0 }, { clip: "idle_look" }], {}, 0, () => 0);
  if (only?.clip !== "idle_look") throw new Error("weight 0 的候选必须被排除");
  if (pickVrmClip("idle", [{ clip: "idle", weight: 0 }], {}, 0) !== null) {
    throw new Error("候选全被排除时应返回 null");
  }

  const cold = [{ clip: "a", cooldownMs: 5000 }, { clip: "b" }];
  if (pickVrmClip("idle", cold, { a: 1000 }, 1500, () => 0)?.clip !== "b") {
    throw new Error("冷却内的候选必须被排除");
  }
  if (pickVrmClip("idle", cold, { a: 1000 }, 7000, () => 0)?.clip !== "a") {
    throw new Error("冷却过后应重新可挑");
  }
}

// 直接用 tsx 跑本文件时执行自检；挂件里 import.meta.url 是 http(s)/tauri，不会触发。
if (import.meta.url.startsWith("file:")) demo();
