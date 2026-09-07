// 语音契约 —— 镜像自 deskmate_contracts/voice.py。

export type VoiceProvider =
  | "auto"
  | "dashscope"
  | "minimax"
  | "volcengine"
  | "disabled";

export interface VoiceParams {
  voice: string | null;
  speed: number;
  pitch: number;
  volume: number;
  emotion: string | null;
  instruction: string | null;
  language: string;
}

export interface VoiceSettings {
  enabled: boolean;
  stt_provider: string;
  stt_model: string;
  tts_provider: string;
  tts_model: string;
  default_voice: string;
  params: VoiceParams;
  interruption_enabled: boolean;
  auto_barge_in: boolean;
}
