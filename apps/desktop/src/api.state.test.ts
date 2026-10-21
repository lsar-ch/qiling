import { describe, expect, it } from "vitest";

import { eventToState } from "./api";

// 回归护栏：speech.stopped 是播报收尾事件，后端 state_mapper 会把它映射成 idle。
// 前端漏掉这条映射时，事件会被当成未知类型丢弃，widget_state 永远停在 speaking，
// 表现就是「语音早就播完了，角色还在循环说话动作」。
describe("eventToState", () => {
  it("播报开始/结束要成对映射", () => {
    expect(eventToState("conversation.response")).toBe("speaking");
    expect(eventToState("speech.stopped")).toBe("idle");
  });

  it("其它收尾事件仍然有效", () => {
    expect(eventToState("speech.interrupted")).toBe("interrupted");
    expect(eventToState("conversation.completed")).toBe("completed");
  });

  it("未知事件返回 null（由调用方忽略）", () => {
    expect(eventToState("something.unknown")).toBeNull();
  });
});
