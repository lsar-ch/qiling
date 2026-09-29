/**
 * 音乐感知→节奏动画：检测系统音频低频能量，驱动角色微脉动
 * 
 * 原理：
 * - 复用 lipSyncBus.analyser（TTS 播放时已激活）
 * - 周期性读取 20-200Hz 频段能量
 * - 超过阈值时写入 CSS 变量 --beat-pulse (0~1)
 * - 低能量持续 2 秒后归零
 */

import { lipSyncBus } from "./lipSync";

const FFT_SIZE = 256; // 频率分辨率足够检测低频
const SAMPLE_RATE = 44100; // 假设的采样率（实际由 AudioContext 决定）
const LOW_FREQ_BINS = 8; // 前 8 个 bin ≈ 20-200Hz（取决于采样率）
const BEAT_GATE = 0.15; // 能量阈值
const UPDATE_INTERVAL_MS = 33; // ~30Hz 更新频率
const SILENCE_RESET_MS = 2000; // 持续低能量 2 秒后归零
const PEAK_DECAY = 0.95; // 峰值衰减系数
const PULSE_DECAY = 0.85; // 脉动值衰减系数

let attached = false;
let intervalId: number | null = null;
let lastBeatTime = 0;
let peakEnergy = 0;
let currentPulse = 0;

function getLowFreqEnergy(analyser: AnalyserNode): number {
  const dataArray = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(dataArray);
  
  // 计算低频段平均能量
  let sum = 0;
  const binCount = Math.min(LOW_FREQ_BINS, dataArray.length);
  for (let i = 0; i < binCount; i++) {
    sum += dataArray[i] / 255; // 归一化到 0~1
  }
  return binCount > 0 ? sum / binCount : 0;
}

function updateBeatPulse(): void {
  const analyser = lipSyncBus.analyser;
  if (!analyser) return;

  const now = Date.now();
  const energy = getLowFreqEnergy(analyser);
  
  // 更新峰值（用于归一化）
  if (energy > peakEnergy) {
    peakEnergy = energy;
  } else {
    peakEnergy *= PEAK_DECAY;
  }
  
  // 归一化能量
  const normalizedEnergy = peakEnergy > 0.01 ? energy / peakEnergy : 0;
  
  if (normalizedEnergy > BEAT_GATE) {
    // 检测到节拍，设置脉动值
    currentPulse = normalizedEnergy;
    lastBeatTime = now;
    
    // 写入 CSS 变量
    document.documentElement.style.setProperty("--beat-pulse", currentPulse.toFixed(2));
  } else {
    // 能量低于阈值
    if (now - lastBeatTime > SILENCE_RESET_MS) {
      // 持续低能量超过 2 秒，归零
      currentPulse = 0;
      document.documentElement.style.setProperty("--beat-pulse", "0");
    } else {
      // 衰减脉动值
      currentPulse *= PULSE_DECAY;
      document.documentElement.style.setProperty("--beat-pulse", currentPulse.toFixed(2));
    }
  }
}

export function attachBeatDetect(): void {
  if (attached) return;
  attached = true;
  
  // 启动周期性检测
  intervalId = window.setInterval(updateBeatPulse, UPDATE_INTERVAL_MS);
}

export function detachBeatDetect(): void {
  if (!attached) return;
  attached = false;
  
  if (intervalId !== null) {
    window.clearInterval(intervalId);
    intervalId = null;
  }
  
  // 清理 CSS 变量
  document.documentElement.style.removeProperty("--beat-pulse");
}
