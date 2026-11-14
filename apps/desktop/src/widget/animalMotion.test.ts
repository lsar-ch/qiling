import { describe, expect, it } from "vitest";

import { animalMotionMetrics, resolveAnimalClip } from "./animalMotion";
import type { AnimalMotionConfig } from "../api";

const config: AnimalMotionConfig = {
  model: "model.glb",
  motionSet: "cat_v1",
  actions: {
    idle: [{ clip: "sit_idle" }],
    executing: [{ clip: "walk" }],
    success: [{ clip: "jump" }],
  },
  fallbacks: { idle: ["walk"] },
};

describe("animal motion resolution", () => {
  it("用配置选择抽象动作，而不是把猫狗名写死在前端", () => {
    expect(resolveAnimalClip(config, "idle", ["sit_idle", "walk"])).toBe("sit_idle");
    expect(resolveAnimalClip(config, "executing", ["walk", "run"])).toBe("walk");
  });

  it("固定动作缺 clip 时不会回退成移动动作", () => {
    expect(resolveAnimalClip(config, "idle", ["walk"])).toBeNull();
    expect(resolveAnimalClip(config, "unknown", ["walk"])).toBeNull();
    expect(resolveAnimalClip(config, "idle", [])).toBeNull();
  });

  it("固定动作的主候选也不能直接配置成移动动作", () => {
    const locomotionOnly = {
      actions: { idle: [{ clip: "walk" }], success: [{ clip: "run" }] },
    } as unknown as AnimalMotionConfig;

    expect(resolveAnimalClip(locomotionOnly, "idle", ["walk", "idle"])).toBe("idle");
    expect(resolveAnimalClip(locomotionOnly, "success", ["run"])).toBeNull();
    expect(resolveAnimalClip(config, "executing", ["run", "walk"])).toBe("walk");
  });

  it("识别配置里尚未补上资产的 trigger", () => {
    expect(animalMotionMetrics(config, ["idle", "click"]).missing).toContain("click");
    expect(animalMotionMetrics(config, ["idle", "executing", "success"]).resolved).toBe(true);
  });

  it("兼容旧式单对象和字符串动作配置", () => {
    const legacy = {
      actions: {
        idle: { clip: "sit_idle" },
        executing: ["walk", { clip: "run", weight: 0.5 }],
      },
      fallbacks: { idle: { clip: "walk" } },
    } as unknown as AnimalMotionConfig;

    expect(resolveAnimalClip(legacy, "idle", ["sit_idle", "walk"])).toBe("sit_idle");
    expect(resolveAnimalClip(legacy, "executing", ["walk", "run"])).toBe("walk");
    expect(resolveAnimalClip(legacy, "missing", ["run"])).toBeNull();
    expect(animalMotionMetrics(legacy, ["idle", "executing"])).toEqual({
      missing: [],
      resolved: true,
    });
  });

  it("残缺动作配置不会让前端解析抛错", () => {
    const broken = {
      actions: {
        idle: { clip: 42 },
        executing: [{ weight: 1 }, null],
      },
      fallbacks: { idle: [null, { clip: "walk" }] },
    } as unknown as AnimalMotionConfig;

    expect(resolveAnimalClip(broken, "idle", ["walk", "run"])).toBeNull();
    expect(animalMotionMetrics(broken, ["idle", "executing"]).missing).toEqual([
      "idle",
      "executing",
    ]);
  });
});
