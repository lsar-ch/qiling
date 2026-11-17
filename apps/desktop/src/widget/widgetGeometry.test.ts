import { describe, expect, it } from "vitest";
import { bubbleHeightForWindow, widgetHeightForBubble } from "./widgetGeometry";

describe("widget bubble geometry", () => {
  it("reserves the measured missing space after a compact window or a scale change", () => {
    expect(widgetHeightForBubble(380, 386, -44)).toBe(438);
    expect(widgetHeightForBubble(480, 486, 27)).toBe(480);
    expect(widgetHeightForBubble(480, 486, 2)).toBe(492);
  });

  it("does not grow again after the bubble reaches the top margin", () => {
    expect(widgetHeightForBubble(380, 438, 8)).toBe(438);
    expect(widgetHeightForBubble(480, 700, null)).toBe(480);
  });

  it("limits a scrollable bubble to the height available on a smaller monitor", () => {
    expect(bubbleHeightForWindow(700, 405)).toBe(287);
    expect(bubbleHeightForWindow(900, 405)).toBe(378);
    expect(bubbleHeightForWindow(400, 405)).toBe(35);
  });
});
