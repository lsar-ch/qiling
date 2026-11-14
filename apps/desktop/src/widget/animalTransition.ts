/**
 * 动物动作的「站 / 坐」族判定与过渡桥接。
 *
 * 背景：33 条 clip 里，坐姿系（`sit_idle` 及其派生）与站姿系（`walk` / `run` / 起步驻足）
 * 的首帧姿态差很大，直接用 0.2s crossFade 会让四条腿互相穿过去。有了
 * `sit_down` / `stand_up` 两条过渡后，切换时先播过渡、再播目标，就没有穿腿。
 *
 * 名单只用**实测可靠**的 clip（首帧姿态与参考坐姿 / 站姿距离比 ≥ 60）：
 * 实测数据见 `scripts/animal/classify_clip_family.py` 的 FAMILY_REPORT。
 * 灰区 clip（`pose_sit_tall` 1.46、`sleep` 1.08、`lick_paw` 2.10、`walk` 1.40 等）
 * **不做桥接**，继续用 crossFade —— 误插过渡比不插更难看。
 */

/** 坐姿系：首帧与 `sit_idle@0` 的 973 骨姿态差 ≤0.016，与站姿差 ≥0.97（比值 ≥63） */
const SIT_CLIPS = new Set([
  "sit_idle",
  "head_look",
  "think_sit",
  "speak_sit",
  "crouch_once",
  "tap_paw_once",
  "jump_once",
]);

/** 站姿系：行走相关，四足完全展开 */
const STAND_CLIPS = new Set(["walk", "run", "walk_start", "walk_stop"]);

export type ClipFamily = "sit" | "stand";

export function clipFamily(name: string | null | undefined): ClipFamily | null {
  if (!name) return null;
  if (SIT_CLIPS.has(name)) return "sit";
  if (STAND_CLIPS.has(name)) return "stand";
  return null;
}

/**
 * 返回需要先播的过渡 clip；不需要过渡时返回 null。
 *
 * - 坐 → 站：`stand_up`
 * - 站 → 坐：`sit_down`
 * - 同族 / 任一侧未判定 / 过渡 clip 不在 GLB 里：null（交给 crossFade）
 *
 * 注意 `stand_up` 自身首帧是坐姿、末帧是站姿，所以过渡播完必须直接接目标，
 * 不能再用本函数判定（否则会来回桥接）。
 */
export function bridgeClipFor(
  from: string | null | undefined,
  to: string | null | undefined,
  available: readonly string[],
): string | null {
  const before = clipFamily(from);
  const after = clipFamily(to);
  if (!after || before === after) return null;
  if (before === "sit" && after === "stand") {
    return available.includes("stand_up") ? "stand_up" : null;
  }
  if (before === "stand" && after === "sit") {
    return available.includes("sit_down") ? "sit_down" : null;
  }
  return null;
}

export function bridgeFollowUpFor(
  bridge: string,
  target: string,
  available: readonly string[],
): string | null {
  return bridge === "stand_up" && target === "walk" && available.includes("walk_start")
    ? "walk_start"
    : null;
}

/**
 * 跨阶段出发桥接：起身准备阶段（mobility phase=standing）里 `stand_up` 已独立
 * 播完并停在站姿末帧；roaming 阶段开始时再从这条末帧经 `walk_start` 接上 walk。
 *
 * 与 `bridgeFollowUpFor` 的区别：那条处理「同一次 play 内」的
 * stand_up → walk_start → walk 链；这条处理起身与出发分属两个阶段的情况。
 * 两者都避免站姿末帧直接跳进步行循环，也保证转身只发生在站起之后。
 */
export function departureBridgeFor(
  from: string | null | undefined,
  to: string | null | undefined,
  available: readonly string[],
): string | null {
  return from === "stand_up" && (to === "walk" || to === "run") && available.includes("walk_start")
    ? "walk_start"
    : null;
}
