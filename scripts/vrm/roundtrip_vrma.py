"""在 Blender 里改一条 VRMA 再导出，顺带堵掉两个静默出错点。

用法：
  blender --background --python scripts/vrm/roundtrip_vrma.py -- \
      --model data/persona-assets/k81/model.vrm \
      --motion data/motion-library/female/idle.vrma \
      --out build/vrma/idle_edited.vrma \
      --amplitude 1.5 --duration 1.4

为什么要脚本而不是手点 「导入 VRM → 导入 VRMA → 导出」（判据见
docs/VRM-ASSET-NOTES.md §7）：

  1. **帧范围截断**：场景默认 frame_end=250。345 帧的 idle 导入后导回去只剩
     250 帧、时长 14.33s → 10.38s。动作被砍掉四分之一而没有任何报错。
     这里按导入后的动作长度把 frame_start/frame_end 撑开。
  2. **骨骼集跟着模型漂**：导出的人骨槽位是按当前模型的人骨映射重建的，不是照
     源片段。k81 / komano 的骨架没有 upperChest，导出就丢 upperChest；模型映射里
     有眼骨，导出就多出 leftEye / rightEye。这一步不在这里硬凑——导出后跑
     `scripts/vrm/normalize_vrma.py --source <源片段> <导出文件>` 收口。
"""

import argparse
import sys

import bpy
from mathutils import Quaternion


def parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="加载动作用的 .vrm")
    parser.add_argument("--motion", required=True, help="要改的源 .vrma")
    parser.add_argument("--out", required=True, help="导出路径")
    parser.add_argument("--amplitude", type=float, default=1.0,
                        help="旋转幅度倍数，1.0 为原样")
    parser.add_argument("--duration", type=float, default=1.0,
                        help="时长倍数，1.0 为原样")
    return parser.parse_args(argv)


def enable_vrm_addon():
    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
    except Exception:  # 已经在 GUI 里启用过就会抛，忽略
        pass


def scale_quaternion(quat, factor):
    """按「相对 rest 的旋转角」缩放。Blender 的 pose 四元数本身就是相对 rest
    的增量，所以绕轴把角度乘 factor 即可；mathutils 的 slerp 拒绝外插因子，
    只能自己走轴角。"""
    quat = quat.normalized()
    axis, angle = quat.to_axis_angle()
    if angle == 0.0:
        return quat
    return Quaternion(axis, angle * factor).normalized()


def scale_amplitude(action, factor):
    """把每条四元数曲线的旋转角按 factor 缩放。"""
    groups = {}
    for curve in action.fcurves:
        if curve.data_path.endswith("rotation_quaternion"):
            groups.setdefault(curve.data_path, {})[curve.array_index] = curve
    touched = 0
    for curves in groups.values():
        if len(curves) != 4:
            continue
        components = [curves[index] for index in range(4)]
        key_count = len(components[0].keyframe_points)
        for index in range(key_count):
            values = [component.keyframe_points[index].co[1]
                      for component in components]
            quat = Quaternion((values[0], values[1], values[2], values[3]))
            scaled = scale_quaternion(quat, factor)
            for offset, component in enumerate(components):
                component.keyframe_points[index].co[1] = scaled[offset]
        for component in components:
            component.update()
        touched += 1
    return touched


def scale_duration(action, factor):
    last = 0.0
    for curve in action.fcurves:
        for point in curve.keyframe_points:
            point.co[0] *= factor
            point.handle_left[0] *= factor
            point.handle_right[0] *= factor
            last = max(last, point.co[0])
        curve.update()
    return last


def main():
    args = parse_args(sys.argv)
    # 顺序别换：read_factory_settings 会把扩展重新置回未启用
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # 中文界面下插件的 error_messages() 会崩，见 docs/VRM-ASSET-NOTES.md §2.2
    bpy.context.preferences.view.language = "en_US"
    enable_vrm_addon()

    bpy.ops.import_scene.vrm(filepath=args.model)
    armature = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature

    if bpy.ops.import_scene.vrma(filepath=args.motion) != {"FINISHED"}:
        raise SystemExit("导入 VRMA 失败：%s" % args.motion)

    action = armature.animation_data.action
    if args.amplitude != 1.0:
        print("幅度 ×%.3f，改了 %d 组四元数曲线"
              % (args.amplitude, scale_amplitude(action, args.amplitude)))
    if args.duration != 1.0:
        print("时长 ×%.3f" % args.duration)
    last_frame = scale_duration(action, args.duration)

    # 关键：不设就等于用场景默认的 1–250，长动作被静默截断
    bpy.context.scene.frame_start = int(min(0, action.frame_range[0]))
    bpy.context.scene.frame_end = int(last_frame or action.frame_range[1])
    print("帧范围 %d–%d，共 %d 帧"
          % (bpy.context.scene.frame_start, bpy.context.scene.frame_end,
             bpy.context.scene.frame_end - bpy.context.scene.frame_start + 1))

    if bpy.ops.export_scene.vrma(filepath=args.out) != {"FINISHED"}:
        raise SystemExit("导出 VRMA 失败：%s" % args.out)
    print("导出 %s" % args.out)
    print("下一步：python3 scripts/vrm/normalize_vrma.py --source %s %s"
          % (args.motion, args.out))


if __name__ == "__main__":
    main()
