// 角色契约 —— 镜像自 qiling_contracts/character.py（Step 10 形象定制预留）。

export type CharacterStyle = "2d_static" | "2d_animated" | "lip_sync" | "live2d" | "3d";
export type AvatarDriver = "procedural_2d" | "video_stream" | "vrm_3d";
export type MotionFamily = "human" | "animal" | "anime";
export type ArtStyle = "realistic" | "anime" | "chibi" | "pixel";

export interface CharacterConfig {
  id: string;
  name: string;
  style: CharacterStyle;
  motion_family: MotionFamily;
  art_style: ArtStyle | null;
  avatar_driver: AvatarDriver;
  avatar_asset: string;
  animation_set: string;
  lip_sync_model: string | null;
  training_status: string;
  training_progress: number;
  reference_images: string[];
  voice_match: string | null;
}
