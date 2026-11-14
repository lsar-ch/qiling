import { describe, expect, it } from "vitest";
import * as THREE from "three";

import { prepareVrmClip } from "./vrmMotion";

describe("VRM motion preparation", () => {
  it("A-pose 手臂保留相对摆动，实时口型不再被 VRMA 覆盖", () => {
    const base = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -1.2);
    const swing = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.2);
    const end = base.clone().multiply(swing);
    const arm = new THREE.QuaternionKeyframeTrack("LeftArm.quaternion", [0, 1], [...base.toArray(), ...end.toArray()]);
    const spine = new THREE.QuaternionKeyframeTrack("Spine.quaternion", [0, 1], [0, 0, 0, 1, 0, 0, 0.1, 0.995]);
    const mouth = new THREE.NumberKeyframeTrack("VRMExpression_aa.weight", [0, 1], [0, 1]);
    const clip = prepareVrmClip(new THREE.AnimationClip("test", 1, [arm, spine, mouth]), true);

    expect(clip.tracks.map((track) => track.name)).toEqual(["LeftArm.quaternion", "Spine.quaternion"]);
    const values = clip.tracks[0].values;
    expect(new THREE.Quaternion().fromArray(values, 0).angleTo(new THREE.Quaternion())).toBeLessThan(1e-6);
    expect(new THREE.Quaternion().fromArray(values, 4).angleTo(swing)).toBeLessThan(1e-6);
    expect(clip.tracks[1]).toBe(spine);
  });
});
