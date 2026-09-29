/**
 * 内在驱动状态：体力 / 疲劳 / 无聊。
 *
 * 只调制挂件空闲时的动作权重，不参与任务编排，也不下发后端。
 * 边界（2026-09-29 定，改动前先读这条）：
 *   1. 只在 idle / hover / click 这类低优先级动作上生效，任务类动作权重不受影响；
 *   2. 只输出权重乘数，永不写入 emotion 通道（否则会劫持 triggerFor 的动作行选择）；
 *   3. 乘数夹在 [0.5, 3]，真正的防刷仍由动作表里的 cooldownMs 负责。
 */
import type { WidgetState } from "../api";

export interface DriveState {
  /** 体力 0..1：执行/思考时下降，空闲时回升。 */
  energy: number;
  /** 疲劳 0..1：连续活动累积，空闲时消退。 */
  fatigue: number;
  /** 无聊 0..1：空闲时累积，任何互动清零。 */
  boredom: number;
}

/** 会在状态上停留一段时间的非空闲态。 */
const ACTIVE_STATES = new Set<WidgetState>(["listening", "thinking", "speaking", "executing"]);
/** 真正消耗体力的重工作态。 */
const WORK_STATES = new Set<WidgetState>(["thinking", "executing"]);

export const DRIVE_WEIGHT_MIN = 0.5;
export const DRIVE_WEIGHT_MAX = 3;

/**
 * 每秒变化率。调参就改这一张表，不要在别处写死数字。
 * 量级刻意取小：驱动要几分钟才看得出来，不能几秒就变脸。
 */
export const DRIVE_RATES = {
  /** 空闲回体力，约 7 分钟从 0 回满。 */
  energyIdle: 0.0025,
  /** 重工作耗体力，约 3 分钟从满到空。 */
  energyWork: -0.005,
  /** 活动累积疲劳，约 5 分钟到顶。 */
  fatigueWork: 0.003,
  /** 空闲消退疲劳。 */
  fatigueIdle: -0.0025,
  /** 空闲累积无聊，约 100 秒到顶。 */
  boredomIdle: 0.01,
} as const;

export function createDriveState(): DriveState {
  return { energy: 0.7, fatigue: 0.05, boredom: 0 };
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function clampWeight(value: number): number {
  return Math.min(DRIVE_WEIGHT_MAX, Math.max(DRIVE_WEIGHT_MIN, value));
}

/**
 * 按真实经过时间推进驱动。
 * elapsedMs 由调用方按 Date.now() 差值给出，不吃 tick 精度——定时器被节流也不会算错。
 */
export function advanceDrive(drive: DriveState, elapsedMs: number, state: WidgetState): void {
  const seconds = Math.max(0, elapsedMs) / 1000;
  if (seconds === 0) return;
  const working = WORK_STATES.has(state);
  const active = ACTIVE_STATES.has(state);

  drive.energy = clamp01(
    drive.energy + (working ? DRIVE_RATES.energyWork : active ? 0 : DRIVE_RATES.energyIdle) * seconds,
  );
  drive.fatigue = clamp01(
    drive.fatigue + (active ? DRIVE_RATES.fatigueWork : DRIVE_RATES.fatigueIdle) * seconds,
  );
  if (state === "idle") {
    drive.boredom = clamp01(drive.boredom + DRIVE_RATES.boredomIdle * seconds);
  }
}

/** 状态切换的瞬时效应：开始互动就清零无聊，任务完成回一点精力。 */
export function noteStateChange(drive: DriveState, prev: WidgetState, next: WidgetState): void {
  if (next === prev) return;
  if (ACTIVE_STATES.has(next) || next === "awaiting_approval" || next === "completed") {
    drive.boredom = 0;
  }
  if (next === "completed") {
    drive.energy = clamp01(drive.energy + 0.05);
  }
}

/** 累/没力气时更想做的动作。 */
const TIRED_ACTIONS = /yawn|stretch/;
/** 无聊时更想做的动作。 */
const BORED_ACTIONS = /glance|look|turn/;
/** 有精神时才愿意做的动作。 */
const LIVELY_ACTIONS = /sparkle|wave|jump|hop|tail|float/;

/**
 * 把驱动状态折算成动作权重乘数。
 * 只该用在 idle / hover / click 触发的动作上，调用方负责这个边界。
 */
export function driveWeightMultiplier(actionId: string, drive: DriveState): number {
  const tired = Math.max(drive.fatigue, 1 - drive.energy);
  let multiplier = 1;

  if (TIRED_ACTIONS.test(actionId)) {
    multiplier *= 1 + tired * 1.2;
  }
  if (BORED_ACTIONS.test(actionId)) {
    multiplier *= 1 + drive.boredom * 1.2;
  }
  if (LIVELY_ACTIONS.test(actionId)) {
    multiplier *= 1 + drive.energy * (1 - drive.boredom) * 0.8 - drive.fatigue * 0.5;
  }
  return clampWeight(multiplier);
}

/** 自检：`npx tsx apps/desktop/src/widget/internalState.ts` 之外，改动本模块后请跑一次。 */
export function demo(): void {
  const bored = createDriveState();
  for (let i = 0; i < 60; i += 1) advanceDrive(bored, 1000, "idle");
  if (bored.boredom <= 0.5) throw new Error("idle must accumulate boredom");
  noteStateChange(bored, "idle", "thinking");
  if (bored.boredom !== 0) throw new Error("activity must clear boredom");

  const rested = createDriveState();
  const weary: DriveState = { energy: 0, fatigue: 1, boredom: 0 };
  if (driveWeightMultiplier("human-yawn", weary) <= driveWeightMultiplier("human-yawn", rested)) {
    throw new Error("fatigue must raise yawn weight");
  }
  const boredStiff: DriveState = { energy: 0.7, fatigue: 0, boredom: 1 };
  if (driveWeightMultiplier("human-glance", boredStiff) <= driveWeightMultiplier("human-glance", rested)) {
    throw new Error("boredom must raise glance weight");
  }
  if (driveWeightMultiplier("anime-sparkle", weary) >= driveWeightMultiplier("anime-sparkle", rested)) {
    throw new Error("fatigue must lower lively weight");
  }

  const extreme: DriveState = { energy: 1, fatigue: 1, boredom: 1 };
  for (const id of ["human-yawn", "human-glance", "anime-sparkle", "human-breathe"]) {
    const weight = driveWeightMultiplier(id, extreme);
    if (!(weight >= DRIVE_WEIGHT_MIN && weight <= DRIVE_WEIGHT_MAX)) {
      throw new Error(`${id} weight out of bounds: ${weight}`);
    }
  }
  if (!(clampWeight(99) === DRIVE_WEIGHT_MAX && clampWeight(0.01) === DRIVE_WEIGHT_MIN)) {
    throw new Error("clampWeight must bound both ends");
  }

  const drift = createDriveState();
  for (let i = 0; i < 20000; i += 1) advanceDrive(drift, 1000, "executing");
  for (const key of ["energy", "fatigue", "boredom"] as const) {
    if (!(drift[key] >= 0 && drift[key] <= 1)) throw new Error(`${key} drifted out of range`);
  }
  advanceDrive(drift, -5000, "idle");
  if (drift.energy > 1 || drift.fatigue < 0) throw new Error("negative elapsed must be ignored");
}
