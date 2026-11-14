import { describe, expect, it } from "vitest";

import petMotion from "../../../../data/persona-assets/pet_cat_walk_test/animal-motion.json";
import petManifest from "../../../../data/persona-assets/pet_cat_walk_test/manifest.json";

import { resolveAnimalClip } from "./animalMotion";
import { bridgeClipFor } from "./animalTransition";

// 用 Vite 原生 JSON 导入，不再依赖 node:fs / __dirname（桌面端 tsconfig 不含 Node 类型）。
// 仅校验冻结进 v0.2 的 pet_cat_walk_test；cat_clean_v1 等实验版本已归档到 assets/personas/bluecat/，不随版本库提交。
const CONFIGS = {
  pet_cat_walk_test: { motion: petMotion, manifest: petManifest },
};
const PERSONAS = Object.keys(CONFIGS) as (keyof typeof CONFIGS)[];

const TRIGGERS = [
  "idle", "listening", "thinking", "speaking", "executing", "awaiting_approval",
  "success", "error", "click", "project", "hover",
] as const;

describe.each(PERSONAS)("persona %s 的配置与 GLB 清单一致", (persona) => {
  const motion: Record<string, unknown> = CONFIGS[persona].motion;
  const manifest: Record<string, unknown> = CONFIGS[persona].manifest;
  const clips = (manifest.clips as { clip: string }[]).map((item) => item.clip);
  const actions = motion.actions as Record<string, unknown>;

  it("11 个 trigger 全部有配置，且都能解析到 GLB 里存在的 clip", () => {
    for (const trigger of TRIGGERS) {
      expect(actions[trigger], `缺 trigger: ${trigger}`).toBeTruthy();
      const clip = resolveAnimalClip(motion as never, trigger, clips);
      expect(clip, `无法解析 ${trigger}`).not.toBeNull();
      expect(clips).toContain(clip as string);
    }
  });

  it("占位动作已全部替换为语义 clip", () => {
    const resolved = Object.fromEntries(
      TRIGGERS.map((trigger) => [trigger, resolveAnimalClip(motion as never, trigger, clips)]),
    );
    expect(resolved.listening).toBe("head_look");
    expect(resolved.thinking).toBe("think_sit");
    expect(resolved.speaking).toBe("speak_sit");
    expect(resolved.success).toBe("jump_once");
    expect(resolved.error).toBe("crouch_once");
    expect(resolved.click).toBe("tap_paw_once");
    expect(resolved.idle).toBe("sit_idle");
    expect(resolved.executing).toBe("walk");
  });

  it("walk / run 只被 executing / project 解析出来", () => {
    for (const trigger of TRIGGERS) {
      const clip = resolveAnimalClip(motion as never, trigger, clips);
      if (clip === "walk" || clip === "run") {
        expect(["executing", "project"]).toContain(trigger);
      }
    }
  });

  it("idleCycle 引用的 clip 全部在 GLB 里", () => {
    const cycle = (motion.idleCycle as string[]) ?? [];
    expect(cycle.length).toBeGreaterThan(0);
    for (const clip of cycle) expect(clips).toContain(clip);
  });

  it("空闲 → 行走 → 空闲 的过渡链正确插入桥接", () => {
    const idle = resolveAnimalClip(motion as never, "idle", clips);
    const walk = resolveAnimalClip(motion as never, "executing", clips);
    const back = resolveAnimalClip(motion as never, "thinking", clips);
    expect(bridgeClipFor(idle, walk, clips)).toBe("stand_up");
    expect(bridgeClipFor(walk, back, clips)).toBe("sit_down");
    // 坐姿内部切换不额外插过渡
    expect(bridgeClipFor(idle, back, clips)).toBeNull();
  });

  it("manifest 覆盖 33 条 clip 且 root_motion 全为原地", () => {
    expect(manifest.clipCount).toBe(33);
    const rows = manifest.clips as { root_motion: string; skeleton_id: string; source: string; license: string }[];
    for (const row of rows) {
      expect(row.root_motion).toBe("in_place");
      expect(row.source.length).toBeGreaterThan(0);
      expect(row.license.length).toBeGreaterThan(0);
      expect(row.skeleton_id).toMatch(/^sha256:[0-9a-f]{32}$/);
    }
  });

  it("sit_idle 时长与 v5 定稿一致（4.8s / 按 v17 轨迹重建），轮播才能完整播完", () => {
    const rows = manifest.clips as { clip: string; duration_s: number }[];
    const sit = rows.find((row) => row.clip === "sit_idle");
    expect(sit?.duration_s).toBeCloseTo(4.8, 4);
    expect((manifest.glb as { file: string }).file).toBe("model.glb");
  });
});
