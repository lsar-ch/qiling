import { describe, expect, it } from "vitest";

import {
  createAnimalMobility,
  setAnimalTemporaryHome,
  updateAnimalMobility,
  type AnimalMobilityState,
} from "./animalMobility";

const area = { x: 0, y: 0, width: 1200, height: 800 };
const size = { width: 430, height: 480 };

function tick(
  state: AnimalMobilityState,
  taskActive: boolean,
  random: () => number = () => 0.5,
  deltaMs = 100,
  nowMs = 0,
) {
  return updateAnimalMobility(state, {
    taskActive,
    dragging: false,
    deltaMs,
    nowMs,
    workArea: area,
    windowSize: size,
    random,
  });
}

describe("animal mobility", () => {
  it("idle loiters first, then strolls at walk speed", () => {
    let state = createAnimalMobility({ x: 100, y: 120 });
    let now = 0;
    // 初始 0 值 → 第一 tick 先安排驻足（random 0.5 → 4000+2500=6500ms）
    let frame = tick(state, false, () => 0.5, 100, now);
    state = frame.state;
    expect(frame.gait).toBeNull();
    expect(state.pauseUntilMs).toBe(6500);

    // 驻足期内不动
    for (now = 100; now < 6500; now += 1000) {
      frame = tick(state, false, () => 0.5, 1000, now);
      state = frame.state;
      expect(frame.position).toEqual({ x: 100, y: 120 });
      expect(frame.gait).toBeNull();
    }
    // 驻足期满先进入「起身准备」：窗口静止、保持正面、不发布 gait
    frame = tick(state, false, () => 0.5, 100, now);
    state = frame.state;
    expect(frame.gait).toBeNull();
    expect(frame.facing).toBe("front");
    expect(frame.state.phase).toBe("standing");
    expect(frame.position).toEqual({ x: 100, y: 120 });
    expect(frame.state.standUntilMs).toBe(now + 1350);

    // 起身期间任意 tick 都不移动、不转身
    for (const t of [now + 100, now + 600, now + 1300]) {
      frame = tick(state, false, () => 0.5, 100, t);
      expect(frame.gait).toBeNull();
      expect(frame.facing).toBe("front");
      expect(frame.position).toEqual({ x: 100, y: 120 });
    }

    // 起身完成才转身出发、慢走
    frame = tick(state, false, () => 0.5, 100, now + 1400);
    expect(frame.gait).toBe("walk");
    expect(frame.state.phase).toBe("roaming");
    expect(frame.state.target).not.toBeNull();
  });

  it("task movement is bounded, monotonic, and runs", () => {
    let state = createAnimalMobility({ x: 700, y: 300 });
    let previous = { ...state.current };
    let target: { x: number; y: number } | null = null;
    for (let i = 0; i < 20; i += 1) {
      const frame = tick(state, true, () => 0.25);
      state = frame.state;
      target ??= state.target;
      expect(frame.gait).toBe("run");
      expect(frame.position.x).toBeGreaterThanOrEqual(area.x);
      expect(frame.position.x).toBeLessThanOrEqual(area.x + area.width - size.width);
      expect(frame.position.y).toBeGreaterThanOrEqual(area.y);
      expect(frame.position.y).toBeLessThanOrEqual(area.y + area.height - size.height);
      if (target && state.target === target) {
        const before = Math.hypot(target.x - previous.x, target.y - previous.y);
        const after = Math.hypot(target.x - frame.position.x, target.y - frame.position.y);
        expect(after).toBeLessThanOrEqual(before);
      }
      previous = { ...frame.position };
    }
    expect(target).not.toBeNull();
    expect(state.phase).toBe("roaming");
  });

  it("finishes the current stroll target then loiters when the task ends", () => {
    let state = createAnimalMobility({ x: 700, y: 300 });
    for (let i = 0; i < 8; i += 1) state = tick(state, true).state;
    expect(state.phase).toBe("roaming");

    let now = 0;
    let stopped = false;
    for (let i = 0; i < 200; i += 1) {
      const frame = tick(state, false, () => 0.5, 100, now);
      state = frame.state;
      now += 100;
      if (frame.state.phase === "home" && frame.gait === null) {
        stopped = true;
        break;
      }
    }
    expect(stopped).toBe(true);
    // 驻足期内位置不再变化
    const rested = { ...state.current };
    const frame = tick(state, false, () => 0.5, 1000, now + 1000);
    expect(frame.position).toEqual(rested);
  });

  it("dragging suspends writes and the drop position stays put after release", () => {
    const state = createAnimalMobility({ x: 100, y: 100 });
    const dragged = updateAnimalMobility(state, {
      taskActive: true,
      dragging: true,
      deltaMs: 100,
      nowMs: 0,
      workArea: area,
      windowSize: size,
    });
    expect(dragged.gait).toBeNull();
    expect(dragged.state.phase).toBe("manual");

    const dropped = setAnimalTemporaryHome(dragged.state, { x: 333, y: 444 });
    const idle = tick(dropped, false);
    expect(idle.position).toEqual({ x: 333, y: 444 });
    expect(idle.state.home).toEqual({ x: 333, y: 444 });
    expect(idle.gait).toBeNull();
  });

  it("manual release never snaps current back to the stale home", () => {
    // 回归：松手后 manual→home 不得把 current 拉回旧 home（瞬移回跳修复）。
    let state = createAnimalMobility({ x: 100, y: 100 });
    state = tick(state, true).state;
    const dragged = updateAnimalMobility(
      { ...state, home: { x: 100, y: 100 }, current: { x: 900, y: 500 } },
      {
        taskActive: false,
        dragging: true,
        deltaMs: 100,
        nowMs: 0,
        workArea: area,
        windowSize: size,
      },
    );
    expect(dragged.state.phase).toBe("manual");
    const released = tick(dragged.state, false, () => 0.5, 100, 0);
    expect(released.position).toEqual({ x: 900, y: 500 });
    expect(released.state.phase).toBe("home");
  });

  it("busy overrides the idle pause and resumes running immediately", () => {
    let state = createAnimalMobility({ x: 100, y: 120 });
    let now = 0;
    state = tick(state, false, () => 0.5, 100, now).state; // 安排驻足
    now = 1000; // 驻足期内
    const frame = tick(state, true, () => 0.5, 100, now);
    expect(frame.gait).toBe("run");
    expect(frame.state.phase).toBe("roaming");
  });
});
