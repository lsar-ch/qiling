import { describe, expect, it, vi } from "vitest";
import { samplePointerPixelOpaque, type PointerPixelContext } from "./animalPixelHit";

function context(alpha = 255): PointerPixelContext {
  return {
    drawingBufferWidth: 200,
    drawingBufferHeight: 100,
    isContextLost: () => false,
    RGBA: 0x1908,
    UNSIGNED_BYTE: 0x1401,
    readPixels: vi.fn((_x, _y, _width, _height, _format, _type, pixel) => {
      (pixel as Uint8Array)[3] = alpha;
    }),
  } as unknown as PointerPixelContext;
}

describe("samplePointerPixelOpaque", () => {
  it("maps CSS coordinates to drawing-buffer pixels and flips the Y axis", () => {
    const gl = context();

    expect(samplePointerPixelOpaque(gl, { left: 10, top: 20, width: 100, height: 50 }, 35, 30)).toBe(true);
    expect(gl.readPixels).toHaveBeenCalledWith(50, 79, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, expect.any(Uint8Array));
  });

  it("passes through only a readable transparent pixel", () => {
    expect(samplePointerPixelOpaque(context(0), { left: 0, top: 0, width: 200, height: 100 }, 50, 50)).toBe(false);
    expect(samplePointerPixelOpaque(context(10), { left: 0, top: 0, width: 200, height: 100 }, 50, 50)).toBe(true);
  });

  it("fails closed for out-of-bounds, lost, or unreadable pixels", () => {
    const gl = context(0);
    expect(samplePointerPixelOpaque(gl, { left: 0, top: 0, width: 200, height: 100 }, -1, 50)).toBe(true);
    expect(samplePointerPixelOpaque({ ...gl, isContextLost: () => true }, { left: 0, top: 0, width: 200, height: 100 }, 50, 50)).toBe(true);
    expect(samplePointerPixelOpaque({ ...gl, readPixels: () => { throw new Error("readback failed"); } }, { left: 0, top: 0, width: 200, height: 100 }, 50, 50)).toBe(true);
  });
});
