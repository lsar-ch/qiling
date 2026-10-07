"""VRM 资产规格校验：导入闸门与 CLI 共用的单一事实源。

规格来源 `docs/WIDGET-VRM-3D-PLAN.md` §3。这里只做结构层判定，不渲染——
渲染层的问题（例如 skinIndex 被重组导致饰件不显示）必须靠真实截图对照，
静态校验抓不到，见 `docs/VRM-ASSET-NOTES.md` §5.4。
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any

VRM_SPEC_VERSION = "1.0"
MAX_TRIS = 40000
MAX_MATERIALS = 16
MAX_SPRING_JOINTS = 30
# 体积与缩略图不进闸门，只做提示：它们不影响能否加载。
ADVISORY_BYTES = 12_000_000

NEEDED_EXPRESSIONS = frozenset({
    "aa", "ih", "ou", "ee", "oh", "blink", "happy", "angry", "sad",
    "relaxed", "neutral", "lookUp", "lookDown", "lookLeft", "lookRight",
})

CORE_HUMANOID = (
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
)

_ALLOWED_AVATAR_PERMISSION = ("onlyAuthor", "onlyExpressively", "everyone")
_DISALLOWED_USAGE_FLAGS = (
    "allowExcessivelyViolentUsage",
    "allowExcessivelySexualUsage",
    "allowPoliticalOrReligiousUsage",
    "allowAntisocialOrHateUsage",
)

VRMA_EXTENSION = "VRMC_vrm_animation"

# VRM 1.0 必备人骨。VRMA 靠 humanoid 映射重定向到模型，缺一根就有一路动作
# 静默丢掉（Blender 往返导出按模型骨集重建，最容易丢的就是这些）。
REQUIRED_VRMA_BONES = (
    "hips", "spine", "head",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
)


class GlbFormatError(ValueError):
    """字节流不是可解析的 GLB 容器。"""


@dataclass
class Check:
    ok: bool
    label: str
    blocking: bool = True


@dataclass
class VrmReport:
    checks: list[Check] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[str]:
        return [c.label for c in self.checks if not c.ok and c.blocking]

    @property
    def warnings(self) -> list[str]:
        return [c.label for c in self.checks if not c.ok and not c.blocking]

    @property
    def ok(self) -> bool:
        return not self.errors


def read_glb(data: bytes) -> tuple[dict[str, Any], int, int, int]:
    """解析 GLB，返回 (JSON chunk, version, 总长度, BIN 长度)。"""
    if len(data) < 12:
        raise GlbFormatError("文件过短，不是 GLB")
    magic, version, total = struct.unpack("<4sII", data[:12])
    if magic != b"glTF":
        raise GlbFormatError("magic 不是 glTF")
    offset = 12
    doc: dict[str, Any] | None = None
    bin_len = 0
    while offset + 8 <= total and offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack("<II", data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + chunk_len]
        if chunk_type == 0x4E4F534A:       # 'JSON'
            doc = json.loads(body.rstrip(b"\x00 ").decode("utf-8"))
        elif chunk_type == 0x004E4942:     # 'BIN\x00'
            bin_len = chunk_len
        offset += 8 + chunk_len
    if doc is None:
        raise GlbFormatError("缺少 JSON chunk")
    return doc, version, total, bin_len


def _count_tris_and_targets(doc: dict[str, Any]) -> tuple[int, int, int, int]:
    meshes = doc.get("meshes", [])
    accessors = doc.get("accessors", [])
    tris = 0
    targets = 0
    sparse_targets = 0
    verts = 0
    for mesh in meshes:
        for prim in mesh.get("primitives", []):
            index = prim.get("indices")
            if index is not None:
                tris += accessors[index]["count"] // 3
            position = prim.get("attributes", {}).get("POSITION")
            if position is not None:
                verts += accessors[position]["count"]
            prim_targets = prim.get("targets", [])
            targets += len(prim_targets)
            for target in prim_targets:
                if any("sparse" in accessors[a] for a in target.values()):
                    sparse_targets += 1
    return tris, verts, targets, sparse_targets


def _humanoid_bones(vrm: dict[str, Any]) -> dict[str, int]:
    raw = vrm.get("humanoid", {}).get("humanBones", [])
    got: dict[str, int] = {}
    if isinstance(raw, dict):        # VRM 1.0: {boneName: {node: i}}
        for name, value in raw.items():
            node = value.get("node") if isinstance(value, dict) else None
            if node is not None:
                got[name] = node
    else:                            # VRM 0.x: [{bone, node}]
        for entry in raw:
            if entry.get("node") is not None:
                got[entry.get("bone", "")] = entry["node"]
    return got


def _node_world_x(doc: dict[str, Any], index: int | None) -> float | None:
    """按 glTF 节点层级累加平移，返回节点世界坐标 x。

    只累加 translation、忽略 rotation 对角度的贡献：肩臂相对根节点的旋转
    通常很小，用来判定「左右是否对称分居中轴两侧」够用。要让判定更严可以
    升级成完整 TRS 合成，但当前只为区分「命名不同」和「真的镜像颠倒」。
    """
    if index is None:
        return None
    nodes = doc.get("nodes", [])
    if not (0 <= index < len(nodes)):
        return None
    parent: dict[int, int] = {}
    for i, node in enumerate(nodes):
        for child in node.get("children", []) or []:
            parent[child] = i
    chain: list[int] = []
    cursor: int | None = index
    guard = 0
    while cursor is not None and guard < len(nodes) + 1:
        chain.append(cursor)
        cursor = parent.get(cursor)
        guard += 1
    x = 0.0
    for node_index in reversed(chain):
        t = nodes[node_index].get("translation") or (0.0, 0.0, 0.0)
        x += float(t[0])
    return x


def validate_vrm(data: bytes) -> VrmReport:
    """校验 .vrm 字节流；返回带 checks/stats 的报告，不抛异常。"""
    checks: list[Check] = []
    stats: dict[str, Any] = {}

    def check(cond: Any, label: str, blocking: bool = True) -> None:
        checks.append(Check(bool(cond), label, blocking))

    try:
        doc, version, total, bin_len = read_glb(data)
    except Exception as exc:                                  # noqa: BLE001
        return VrmReport([Check(False, f"不是有效的 GLB/VRM 文件：{exc}")], {})

    stats["version"] = version
    stats["size"] = total
    stats["bin_len"] = bin_len

    used = doc.get("extensionsUsed", [])
    stats["extensions_used"] = used
    stats["extensions_required"] = doc.get("extensionsRequired", [])
    check("VRMC_vrm" in used, "extensionsUsed 含 VRMC_vrm")
    vrm = doc.get("extensions", {}).get("VRMC_vrm", {})

    spec = vrm.get("specVersion")
    stats["spec_version"] = spec
    spec_hint = ""
    if spec != VRM_SPEC_VERSION:
        spec_hint = "；请先跑 scripts/vrm/optimize_vrm.py 由 0.x 转 1.0"
    check(spec == VRM_SPEC_VERSION,
          f"VRM specVersion == {VRM_SPEC_VERSION}（实际 {spec}）{spec_hint}")

    meta = vrm.get("meta", {})
    stats["meta"] = {k: meta.get(k) for k in (
        "name", "avatarPermission", "commercialUsage", "modification",
        "allowRedistribution", "creditNotation",
    )}
    check(meta.get("avatarPermission") in _ALLOWED_AVATAR_PERMISSION,
          "meta.avatarPermission 可被加载 (%s)" % meta.get("avatarPermission"))
    for flag in _DISALLOWED_USAGE_FLAGS:
        check(meta.get(flag) is False, f"meta.{flag} 为 false")
    check(meta.get("thumbnailImage") is not None,
          "含缩略图（建议补齐，不影响加载）", blocking=False)

    bones = _humanoid_bones(vrm)
    stats["humanoid_count"] = len(bones)
    missing = [b for b in CORE_HUMANOID if b not in bones]
    # upperChest 在 VRM 1.0 里是可选骨，且 栖灵 渲染链（VrmStage）不引用它。
    # 81.vrm 的 Neck 直挂 Chest、骨架里确实没有中间骨，卡这条只会误伤。
    blocking_missing = [b for b in missing if b != "upperChest"]
    check(not blocking_missing,
          f"核心人骨齐全（缺 {blocking_missing}）" if blocking_missing else "核心人骨齐全")
    if "upperChest" in missing:
        check(False, "缺 upperChest（VRM1 可选骨，渲染链不引用）", blocking=False)
    # 左右肩臂：按世界坐标几何判定，别看骨名。骨名约定五花八门
    # （芙宁娜 "Left arm"、81.vrm "Upper Arm.L"），按名字判会误伤。
    # 真正的不变量是：两臂在身体中轴**两侧**且大致对称。
    nodes = doc.get("nodes", [])
    arms = {}
    for side in ("left", "right"):
        node = bones.get(f"{side}UpperArm")
        arms[side] = nodes[node].get("name", "") if node is not None and node < len(nodes) else ""
    stats["upper_arms"] = arms
    lx = _node_world_x(doc, bones.get("leftUpperArm")) \
        if bones.get("leftUpperArm") is not None else None
    rx = _node_world_x(doc, bones.get("rightUpperArm")) \
        if bones.get("rightUpperArm") is not None else None
    stats["upper_arm_x"] = {"left": lx, "right": rx}
    # 低于这个量级（1mm）说明横向偏移不在 translation 这一层，判不出方向
    epsilon = 1e-3
    if lx is None or rx is None:
        check(False, "左右肩臂几何可判定（缺 leftUpperArm/rightUpperArm）",
              blocking=False)
    elif min(abs(lx), abs(rx)) < epsilon:
        # 有一侧 x≈0：vrm_demo 的右肩横向偏移在旋转里、translation 只给 0，
        # 这时乘积的符号没有意义，判「同侧」是误报，只能提示。
        check(False, "左右肩臂几何可判定（x 过小判不出方向 left=%.4f right=%.4f）"
              % (lx, rx), blocking=False)
    elif lx * rx > 0:
        # 两臂落在中轴同一侧（含两臂完全重合）= 真的左右颠倒，必须拦
        check(False, "左右肩臂分居两侧（left x=%.4f right x=%.4f 同侧）"
              % (lx, rx))
    else:
        check(True, "左右肩臂分居两侧（left x=%.4f right x=%.4f）" % (lx, rx))

    expressions = sorted(vrm.get("expressions", {}).get("preset", {}))
    stats["expressions"] = expressions
    lack = sorted(NEEDED_EXPRESSIONS - set(expressions))
    check(not lack, f"15 个必备表情齐全（缺 {lack}）" if lack else "15 个必备表情齐全")

    tris, verts, targets, sparse_targets = _count_tris_and_targets(doc)
    stats.update(tris=tris, verts=verts, morph_targets=targets,
                 sparse_targets=sparse_targets)
    tris_hint = "" if tris <= MAX_TRIS else "；超出规格上限，需先减面"
    check(tris <= MAX_TRIS, f"三角面 {tris} <= {MAX_TRIS}{tris_hint}")
    check(targets >= len(NEEDED_EXPRESSIONS),
          f"morph target 数 {targets} >= {len(NEEDED_EXPRESSIONS)}")

    materials = doc.get("materials", [])
    stats["materials"] = [
        {
            "name": m.get("name"),
            "extensions": list(m.get("extensions", {})),
            "double_sided": m.get("doubleSided", True),
            "alpha_mode": m.get("alphaMode", "opaque"),
        }
        for m in materials
    ]
    mat_hint = "" if len(materials) <= MAX_MATERIALS else "；超出规格上限，需合并材质"
    check(len(materials) <= MAX_MATERIALS,
          f"材质数 {len(materials)} <= {MAX_MATERIALS}{mat_hint}")
    # glTF 未写 doubleSided 时默认 true；朝内法线的头发壳依赖双面。
    check(all(m.get("doubleSided", True) for m in materials),
          "所有材质保持双面（头发壳有朝内法线）", blocking=False)

    # VRM 1.0 的 joints 是骨链：相邻两项配对成关节，末节点只当尾巴。
    springs = doc.get("extensions", {}).get("VRMC_springBone", {}).get("springs", [])
    entries = sum(len(s.get("joints", [])) for s in springs)
    joints = entries - len(springs)
    stats["spring"] = {"chains": len(springs), "entries": entries, "joints": joints}
    spring_hint = "" if joints <= MAX_SPRING_JOINTS else "；超出规格上限，需裁剪物理骨预算"
    check(joints <= MAX_SPRING_JOINTS,
          f"spring bone 关节 {joints} <= {MAX_SPRING_JOINTS}{spring_hint}")

    check(total < ADVISORY_BYTES,
          "文件体积 %.2f MB < %.0f MB（建议值，不影响加载）"
          % (total / 1e6, ADVISORY_BYTES / 1e6),
          blocking=False)
    stats["images"] = [
        {
            "name": img.get("name"),
            "mime": img.get("mimeType"),
            "size": doc["bufferViews"][img["bufferView"]]["byteLength"],
        }
        for img in doc.get("images", [])
        if img.get("bufferView") is not None
    ]
    return VrmReport(checks, stats)


def validate_vrma(data: bytes) -> list[str]:
    """校验 .vrma 字节流；返回错误列表，空列表表示可用。"""
    try:
        doc, _version, _total, _bin_len = read_glb(data)
    except Exception as exc:                                  # noqa: BLE001
        return [f"不是有效的 GLB/VRMA 文件：{exc}"]
    errors: list[str] = []
    if VRMA_EXTENSION not in doc.get("extensionsUsed", []):
        errors.append(f"缺少 {VRMA_EXTENSION} 扩展，不是 VRM 动画文件")
    if not doc.get("animations"):
        errors.append("不含任何 animation")
    # 逐层判类型：这个扩展来自用户上传的文件，不能假定它一定是对象
    extension = doc.get("extensions")
    extension = extension.get(VRMA_EXTENSION) if isinstance(extension, dict) else None
    humanoid = extension.get("humanoid") if isinstance(extension, dict) else None
    human_bones = humanoid.get("humanBones") if isinstance(humanoid, dict) else None
    if not isinstance(human_bones, dict) or not human_bones:
        errors.append("缺少 humanoid.humanBones，无法重定向到模型")
    else:
        absent = [name for name in REQUIRED_VRMA_BONES if name not in human_bones]
        if absent:
            errors.append("humanBones 缺少 VRM 1.0 必备骨：%s" % "、".join(absent))
    return errors
