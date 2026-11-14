import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchPersonas } from "./api.ts";

describe("fetchPersonas", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults missing legacy fields and keeps valid values", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({
      items: [
        { id: "legacy-missing" },
        { id: "legacy-null", personality: null, avatar: null },
        { id: "configured", personality: ["可靠"], avatar: "/avatar.png" },
      ],
    })));

    const personas = await fetchPersonas();

    expect(personas.map(({ personality, avatar }) => [personality, avatar])).toEqual([
      [[], ""],
      [[], ""],
      [["可靠"], "/avatar.png"],
    ]);
  });
});
