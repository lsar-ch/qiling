import { describe, expect, it } from "vitest";

import { animalFacingForDelta, animalYawForFacing } from "./animalFacing";

describe("animal facing", () => {
  it("把水平位移映射为左右朝向，小位移回到正面", () => {
    expect(animalFacingForDelta(-20)).toBe("left");
    expect(animalFacingForDelta(20)).toBe("right");
    expect(animalFacingForDelta(2)).toBe("front");
  });

  it("正面模型的左侧对应屏幕左侧，右侧对应屏幕右侧", () => {
    expect(animalYawForFacing("left")).toBeCloseTo(-Math.PI / 2);
    expect(animalYawForFacing("right")).toBeCloseTo(Math.PI / 2);
    expect(animalYawForFacing("front")).toBe(0);
  });
});
