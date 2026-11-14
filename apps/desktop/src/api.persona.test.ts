import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchActivePersonaAsset } from "./api";

const presentation = {
  persona_id: "pet_cat_walk_test",
  persona_name: "行走测试猫",
  style: "animal",
  motion_family: "animal",
  art_style: "realistic",
  theme: { primary: "#6366F1", aura: "#818CF8", accent: "#C4B5FD" },
  animations: {
    breath_rate: 1,
    blink_interval_ms: 4000,
    idle_action_interval_ms: 8000,
    transition_ms: 300,
  },
  fx: { thinking_bubble: true, music_note: false, success_sparkle: true },
  animal: { model: "model.glb", actions: {}, fallbacks: {} },
  asset: { avatar_url: "/avatar.png", glb_path: "model.glb" },
};

describe("fetchActivePersonaAsset", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("冷启动直接取得活动角色 presentation 和 GLB 路径", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/settings")) {
        return Response.json({ active_persona_id: "pet_cat_walk_test" });
      }
      if (url.endsWith("/api/personas/pet_cat_walk_test/presentation")) {
        return Response.json(presentation);
      }
      if (url.endsWith("/api/personas/pet_cat_walk_test/asset-manifest")) {
        return Response.json({ width: 512, height: 512, content_bbox: [1, 2, 3, 4] });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const asset = await fetchActivePersonaAsset();

    expect(asset.presentation.asset?.glb_path).toBe("model.glb");
    expect(asset.glb).toBe(true);
    expect(asset.personaId).toBe("pet_cat_walk_test");
    expect(asset.contentBbox).toEqual([1, 2, 3, 4]);
  });

  it("首次请求失败后自动重试", async () => {
    let settingsCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/settings")) {
        settingsCalls += 1;
        if (settingsCalls === 1) throw new TypeError("temporary network failure");
        return Response.json({ active_persona_id: "pet_cat_walk_test" });
      }
      if (url.endsWith("/api/personas/pet_cat_walk_test/presentation")) {
        return Response.json(presentation);
      }
      if (url.endsWith("/api/personas/pet_cat_walk_test/asset-manifest")) {
        return Response.json({ width: 512, height: 512, content_bbox: null });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const asset = await fetchActivePersonaAsset();

    expect(settingsCalls).toBe(2);
    expect(asset.presentation.asset?.glb_path).toBe("model.glb");
  });
});
