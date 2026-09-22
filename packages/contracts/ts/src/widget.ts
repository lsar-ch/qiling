// 挂件状态契约 —— 镜像自 deskmate_contracts/widget.py。
import type { ArtStyle, MotionFamily } from "./character";

export type PersonaStyle = MotionFamily;

export type WidgetState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "executing"
  | "awaiting_approval"
  | "completed"
  | "interrupted";

export interface WidgetStatusReport {
  report_id: string;
  state: WidgetState;
  task_id: string | null;
  message: string | null;
  timestamp: string;
}

export interface PersonaPresentation {
  persona_id: string;
  persona_name: string;
  style: PersonaStyle;
  motion_family: MotionFamily;
  art_style: ArtStyle | null;
  theme: Record<string, string>;
  animations: Record<string, number>;
  fx: Record<string, boolean>;
  asset: Record<string, unknown> | null;
}
