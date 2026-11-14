// 角色契约 —— 镜像自 qiling_contracts/character.py（Step 10 形象定制预留）。

export type CharacterStyle = "2d_static" | "2d_animated" | "lip_sync" | "live2d" | "3d";
export type AvatarDriver = "procedural_2d" | "video_stream" | "vrm_3d" | "glb_animal_3d";
export type MotionFamily = "human" | "animal" | "anime";
export type ArtStyle = "realistic" | "anime" | "chibi" | "pixel";

/** 运行时 retarget 只认抽象动作名，不把猫/狗写死进前端。 */
export type AnimalActionName =
  | "idle" | "walk" | "run" | "jump" | "crouch" | "tap_paw"
  | "sit_idle" | "sleep" | "blink_l" | "blink_r" | "ear_forward_l" | "ear_forward_r"
  | "lick_paw" | "stretch" | "ear_twitch";

export interface AnimalMotionAction {
  clip: AnimalActionName;
  repeat?: number;
  timeScale?: number;
  /** 多候选按权重随机；同一角色可复用同一套猫狗动作。 */
  weight?: number;
  cooldownMs?: number;
}

export interface AnimalMotionConfig {
  /** GLB 文件相对角色资产目录的路径；换猫/狗模型时由角色卡提供。 */
  model: string;
  motionSet: string;
  loopTriggers?: string[];
  blendMs?: number;
  walkSwitchMs?: number;
  runSwitchMs?: number;
  /** 缺失动作的抽象回退链，值仍是 AnimalActionName。 */
  fallbacks?: Partial<Record<string, AnimalActionName[]>>;
  /** trigger 名称 → 动作候选；猫狗共用。 */
  actions: Record<string, AnimalMotionAction[]>;
}

export interface CharacterConfig {
  id: string;
  name: string;
  style: CharacterStyle;
  motion_family: MotionFamily;
  art_style: ArtStyle | null;
  avatar_driver: AvatarDriver;
  avatar_asset: string;
  motion_set: string;
  animation_set: string;
  lip_sync_model: string | null;
  training_status: string;
  training_progress: number;
  reference_images: string[];
  voice_match: string | null;
}
