import { describe, expect, it } from "vitest";

import { bridgeClipFor, bridgeFollowUpFor, clipFamily, departureBridgeFor } from "./animalTransition";

const AVAILABLE = [
  "sit_idle",
  "walk",
  "run",
  "sit_down",
  "stand_up",
  "head_look",
  "pose_sit_tall",
];

describe("clip family", () => {
  it("坐姿系包含 sit_idle 与其派生动作", () => {
    for (const clip of ["sit_idle", "head_look", "think_sit", "speak_sit", "crouch_once", "tap_paw_once", "jump_once"]) {
      expect(clipFamily(clip)).toBe("sit");
    }
  });

  it("站姿系只含行走相关动作", () => {
    for (const clip of ["walk", "run", "walk_start", "walk_stop"]) {
      expect(clipFamily(clip)).toBe("stand");
    }
  });

  it("灰区与未列举的 clip 一律不判定", () => {
    for (const clip of ["pose_sit_tall", "sleep", "lick_paw", "idle", "sit_down", "stand_up", "", null, undefined]) {
      expect(clipFamily(clip)).toBeNull();
    }
  });
});

describe("bridge clip", () => {
  it("坐 → 站 先播 stand_up", () => {
    expect(bridgeClipFor("sit_idle", "walk", AVAILABLE)).toBe("stand_up");
    expect(bridgeClipFor("head_look", "run", AVAILABLE)).toBe("stand_up");
  });

  it("站 → 坐 先播 sit_down", () => {
    expect(bridgeClipFor("walk", "sit_idle", AVAILABLE)).toBe("sit_down");
    expect(bridgeClipFor("run", "think_sit", AVAILABLE)).toBe("sit_down");
  });

  it("同族不桥接", () => {
    expect(bridgeClipFor("sit_idle", "head_look", AVAILABLE)).toBeNull();
    expect(bridgeClipFor("walk", "run", AVAILABLE)).toBeNull();
    expect(bridgeClipFor("walk", "walk_start", AVAILABLE)).toBeNull();
  });

  it("任一侧未判定就不桥接，避免误插过渡", () => {
    expect(bridgeClipFor("sit_idle", "pose_sit_tall", AVAILABLE)).toBeNull();
    expect(bridgeClipFor("pose_sit_tall", "sit_idle", AVAILABLE)).toBeNull();
    expect(bridgeClipFor(null, "walk", AVAILABLE)).toBeNull();
    expect(bridgeClipFor("walk", "sit_down", AVAILABLE)).toBeNull();
  });

  it("过渡 clip 不在 GLB 里时退回 crossFade", () => {
    expect(bridgeClipFor("sit_idle", "walk", ["sit_idle", "walk"])).toBeNull();
    expect(bridgeClipFor("walk", "sit_idle", ["sit_idle", "walk"])).toBeNull();
  });
});

describe("bridge follow-up", () => {
  it("坐姿起身后先经过 walk_start 再进入 walk", () => {
    expect(bridgeFollowUpFor("stand_up", "walk", [...AVAILABLE, "walk_start"])).toBe("walk_start");
  });

  it("其他目标和缺失 walk_start 的旧资产不增加阶段", () => {
    expect(bridgeFollowUpFor("stand_up", "run", [...AVAILABLE, "walk_start"])).toBeNull();
    expect(bridgeFollowUpFor("stand_up", "walk", AVAILABLE)).toBeNull();
  });
});

describe("departure bridge (起身准备阶段结束后)", () => {
  it("stand_up 末帧出发先经过 walk_start", () => {
    const withStart = [...AVAILABLE, "walk_start"];
    expect(departureBridgeFor("stand_up", "walk", withStart)).toBe("walk_start");
    expect(departureBridgeFor("stand_up", "run", withStart)).toBe("walk_start");
  });

  it("非 stand_up 来源、非步行目标、旧资产都不桥接", () => {
    expect(departureBridgeFor("sit_idle", "walk", [...AVAILABLE, "walk_start"])).toBeNull();
    expect(departureBridgeFor("stand_up", "sit_idle", [...AVAILABLE, "walk_start"])).toBeNull();
    expect(departureBridgeFor("stand_up", "walk", AVAILABLE)).toBeNull();
  });
});
