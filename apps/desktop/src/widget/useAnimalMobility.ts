import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

import {
  createAnimalMobility,
  setAnimalTemporaryHome,
  shiftAnimalMobilityForResize,
  updateAnimalMobility,
  type AnimalFacing,
  type AnimalGait,
  type AnimalMobilityPhase,
  type AnimalMobilityState,
  type Point,
  type Rect,
} from "./animalMobility";

type WorkArea = [string, number, number, number, number];

interface UseAnimalMobilityOptions {
  enabled: boolean;
  taskActive: boolean;
  dragging: boolean;
}

interface AnimalMobilityOutput {
  gait: AnimalGait | null;
  facing: AnimalFacing;
  phase: AnimalMobilityPhase | null;
  adoptCurrentPosition: () => Promise<void>;
}

const FRAME_MS = 66;

function toRect([, x, y, width, height]: WorkArea): Rect {
  return { x, y, width, height };
}

function selectWorkArea(position: Point, size: { width: number; height: number }, areas: Rect[]): Rect | null {
  if (areas.length === 0) return null;
  const cx = position.x + size.width / 2;
  const cy = position.y + size.height / 2;
  const containing = areas.find(
    (area) =>
      cx >= area.x &&
      cx < area.x + area.width &&
      cy >= area.y &&
      cy < area.y + area.height,
  );
  if (containing) return containing;
  return areas.reduce((best, area) => {
    const distance = Math.hypot(
      Math.max(area.x - cx, 0, cx - (area.x + area.width)),
      Math.max(area.y - cy, 0, cy - (area.y + area.height)),
    );
    const bestDistance = Math.hypot(
      Math.max(best.x - cx, 0, cx - (best.x + best.width)),
      Math.max(best.y - cy, 0, cy - (best.y + best.height)),
    );
    return distance < bestDistance ? area : best;
  });
}

export function useAnimalMobility({
  enabled,
  taskActive,
  dragging,
}: UseAnimalMobilityOptions): AnimalMobilityOutput {
  const [output, setOutput] = useState<{
    gait: AnimalGait | null;
    facing: AnimalFacing;
    phase: AnimalMobilityPhase | null;
  }>({ gait: null, facing: "front", phase: null });
  const stateRef = useRef<AnimalMobilityState | null>(null);
  const workAreaRef = useRef<Rect | null>(null);
  const windowSizeRef = useRef<{ width: number; height: number }>({ width: 430, height: 480 });
  const optionsRef = useRef({ enabled, taskActive, dragging });
  const dragWasActiveRef = useRef(false);
  const outputRef = useRef(output);
  outputRef.current = output;

  optionsRef.current = { enabled, taskActive, dragging };

  const publish = useCallback((gait: AnimalGait | null, facing: AnimalFacing, phase: AnimalMobilityPhase | null) => {
    const current = outputRef.current;
    if (current.gait === gait && current.facing === facing && current.phase === phase) return;
    setOutput({ gait, facing, phase });
  }, []);

  const adoptCurrentPosition = useCallback(async (): Promise<void> => {
    const [position, size, rawAreas] = await Promise.all([
      getCurrentWindow().outerPosition(),
      getCurrentWindow().outerSize(),
      invoke<WorkArea[]>("list_desktop_work_areas"),
    ]);
    const areas = rawAreas.map(toRect);
    const workArea = selectWorkArea(position, size, areas);
    if (!workArea) return;
    const point = { x: position.x, y: position.y };
    stateRef.current = setAnimalTemporaryHome(
      stateRef.current ?? createAnimalMobility(point),
      point,
    );
    workAreaRef.current = workArea;
    windowSizeRef.current = { width: size.width, height: size.height };
    publish(null, "front", "home");
  }, [publish]);

  useEffect(() => {
    if (dragging) {
      dragWasActiveRef.current = true;
      if (stateRef.current) {
        stateRef.current = { ...stateRef.current, phase: "manual", target: null };
      }
      publish(null, "front", "manual");
      return;
    }
    if (!dragWasActiveRef.current) return;
    dragWasActiveRef.current = false;
    void adoptCurrentPosition().catch(() => {
      /* 下一阶段边界再校准 */
    });
  }, [adoptCurrentPosition, dragging]);

  useEffect(() => {
    if (!enabled) {
      stateRef.current = null;
      publish(null, "front", null);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastTickAt = performance.now();

    const loadGeometry = async (): Promise<boolean> => {
      const [position, size, rawAreas] = await Promise.all([
        getCurrentWindow().outerPosition(),
        getCurrentWindow().outerSize(),
        invoke<WorkArea[]>("list_desktop_work_areas"),
      ]);
      if (cancelled) return false;
      const areas = rawAreas.map(toRect);
      const workArea = selectWorkArea(position, size, areas);
      if (!workArea) return false;
      if (!stateRef.current) {
        stateRef.current = createAnimalMobility({ x: position.x, y: position.y });
      }
      workAreaRef.current = workArea;
      windowSizeRef.current = { width: size.width, height: size.height };
      return true;
    };

    const onResize = (): void => {
      void (async () => {
        const oldHeight = windowSizeRef.current.height;
        const size = await getCurrentWindow().outerSize().catch(() => null);
        if (cancelled || !size || size.height === oldHeight) return;
        const dy = oldHeight - size.height;
        windowSizeRef.current = { width: size.width, height: size.height };
        if (stateRef.current) {
          stateRef.current = shiftAnimalMobilityForResize(stateRef.current, dy);
        }
      })();
    };

    const tick = async (): Promise<void> => {
      if (cancelled) return;
      const state = stateRef.current;
      const workArea = workAreaRef.current;
      if (!state || !workArea) {
        timer = setTimeout(() => void tick(), 250);
        return;
      }
      const now = performance.now();
      const deltaMs = Math.min(250, Math.max(0, now - lastTickAt));
      lastTickAt = now;
      const current = optionsRef.current;
      const frame = updateAnimalMobility(state, {
        taskActive: current.taskActive && !current.dragging,
        dragging: current.dragging,
        deltaMs,
        nowMs: now,
        workArea,
        windowSize: windowSizeRef.current,
      });
      stateRef.current = frame.state;
      publish(frame.gait, frame.facing, frame.state.phase);
      if (frame.gait && (frame.position.x !== state.current.x || frame.position.y !== state.current.y)) {
        try {
          await invoke("move_widget_to", {
            x: Math.round(frame.position.x),
            y: Math.round(frame.position.y),
          });
        } catch {
          /* 移动失败停一帧，下一帧从本地状态继续 */
        }
      }
      if (!cancelled) timer = setTimeout(() => void tick(), FRAME_MS);
    };

    void loadGeometry().then((ready) => {
      if (!cancelled && ready) {
        lastTickAt = performance.now();
        timer = setTimeout(() => void tick(), 0);
      }
    });
    window.addEventListener("resize", onResize);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, [enabled, publish]);

  return {
    ...output,
    adoptCurrentPosition,
  };
}
