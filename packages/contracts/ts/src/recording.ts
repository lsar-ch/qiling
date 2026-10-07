// 录制契约 —— 镜像自 qiling_contracts/recording.py（Step 10 接口预留）。

export type RecordingFormat =
  | "video/webm"
  | "video/mp4"
  | "audio/wav"
  | "audio/mpeg";

export type RecordingMode = "conversation" | "task_execution" | "digital_human";

export interface RecordingSession {
  session_id: string;
  conversation_id: string | null;
  task_id: string | null;
  mode: RecordingMode;
  format: RecordingFormat;
  started_at: string;
  ended_at: string | null;
  output_path: string | null;
  duration_s: number | null;
  metadata: Record<string, unknown>;
  status: string;
}
