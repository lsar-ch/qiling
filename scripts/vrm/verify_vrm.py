"""校验 .vrm 是否符合本项目规格。

规则本体在 `services/ai-service/app/core/vrm_validator.py`（导入闸门同一份），
这里只负责把报告打印成人看的输出，避免两份规则漂移。

用法: python3 scripts/vrm/verify_vrm.py <path.vrm>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "services", "ai-service"))

from app.core.vrm_validator import (  # noqa: E402
    ADVISORY_BYTES,
    MAX_MATERIALS,
    MAX_SPRING_JOINTS,
    MAX_TRIS,
    NEEDED_EXPRESSIONS as NEEDED,
    validate_vrm,
)


def main(path):
    report = validate_vrm(open(path, "rb").read())
    stats = report.stats

    print("== %s ==" % path)
    if not stats:
        for check in report.checks:
            print(("  FAIL " if not check.ok else "  OK   ") + check.label)
        return 1

    meta = stats["meta"]
    print("  glb version=%d size=%.2f MB bin=%d KB"
          % (stats["version"], stats["size"] / 1e6, stats["bin_len"] // 1024))
    print("  extensionsUsed:", stats["extensions_used"])
    print("  extensionsRequired:", stats["extensions_required"])
    for key, value in meta.items():
        print("    meta.%s = %s" % (key, value))
    print("    humanBones 总数 = %d" % stats["humanoid_count"])
    print("    upper arms: left=%s right=%s"
          % (stats["upper_arms"]["left"], stats["upper_arms"]["right"]))
    print("    preset 表情 %d 个: %s"
          % (len(stats["expressions"]), stats["expressions"]))
    print("    lookAt 类型 = %s（bone=眼球骨驱动，VRoid 默认）"
          % stats.get("look_at_type"))
    print("    顶点 = %d, 三角面 = %d, morph target = %d (稀疏存储 %d)"
          % (stats["verts"], stats["tris"], stats["morph_targets"],
             stats["sparse_targets"]))
    for mat in stats["materials"]:
        print("      mat %-22s ext=%s doubleSided=%s alphaMode=%s"
              % (mat["name"], mat["extensions"], mat["double_sided"],
                 mat["alpha_mode"]))
    spring = stats["spring"]
    print("    spring 链 = %d, joints 条目 = %d, 实际关节 = %d"
          % (spring["chains"], spring["entries"], spring["joints"]))
    for image in stats["images"]:
        print("    image %-16s %s %.2f MB"
              % (image["name"], image["mime"], image["size"] / 1e6))
    print("  规格上限：%d 面 / %d 材质 / %d spring 关节 / 建议 < %.0f MB"
          % (MAX_TRIS, MAX_MATERIALS, MAX_SPRING_JOINTS, ADVISORY_BYTES / 1e6))

    print("  -- 检查项 --")
    for check in report.checks:
        if check.ok:
            print("  OK   " + check.label)
        else:
            tag = "FAIL" if check.blocking else "WARN"
            print("  %s %s" % (tag, check.label))

    troubles = [c for c in report.checks if not c.ok]
    if not troubles:
        print("== 全部通过 ==")
        return 0
    print("== %s ==" % ("存在未通过项" if report.errors else "有建议项未通过"))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  "build/vrm/qiling_glb/model.vrm"))
