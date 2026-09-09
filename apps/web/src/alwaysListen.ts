// 常开语音监听：能量 VAD 自动断句 → 16k 单声道 WAV。
// 说明：说话起音/结束由音量阈值判断；参数需真机试听后微调。

import { encodeWav } from "./recorder";

export interface AlwaysListenSegment {
  wav: Blob;
  startedAt: number; // 语音段开始时间（Date.now），用于区分「播报回采」
}

export interface AlwaysListenCallbacks {
  onSegment: (segment: AlwaysListenSegment) => void;
  onUtteranceStart?: () => void; // VAD 刚检测到起音（可用来即时打断播报）
  onReady?: () => void;
  onStop?: () => void;
  onError?: (message: string) => void;
}

export interface AlwaysListener {
  stop: () => void;
  resume: () => void;
  readonly running: boolean;
}

// VAD 阈值（RMS，0~1）。麦克风电平和环境噪音因人而异，先给经验默认值。
const START_RMS = 0.012; // 判定开始说话
const END_RMS = 0.007; // 低于该值累计为静音
const SILENCE_MS = 650; // 静音多久判定说完
const MIN_SPEECH_MS = 400; // 最短有效语音
const MAX_SPEECH_MS = 12000; // 单句上限，超时自动切段
const START_HOLD_MS = 90; // 起音需持续多久，避免瞬时噪音误触

function rms(chunk: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
  return Math.sqrt(sum / chunk.length);
}

async function buildWav(
  samples: Float32Array,
  sourceRate: number,
): Promise<Blob> {
  const targetRate = 16000;
  if (sourceRate === targetRate) {
    return encodeWav(samples, targetRate);
  }
  const length = Math.max(1, Math.round((samples.length * targetRate) / sourceRate));
  const offline = new OfflineAudioContext(1, length, targetRate);
  const buf = offline.createBuffer(1, samples.length, sourceRate);
  const copy = new Float32Array(samples.length);
  copy.set(samples);
  buf.copyToChannel(copy, 0);
  const src = offline.createBufferSource();
  src.buffer = buf;
  src.connect(offline.destination);
  src.start(0);
  const rendered = await offline.startRendering();
  return encodeWav(rendered.getChannelData(0), targetRate);
}

export async function startAlwaysListener(
  cb: AlwaysListenCallbacks,
  sharedCtx?: AudioContext,
): Promise<AlwaysListener | null> {
  if (!navigator.mediaDevices?.getUserMedia || typeof AudioContext === "undefined") {
    cb.onError?.("当前浏览器不支持常开监听，请用按键说话");
    return null;
  }
  if (typeof AudioContext.prototype.createScriptProcessor === "undefined") {
    cb.onError?.("当前浏览器不支持能量监听，请用按键说话");
    return null;
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch {
    cb.onError?.("无法访问麦克风（常开监听需要授权）");
    return null;
  }

  // 播放与采集共用同一 AudioContext（sharedCtx 由页面在用户手势后创建/唤醒），
  // 便于浏览器 AEC 取参考信号，也规避自动播放策略。
  const ownsCtx = !sharedCtx;
  const ctx = sharedCtx ?? new AudioContext();
  if (ctx.state === "closed") {
    // 共享 ctx 已被页面卸载清理：节点建在已关闭上下文上只会产生告警。
    stream.getTracks().forEach((t) => t.stop());
    cb.onError?.("音频会话已结束，请重新开启常开监听");
    return null;
  }

  const source = ctx.createMediaStreamSource(stream);
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  const silence = ctx.createGain();
  silence.gain.value = 0;
  source.connect(processor);
  processor.connect(silence);
  silence.connect(ctx.destination);

  const rate = ctx.sampleRate;
  const frameMs = (4096 / rate) * 1000;
  let running = true;
  let stopped = false;
  let state: "waiting" | "speech" = "waiting";
  let holdMs = 0;
  let speechMs = 0;
  let silentMs = 0;
  let parts: Float32Array[] = [];
  let partLen = 0;
  let utteranceStartAt = 0;

  const reset = (): void => {
    parts = [];
    partLen = 0;
    holdMs = 0;
    speechMs = 0;
    silentMs = 0;
    utteranceStartAt = 0;
    state = "waiting";
  };

  const emitSegment = (): void => {
    if (partLen < rate * 0.25) {
      reset();
      return;
    }
    const samples = new Float32Array(partLen);
    let offset = 0;
    for (const part of parts) {
      samples.set(part, offset);
      offset += part.length;
    }
    reset();
    const startedAt = utteranceStartAt || Date.now();
    const srcRate = rate;
    void buildWav(samples, srcRate)
      .then((wav) => {
        if (running && wav.size > 44) cb.onSegment({ wav, startedAt });
      })
      .catch(() => {
        /* 转换失败静默丢弃，避免打断监听 */
      });
  };

  processor.onaudioprocess = (event) => {
    if (!running) return;
    const data = event.inputBuffer.getChannelData(0);
    const level = rms(data);

    if (state === "waiting") {
      if (level > START_RMS) {
        holdMs += frameMs;
        if (holdMs >= START_HOLD_MS) {
          state = "speech";
          utteranceStartAt = Date.now();
          cb.onUtteranceStart?.();
          parts = [new Float32Array(data)];
          partLen = data.length;
          speechMs = frameMs;
          silentMs = 0;
        }
      } else {
        holdMs = 0;
      }
      return;
    }

    parts.push(new Float32Array(data));
    partLen += data.length;
    speechMs += frameMs;
    silentMs = level > END_RMS ? 0 : silentMs + frameMs;

    if (speechMs >= MAX_SPEECH_MS || (silentMs >= SILENCE_MS && speechMs >= MIN_SPEECH_MS)) {
      emitSegment();
    }
  };

  // 自动播放策略可能让 AudioContext 挂起：resume() 供用户交互后调用
  const resume = (): void => {
    if (!stopped && ctx.state === "suspended") {
      void ctx.resume().catch(() => {
        /* 用户未交互前可能失败，稍后再次 resume */
      });
    }
  };
  resume();

  const stop = (): void => {
    if (stopped) return;
    stopped = true;
    running = false;
    try {
      source.disconnect();
      processor.disconnect();
      silence.disconnect();
    } catch {
      /* 已断开 */
    }
    if (ownsCtx) {
      void ctx.close().catch(() => {
        /* 关闭失败忽略 */
      });
    }
    stream.getTracks().forEach((t) => t.stop());
    cb.onStop?.();
  };

  cb.onReady?.();
  return { stop, resume, running: true };
}
