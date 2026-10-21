#!/usr/bin/env python3
"""CMU FBX 动作重定向到角色 VRM 并导出 VRMA（Blender 无头）。

用法：
    /Applications/Blender.app/Contents/MacOS/Blender -b --python scripts/vrm/cmu_retarget.py -- \
        --model data/persona-assets/qiling/model.vrm \
        --motion /tmp/cmu_141_16.fbx --out /tmp/out/wave.vrma --skip-first-frame

重定向策略：rest 空间 delta 迁移——源骨相对自身 rest 的世界旋转增量，
原样套到 VRM 骨的 rest 世界上（两者 rest 均 T-pose，比例差由骨链吸收）。
只映射躯干/四肢 18 骨；手指/upperChest/脚趾等缺失骨保持静止，
如 check_vrma.mjs 要求满 52 骨再用 normalize_vrma.py 补。
"""
from __future__ import annotations

import argparse
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from normalize_vrma import parse_glb

# 源（MotionBuilder 风格 CMU 骨名）→ VRM 1.0 humanoid 骨名
BONE_MAP = {
    "hip": "hips",
    "abdomen": "spine",
    "chest": "chest",
    "neck": "neck",
    "head": "head",
    "lCollar": "leftShoulder",
    "rCollar": "rightShoulder",
    "lShldr": "leftUpperArm",
    "rShldr": "rightUpperArm",
    "lForeArm": "leftLowerArm",
    "rForeArm": "rightLowerArm",
    "lHand": "leftHand",
    "rHand": "rightHand",
    "lThigh": "leftUpperLeg",
    "rThigh": "rightUpperLeg",
    "lShin": "leftLowerLeg",
    "rShin": "rightLowerLeg",
    "lFoot": "leftFoot",
    "rFoot": "rightFoot",
}


def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--motion", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--skip-first-frame", action="store_true",
                   help="跳过源 Action 第1帧，规避 Blender 导出的绑定姿态首帧跳变")
    return p.parse_args(argv)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parse_args(argv)
    # VRM 1.0 文件自带 humanoid 映射（规范化骨名 → 节点名），比 addon 内部属性稳
    doc, _ = parse_glb(__import__("pathlib").Path(args.model).read_bytes())
    human_bones = doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    raw_name = {
        name: doc["nodes"][spec["node"]]["name"]
        for name, spec in human_bones.items()
    }
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.view.language = "en_US"
    bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")

    bpy.ops.import_scene.vrm(filepath=args.model)
    vrm_arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=args.motion)
    src_arm = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o not in before)

    pairs = []
    for src_name, vrm_name in BONE_MAP.items():
        sb = src_arm.pose.bones.get(src_name)
        vb = vrm_arm.pose.bones.get(raw_name.get(vrm_name, ""))
        if sb and vb:
            pairs.append((sb, vb))
    print("映射 %d 骨" % len(pairs))

    src_rest = {sb.name: Matrix(sb.bone.matrix_local.copy()) for sb, _ in pairs}
    vrm_rest = {vb.name: Matrix(vb.bone.matrix_local.copy()) for _, vb in pairs}

    action = src_arm.animation_data.action
    f0, f1 = int(action.frame_range[0]), int(action.frame_range[1])
    if args.skip_first_frame:
        f0 += 1
        if f0 > f1:
            raise SystemExit("跳过第1帧后没有可导出的动作帧")
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = f0, f1

    scale = 1.0
    sl, vl = src_arm.data.bones.get("lThigh"), vrm_arm.data.bones.get("leftUpperLeg")
    if sl and vl:
        scale = vl.length / sl.length

    hips_src = src_arm.pose.bones.get("hip")
    hips_vrm = vrm_arm.pose.bones.get("hips")

    for frame in range(f0, f1 + 1):
        bpy.context.scene.frame_set(frame)
        for sb, vb in pairs:
            if vb.name == "hips":
                continue
            delta = (src_rest[sb.name].inverted() @ sb.matrix).to_3x3()
            vb.matrix = vrm_rest[vb.name].to_3x3().to_4x4() @ delta.to_4x4()
            vb.keyframe_insert("rotation_quaternion" if vb.rotation_mode == "QUATERNION" else "rotation_euler", frame=frame)
        if hips_src is not None and hips_vrm is not None:
            delta = src_rest["hip"].inverted() @ hips_src.matrix
            hips_vrm.matrix = vrm_rest["hips"].to_3x3().to_4x4() @ delta.to_3x3().to_4x4()
            hips_vrm.location = hips_vrm.location + hips_vrm.bone.matrix_local.inverted().to_3x3() @ (delta.translation * scale)
            hips_vrm.keyframe_insert("rotation_quaternion" if hips_vrm.rotation_mode == "QUATERNION" else "rotation_euler", frame=frame)
            hips_vrm.keyframe_insert("location", frame=frame)
        bpy.context.view_layer.update()

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = vrm_arm
    vrm_arm.select_set(True)
    if bpy.ops.export_scene.vrma(filepath=args.out) != {"FINISHED"}:
        raise SystemExit("导出 VRMA 失败：%s" % args.out)
    print("导出 %s（帧 %d-%d）" % (args.out, f0, f1))


if __name__ == "__main__":
    main()
