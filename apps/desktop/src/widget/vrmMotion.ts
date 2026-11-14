import * as THREE from "three";

const ARM_TRACK_RE = /(Arm|Hand|Shoulder|Thumb|Index|Middle|Ring|Little)/i;
const MOUTH_TRACK_RE = /(?:^|_)(?:aa|ih|ou|ee|oh)\.weight$/i;

interface HumanoidLike {
  getRawBoneNode(name: string): THREE.Object3D | null | undefined;
}

/** A-pose 上臂与竖直线夹角很小；调用方须先更新 world matrix。 */
export function isAPoseHumanoid(humanoid: HumanoidLike | null | undefined): boolean {
  const upper = humanoid?.getRawBoneNode("leftUpperArm");
  const lower = humanoid?.getRawBoneNode("leftLowerArm");
  if (!upper || !lower) return false;
  const arm = lower.getWorldPosition(new THREE.Vector3()).sub(upper.getWorldPosition(new THREE.Vector3())).normalize();
  const degrees = THREE.MathUtils.radToDeg(Math.acos(THREE.MathUtils.clamp(-arm.y, -1, 1)));
  return degrees < 45;
}

/**
 * VRMA 人类动作按 T-pose 首帧编码。A-pose 卡把手臂轨道重基到 identity，
 * 保留每帧相对首帧的摆动，避免把 T-pose 的 90° 基准再叠到模型自身上。
 * 口型轨道始终移除，由实时音频 RMS 独占 aa/ih/ou/ee/oh，避免两条驱动互相覆盖。
 */
export function prepareVrmClip(clip: THREE.AnimationClip, aPoseCard: boolean): THREE.AnimationClip {
  clip.tracks = clip.tracks
    .filter((track) => !MOUTH_TRACK_RE.test(track.name))
    .map((track) => {
      if (!aPoseCard || !ARM_TRACK_RE.test(track.name) || !track.name.endsWith(".quaternion") || track.getValueSize() !== 4) {
        return track;
      }

      const rebased = track.clone();
      const values = rebased.values;
      const reference = new THREE.Quaternion().fromArray(values, 0).normalize();
      const inverseReference = reference.clone().invert();
      const current = new THREE.Quaternion();
      const relative = new THREE.Quaternion();
      for (let offset = 0; offset < values.length; offset += 4) {
        current.fromArray(values, offset).normalize();
        relative.copy(inverseReference).multiply(current);
        values[offset] = relative.x;
        values[offset + 1] = relative.y;
        values[offset + 2] = relative.z;
        values[offset + 3] = relative.w;
      }
      return rebased;
    });
  return clip;
}
