import { describe, expect, it } from "vitest";

import { demo as actionsDemo, pickAction, triggerFor } from "./actions";
import { demo as internalStateDemo } from "./internalState";

describe("triggerFor", () => {
  it("把 completed 映射到 success（T-pose 闪现的入口）", () => {
    expect(triggerFor("completed", "neutral")).toBe("success");
    expect(triggerFor("interrupted", "neutral")).toBe("idle");
  });

  it("emotion 优先于 state，error/happy 不被状态覆盖", () => {
    expect(triggerFor("idle", "error")).toBe("error");
    expect(triggerFor("executing", "success")).toBe("success");
    expect(triggerFor("idle", "happy")).toBe("success");
    expect(triggerFor("speaking", "sad")).toBe("error");
  });
});

describe("pickAction", () => {
  it("cooldown 未到时换一个动作，全部冷却中才返回 null", () => {
    const now = 10_000;
    const first = pickAction("human", "idle", {}, now, () => 0);
    expect(first).not.toBeNull();
    const next = pickAction("human", "idle", { [first!.id]: now }, now, () => 0);
    expect(next?.id).not.toBe(first!.id);
  });

  it("权重乘数能把选择压到唯一候选上", () => {
    const now = 10_000;
    const plain = pickAction("human", "idle", {}, now, () => 0.99);
    const forced = pickAction("human", "idle", {}, now, () => 0.99, (id) =>
      id === plain!.id ? 0.001 : 1,
    );
    expect(forced?.id).not.toBe(plain!.id);
  });

  it("idle 默认循环播放，其余触发默认单次", () => {
    expect(pickAction("human", "idle", {}, 0, () => 0)?.loop).toBe(true);
    expect(pickAction("human", "success", {}, 0, () => 0)?.loop).toBe(false);
  });
});

describe("模块自检 demo()", () => {
  it("动作表完整性 / 冷却 / 驱动权重边界仍成立", () => {
    expect(() => actionsDemo()).not.toThrow();
    expect(() => internalStateDemo()).not.toThrow();
  });
});
