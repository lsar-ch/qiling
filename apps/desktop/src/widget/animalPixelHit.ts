export type PointerSampleRequest = {
  requestId: number;
  x: number;
  y: number;
};

export type PointerPixelContext = Pick<
  WebGLRenderingContext,
  "drawingBufferWidth" | "drawingBufferHeight" | "isContextLost" | "readPixels" | "RGBA" | "UNSIGNED_BYTE"
>;

/** Unknown, stale, or unreadable pixels stay interactive; only a clear alpha miss passes through. */
export function samplePointerPixelOpaque(
  gl: PointerPixelContext,
  rect: Pick<DOMRect, "left" | "top" | "width" | "height">,
  x: number,
  y: number,
  threshold = 10,
): boolean {
  const { drawingBufferWidth: bufferWidth, drawingBufferHeight: bufferHeight } = gl;
  if (
    gl.isContextLost()
    || !Number.isFinite(x)
    || !Number.isFinite(y)
    || rect.width <= 0
    || rect.height <= 0
    || bufferWidth <= 0
    || bufferHeight <= 0
  ) return true;

  const pixelX = Math.floor(((x - rect.left) / rect.width) * bufferWidth);
  const pixelY = Math.floor(bufferHeight - 1 - ((y - rect.top) / rect.height) * bufferHeight);
  if (pixelX < 0 || pixelY < 0 || pixelX >= bufferWidth || pixelY >= bufferHeight) return true;

  const pixel = new Uint8Array(4);
  try {
    gl.readPixels(pixelX, pixelY, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
  } catch {
    return true;
  }
  return pixel[3] >= threshold;
}
