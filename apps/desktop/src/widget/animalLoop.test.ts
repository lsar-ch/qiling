import { describe, expect, it } from "vitest";

import {
  IDLE_CYCLE_DWELL_MS,
  SIT_IDLE_DWELL_MARGIN_MS,
  animalLoopModeFor,
  animalTimeScaleFor,
  idleCycleDwellMs,
} from "./AnimalStage";
import * as THREE from "three";

describe("animal loop mode", () => {
  it("walk/run 单向前进，必须 LoopRepeat", () => {
    expect(animalLoopModeFor("executing", "walk")).toBe(THREE.LoopRepeat);
    expect(animalLoopModeFor("executing", "run")).toBe(THREE.LoopRepeat);
    // gait 路径会把 gait 名当作第一个参数传入，也必须保持循环
    expect(animalLoopModeFor("walk", "walk")).toBe(THREE.LoopRepeat);
  });

  it("one-shot 动作只播一次", () => {
    expect(animalLoopModeFor("success", "jump")).toBe(THREE.LoopOnce);
  });

  it("闲置/坐姿等循环动作原地单向循环，不往返倒放", () => {
    for (const clip of ["sit_idle", "idle_tail", "pose_sit_tall", "sleep", "idle"]) {
      expect(animalLoopModeFor("idle", clip)).toBe(THREE.LoopRepeat);
      expect(animalLoopModeFor("idle", clip)).not.toBe(THREE.LoopPingPong);
    }
  });

  it("只放慢 idle_tail 以匹配 Blender 24fps 下的 86 帧周期", () => {
    expect(animalTimeScaleFor("idle_tail")).toBeCloseTo(68 / 86);
    expect(animalTimeScaleFor("sit_idle")).toBe(1);
    expect(animalTimeScaleFor("walk", "run")).toBe(1.35);
  });
});

describe("idle 轮播展示时长", () => {
  const clips = [
    new THREE.AnimationClip("idle", 5.2917, []),
    new THREE.AnimationClip("sit_idle", 4.8, []), // v5：按 v17 轨迹重建并拉长到 4.8s
    new THREE.AnimationClip("idle_tail", 2.8333, []),
  ];

  it("sit_idle 完整播完一遍才切换，且留出 crossFade / 节流余量", () => {
    expect(idleCycleDwellMs(clips, "sit_idle")).toBe(4800 + SIT_IDLE_DWELL_MARGIN_MS);
    expect(idleCycleDwellMs(clips, "sit_idle")).toBeGreaterThan(IDLE_CYCLE_DWELL_MS);
  });

  it("其余 clip 保持既定轮播节奏，不受 sit_idle 影响", () => {
    for (const name of ["idle", "idle_tail", "sleep", "walk"]) {
      expect(idleCycleDwellMs(clips, name)).toBe(IDLE_CYCLE_DWELL_MS);
    }
  });

  it("缺 clip 或时长非法时安全回退到默认展示时长", () => {
    expect(idleCycleDwellMs([], "sit_idle")).toBe(IDLE_CYCLE_DWELL_MS);
    expect(idleCycleDwellMs([new THREE.AnimationClip("sit_idle", 0, [])], "sit_idle"))
      .toBe(IDLE_CYCLE_DWELL_MS);
  });

  it("资产再次改长度时无需手改常量", () => {
    const longer = [new THREE.AnimationClip("sit_idle", 5, [])];
    expect(idleCycleDwellMs(longer, "sit_idle")).toBe(5000 + SIT_IDLE_DWELL_MARGIN_MS);
  });
});
