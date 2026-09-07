// 常开语音监听：能量 VAD 自动断句 → 16k 单声道 WAV。
// 参数与 apps/web 保持一致，后续统一为全双工语音时再收敛共享包。

function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (offset: number, text: string): void => {
    for (let i = 0; i < text.length; i++) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export interface AlwaysListenSegment {
  wav: Blob;
  startedAt: number;
}

export interface AlwaysListenCallbacks {
  onSegment: (segment: AlwaysListenSegment) => void;
  onUtteranceStart?: () => void;
  onReady?: () => void;
  onStop?: () => void;
  onError?: (message: string) => void;
}

export interface AlwaysListener {
  stop: () => void;
  resume: () => void;
  readonly running: boolean;
}

const START_RMS = 0.012;
const END_RMS = 0.007;
const SILENCE_MS = 650;
const MIN_SPEECH_MS = 400;
const MAX_SPEECH_MS = 12000;
const START_HOLD_MS = 90;

function rms(chunk: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
  return Math.sqrt(sum / chunk.length);
}

async function buildWav(samples: Float32Array, sourceRate: number): Promise<Blob> {
  const targetRate = 16000;
  if (sourceRate === targetRate) return encodeWav(samples, targetRate);
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
  callbacks: AlwaysListenCallbacks,
  sharedCtx?: AudioContext,
): Promise<AlwaysListener | null> {
  if (!navigator.mediaDevices?.getUserMedia || typeof AudioContext === "undefined") {
    callbacks.onError?.("当前环境不支持常开监听，请用文字输入");
    return null;
  }
  if (typeof AudioContext.prototype.createScriptProcessor === "undefined") {
    callbacks.onError?.("当前环境不支持能量监听，请用文字输入");
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
    callbacks.onError?.("无法访问麦克风，请在系统设置中授权后重试");
    return null;
  }

  const ownsCtx = !sharedCtx;
  const ctx = sharedCtx ?? new AudioContext();
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
        if (running && wav.size > 44) callbacks.onSegment({ wav, startedAt });
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
          callbacks.onUtteranceStart?.();
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

    if (
      speechMs >= MAX_SPEECH_MS ||
      (silentMs >= SILENCE_MS && speechMs >= MIN_SPEECH_MS)
    ) {
      emitSegment();
    }
  };

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
    stream.getTracks().forEach((track) => track.stop());
    callbacks.onStop?.();
  };

  callbacks.onReady?.();
  return { stop, resume, running: true };
}
