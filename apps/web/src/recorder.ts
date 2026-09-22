// 麦克风录音工具：MediaRecorder 采集 → 解码重采样为 16k 单声道 WAV。
// 返回 null 表示浏览器不支持或用户拒绝授权，调用方自行降级提示。

export interface MicRecorder {
  stop: () => Promise<Blob | null>;
  cancel: () => void;
}

export const MIC_CONSTRAINTS: MediaStreamConstraints["audio"] = {
  channelCount: 1,
  echoCancellation: true,
  noiseSuppression: true,
};

// 挂件刚释放麦克风、系统尚未完成回收时，getUserMedia 会抛 NotReadableError
// （“另一程序在占用”）。权限类错误（NotAllowedError）不重试，立刻交还调用方提示授权。
export async function getUserMediaWithBusyRetry(
  constraints: MediaStreamConstraints["audio"],
  attempts = 6,
  delayMs = 250,
): Promise<MediaStream | null> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: constraints });
    } catch (err) {
      const name = err instanceof DOMException ? err.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") return null;
      if (attempt === attempts - 1) return null;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }
  return null;
}

export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (offset: number, text: string): void => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);            // PCM
  view.setUint16(22, 1, true);            // 单声道
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

export async function startRecording(): Promise<MicRecorder | null> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    return null;
  }
  const stream = await getUserMediaWithBusyRetry(MIC_CONSTRAINTS);
  if (!stream) return null;

  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", ""].find((m) =>
    m === "" ? true : MediaRecorder.isTypeSupported(m),
  );
  const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };
  recorder.start();

  const cleanup = (): void => {
    stream.getTracks().forEach((t) => t.stop());
  };

  return {
    cancel: () => {
      try {
        if (recorder.state !== "inactive") recorder.stop();
      } catch {
        /* 忽略 */
      }
      cleanup();
    },
    stop: async () => {
      const blobPromise = new Promise<Blob | null>((resolve) => {
        recorder.onstop = () => resolve(chunks.length > 0 ? new Blob(chunks) : null);
      });
      if (recorder.state !== "inactive") recorder.stop();
      cleanup();
      const recorded = await blobPromise;
      if (!recorded) return null;

      try {
        const arrayBuffer = await recorded.arrayBuffer();
        const context = new AudioContext();
        const audio = await context.decodeAudioData(arrayBuffer);
        void context.close();
        const targetRate = 16000;
        const length = Math.max(1, Math.ceil(audio.duration * targetRate));
        const offline = new OfflineAudioContext(1, length, targetRate);
        const source = offline.createBufferSource();
        source.buffer = audio;
        source.connect(offline.destination);
        source.start();
        const rendered = await offline.startRendering();
        return encodeWav(rendered.getChannelData(0), targetRate);
      } catch {
        return null; // 解码失败（格式不受支持）
      }
    },
  };
}
