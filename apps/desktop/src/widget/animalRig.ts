import * as THREE from "three";

/** 当前运行时需要的最小四足规范骨骼。离线 retarget 会先转成这些名。 */
export const ANIMAL_CANONICAL_BONES = [
  "Root",
  "Spine",
  "Spine1",
  "Spine2",
  "Head",
  "Snout",
  "FrontLeg",
  "FrontLeg.L",
  "FrontPaw",
  "FrontPaw.L",
  "BackLeg",
  "BackLeg.L",
  "BackPaw",
  "BackPaw.L",
  "Tail",
  "Tail1",
  "Tail2",
] as const;

export interface AnimalRig {
  mixer: THREE.AnimationMixer;
  model: THREE.Object3D;
  bones: Record<string, THREE.Bone>;
}

export function buildAnimalRig(
  model: THREE.Object3D,
  mixer: THREE.AnimationMixer,
): AnimalRig {
  let skeleton: THREE.Skeleton | undefined;
  model.traverse((object) => {
    if (!skeleton && object instanceof THREE.SkinnedMesh && object.skeleton) {
      skeleton = object.skeleton;
    }
  });
  if (!skeleton) throw new Error("动物 GLB 没有可用骨骼");
  const bones: Record<string, THREE.Bone> = {};
  for (const name of ANIMAL_CANONICAL_BONES) {
    const bone = skeleton.bones.find((item) => item.name === name);
    if (bone) bones[name] = bone;
  }
  return { mixer, model, bones };
}
