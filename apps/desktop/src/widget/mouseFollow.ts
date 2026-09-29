/**
 * 鼠标视线跟随：角色眼球和头部微转向鼠标方向，产生"看着你"的互动感。
 *
 * 2D 模式：监听 window mousemove，写入 CSS 变量（rotate + translate）。
 * VRM 模式：通过回调把归一化方向向量传给 VrmStage，驱动 vrm.lookAt.target。
 * 鼠标静止 3 秒后回中。
 */

const MAX_ROTATE_DEG = 2;   // 整体旋转幅度 ±2°
const MAX_EYE_PX = 3;       // 眼球偏移 ±3px
const IDLE_RESET_MS = 3000; // 鼠标静止后回中的延迟

let attached = false;
let rafId: number | null = null;
let resetTimer: ReturnType<typeof setTimeout> | null = null;

// 待写入的最新鼠标坐标（rAF 节流用）
let pendingX = 0;
let pendingY = 0;
let pendingDirty = false;

// 外部回调：VRM 模式消费归一化方向向量
type FollowCallback = (dx: number, dy: number) => void;
const callbacks = new Set<FollowCallback>();

function getMascotWrap(): HTMLElement | null {
  return document.querySelector<HTMLElement>(".mascot-wrap");
}

function isVrmMode(): boolean {
  const root = document.querySelector<HTMLElement>(".w-root");
  return root?.dataset.vrm === "1";
}

function writeCssVars(wrap: HTMLElement, dx: number, dy: number): void {
  const rot = Math.max(-MAX_ROTATE_DEG, Math.min(MAX_ROTATE_DEG, dx * MAX_ROTATE_DEG));
  const ex = Math.max(-MAX_EYE_PX, Math.min(MAX_EYE_PX, dx * MAX_EYE_PX));
  const ey = Math.max(-MAX_EYE_PX, Math.min(MAX_EYE_PX, dy * MAX_EYE_PX * 0.6));
  wrap.style.setProperty("--mf-rotate", `${rot.toFixed(2)}deg`);
  wrap.style.setProperty("--mf-ey-x", `${ex.toFixed(1)}px`);
  wrap.style.setProperty("--mf-ey-y", `${ey.toFixed(1)}px`);
}

function resetCssVars(wrap: HTMLElement): void {
  wrap.style.setProperty("--mf-rotate", "0deg");
  wrap.style.setProperty("--mf-ey-x", "0px");
  wrap.style.setProperty("--mf-ey-y", "0px");
}

function flushFrame(): void {
  rafId = null;
  if (!pendingDirty) return;
  pendingDirty = false;

  const wrap = getMascotWrap();
  if (!wrap) return;

  const rect = wrap.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const refDist = Math.max(rect.width, 200);
  const dx = Math.max(-1, Math.min(1, (pendingX - cx) / refDist));
  const dy = Math.max(-1, Math.min(1, (pendingY - cy) / refDist));

  if (isVrmMode()) {
    // VRM 模式：不写 CSS 变量，通知回调（VrmStage 消费）
    for (const cb of callbacks) {
      try { cb(dx, dy); } catch { /* ignore */ }
    }
  } else {
    writeCssVars(wrap, dx, dy);
  }
}

function onMouseMove(e: MouseEvent): void {
  pendingX = e.clientX;
  pendingY = e.clientY;
  pendingDirty = true;

  if (rafId === null) {
    rafId = requestAnimationFrame(flushFrame);
  }

  if (resetTimer !== null) {
    clearTimeout(resetTimer);
  }
  resetTimer = setTimeout(() => {
    resetTimer = null;
    const wrap = getMascotWrap();
    if (wrap) {
      if (isVrmMode()) {
        for (const cb of callbacks) {
          try { cb(0, 0); } catch { /* ignore */ }
        }
      } else {
        resetCssVars(wrap);
      }
    }
  }, IDLE_RESET_MS);
}

export function attachMouseFollow(): void {
  if (attached) return;
  attached = true;
  window.addEventListener("mousemove", onMouseMove, { passive: true });
}

export function detachMouseFollow(): void {
  if (!attached) return;
  attached = false;
  window.removeEventListener("mousemove", onMouseMove);
  if (rafId !== null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  if (resetTimer !== null) {
    clearTimeout(resetTimer);
    resetTimer = null;
  }
  pendingDirty = false;
}

/** VRM 模式注册回调，接收归一化方向向量 dx/dy ∈ [-1, 1]。 */
export function onFollowUpdate(cb: FollowCallback): void {
  callbacks.add(cb);
}

export function offFollowUpdate(cb: FollowCallback): void {
  callbacks.delete(cb);
}
