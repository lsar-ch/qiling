"""把 Blender 往返导出的 .vrma 拉回动作库规范骨骼集。

背景（细节见 docs/VRM-ASSET-NOTES.md）：Blender 的 VRM 插件导出 VRMA 时，
人骨槽位是照着**当前模型**的 humanoid 映射重建的，不是照源片段。于是导出结果
会跟着模型漂：k81 / komano 的骨架没有 upperChest 骨，导出就丢掉 upperChest；
模型的映射里有左/右眼骨，导出就多出 leftEye / rightEye。动作库的 40 个片段是
一致的 52 骨集（VRM 1.0 全集去掉 leftEye / rightEye / jaw），导出后必须收口。

用法：
  # 体检，不改文件；不合规退出码 1
  python3 scripts/vrm/normalize_vrma.py --check data/motion-library/female/*.vrma

  # 就地归一化，缺失的槽位用源片段补回
  python3 scripts/vrm/normalize_vrma.py --source /tmp/idle_original.vrma \
      data/motion-library/female/idle.vrma

  # 自检（拿动作库真实片段做回归）
  python3 scripts/vrm/normalize_vrma.py --selftest
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOTION_LIBRARY = ROOT / "data" / "motion-library"

VRMA_EXTENSION = "VRMC_vrm_animation"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942

# 规范人骨集：VRM 1.0 全集去掉 leftEye / rightEye / jaw。
# 与 scripts/vrm/humanoid-bones.json 同一份名单，check_vrma.mjs 也读它。
CANONICAL_BONES: tuple[str, ...] = json.loads(
    (Path(__file__).resolve().parent / "humanoid-bones.json").read_text()
)["bones"]

# VRM 1.0 人骨层级（只含规范集内的骨）。用来在补缺失槽位时决定插到哪。
PARENT: dict[str, str] = {
    "spine": "hips",
    "chest": "spine",
    "upperChest": "chest",
    "neck": "upperChest",
    "head": "neck",
    "leftShoulder": "upperChest",
    "leftUpperArm": "leftShoulder",
    "leftLowerArm": "leftUpperArm",
    "leftHand": "leftLowerArm",
    "leftThumbMetacarpal": "leftHand",
    "leftThumbProximal": "leftThumbMetacarpal",
    "leftThumbDistal": "leftThumbProximal",
    "leftIndexProximal": "leftHand",
    "leftIndexIntermediate": "leftIndexProximal",
    "leftIndexDistal": "leftIndexIntermediate",
    "leftMiddleProximal": "leftHand",
    "leftMiddleIntermediate": "leftMiddleProximal",
    "leftMiddleDistal": "leftMiddleIntermediate",
    "leftRingProximal": "leftHand",
    "leftRingIntermediate": "leftRingProximal",
    "leftRingDistal": "leftRingIntermediate",
    "leftLittleProximal": "leftHand",
    "leftLittleIntermediate": "leftLittleProximal",
    "leftLittleDistal": "leftLittleIntermediate",
    "rightShoulder": "upperChest",
    "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm",
    "rightHand": "rightLowerArm",
    "rightThumbMetacarpal": "rightHand",
    "rightThumbProximal": "rightThumbMetacarpal",
    "rightThumbDistal": "rightThumbProximal",
    "rightIndexProximal": "rightHand",
    "rightIndexIntermediate": "rightIndexProximal",
    "rightIndexDistal": "rightIndexIntermediate",
    "rightMiddleProximal": "rightHand",
    "rightMiddleIntermediate": "rightMiddleProximal",
    "rightMiddleDistal": "rightMiddleIntermediate",
    "rightRingProximal": "rightHand",
    "rightRingIntermediate": "rightRingProximal",
    "rightRingDistal": "rightRingIntermediate",
    "rightLittleProximal": "rightHand",
    "rightLittleIntermediate": "rightLittleProximal",
    "rightLittleDistal": "rightLittleIntermediate",
    "leftUpperLeg": "hips",
    "leftLowerLeg": "leftUpperLeg",
    "leftFoot": "leftLowerLeg",
    "leftToes": "leftFoot",
    "rightUpperLeg": "hips",
    "rightLowerLeg": "rightUpperLeg",
    "rightFoot": "rightLowerLeg",
    "rightToes": "rightFoot",
}


class VrmaFormatError(ValueError):
    """文件不是可解析的 GLB，或结构不是本脚本能处理的 VRMA。"""


def parse_glb(data: bytes) -> tuple[dict, bytes]:
    """拆分 GLB，返回 (JSON chunk, BIN chunk)。"""
    if len(data) < 12:
        raise VrmaFormatError("文件过短，不是 GLB")
    magic, version, total = struct.unpack("<4sII", data[:12])
    if magic != b"glTF":
        raise VrmaFormatError("缺少 glTF magic")
    if version != 2:
        raise VrmaFormatError("只支持 glTF 2.0，实际 %d" % version)
    if total != len(data):
        raise VrmaFormatError("头部声明长度 %d 与实际 %d 不符" % (total, len(data)))
    doc: dict | None = None
    bin_bytes = b""
    offset = 12
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        payload = data[offset + 8 : offset + 8 + length]
        if kind == JSON_CHUNK:
            doc = json.loads(payload.decode("utf-8"))
        elif kind == BIN_CHUNK:
            bin_bytes = payload
        offset += 8 + length
    if doc is None:
        raise VrmaFormatError("没有 JSON chunk")
    return doc, bin_bytes


def pack_glb(doc: dict, bin_bytes: bytes) -> bytes:
    """按 GLB 规则打包，两个 chunk 各自补齐到 4 字节。"""
    if doc.get("buffers"):
        doc["buffers"][0]["byteLength"] = len(bin_bytes)
    payload = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunks = struct.pack("<II", len(payload), JSON_CHUNK) + payload
    if bin_bytes:
        padded = bin_bytes + b"\x00" * ((4 - len(bin_bytes) % 4) % 4)
        chunks += struct.pack("<II", len(padded), BIN_CHUNK) + padded
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def _read_floats(doc: dict, bin_bytes: bytes, accessor_index: int) -> list[float]:
    accessor = doc["accessors"][accessor_index]
    if accessor.get("componentType") != 5126:
        raise VrmaFormatError("只支持 float 采样器，accessor %d 是 %s"
                              % (accessor_index, accessor.get("componentType")))
    if accessor.get("sparse"):
        raise VrmaFormatError("不支持稀疏 accessor %d" % accessor_index)
    view = doc["bufferViews"][accessor["bufferView"]]
    if view.get("buffer", 0) != 0:
        raise VrmaFormatError("只支持 buffer 0")
    comps = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    count = accessor["count"] * comps
    values = struct.unpack_from("<%df" % count, bin_bytes, start)
    return list(values)


def _append_floats(doc: dict, bin_bytes: bytearray, values: list[float],
                   comps: int) -> int:
    """把一批 float 追加进 BIN，返回新建 accessor 的下标。"""
    while len(bin_bytes) % 4:
        bin_bytes.append(0)
    payload = struct.pack("<%df" % len(values), *values)
    view = {"buffer": 0, "byteOffset": len(bin_bytes), "byteLength": len(payload)}
    doc["bufferViews"].append(view)
    bin_bytes.extend(payload)
    type_name = {1: "SCALAR", 3: "VEC3", 4: "VEC4"}[comps]
    accessor: dict = {
        "bufferView": len(doc["bufferViews"]) - 1,
        "componentType": 5126,
        "count": len(values) // comps,
        "type": type_name,
    }
    # 动画采样器的输入 accessor 按规范必须带 min/max
    if comps == 1:
        accessor["min"] = [min(values)]
        accessor["max"] = [max(values)]
    doc["accessors"].append(accessor)
    return len(doc["accessors"]) - 1


def _human_bones(doc: dict) -> dict:
    extension = doc.get("extensions", {}).get(VRMA_EXTENSION)
    if not isinstance(extension, dict):
        raise VrmaFormatError("缺少 %s 扩展" % VRMA_EXTENSION)
    bones = extension.get("humanoid", {}).get("humanBones")
    if not isinstance(bones, dict):
        raise VrmaFormatError("缺少 humanoid.humanBones")
    return bones


def _animations(doc: dict) -> list[dict]:
    animations = doc.get("animations")
    if not isinstance(animations, list) or not animations:
        raise VrmaFormatError("不含任何 animation")
    return animations


def _duration(doc: dict, bin_bytes: bytes) -> float:
    longest = 0.0
    for animation in _animations(doc):
        for sampler in animation.get("samplers", []):
            values = _read_floats(doc, bin_bytes, sampler["input"])
            if values:
                longest = max(longest, max(values))
    return longest


def survey(doc: dict) -> tuple[list[str], list[str]]:
    """返回 (缺失的规范槽位, 规范外的槽位)，两者都按固定顺序。"""
    keys = set(_human_bones(doc))
    missing = [name for name in CANONICAL_BONES if name not in keys]
    extra = sorted(keys - set(CANONICAL_BONES))
    return missing, extra


def _drop_extra(doc: dict, extra: list[str]) -> None:
    """删掉规范外槽位，并移除只打在它们节点上的通道。

    先删槽位再算待删节点：万一某个规范外槽位和保留槽位共用同一个节点
    （脏数据里出现过），只按节点号删通道会把保留骨的动画一起删掉。
    """
    bones = _human_bones(doc)
    doomed = {bones[name]["node"] for name in extra}
    for name in extra:
        del bones[name]
    doomed -= {bones[name]["node"] for name in bones}
    for animation in _animations(doc):
        animation["channels"] = [
            channel for channel in animation["channels"]
            if channel["target"]["node"] not in doomed
        ]


def _find_channel(doc: dict, node_index: int, path: str) -> dict | None:
    for animation in _animations(doc):
        for channel in animation["channels"]:
            target = channel["target"]
            if target["node"] == node_index and target["path"] == path:
                return animation["samplers"][channel["sampler"]]
    return None


def _insert_missing(doc: dict, bin_bytes: bytearray, name: str, source_doc: dict,
                    source_bin: bytes, time_scale: float) -> list[str]:
    """把源片段里的某个规范槽位搬进目标文件，返回动作说明（供报告用）。"""
    notes: list[str] = []
    bones = _human_bones(doc)
    source_bones = _human_bones(source_doc)
    if name in bones:
        return notes
    parent_name = PARENT[name]
    if parent_name not in bones:
        raise VrmaFormatError("%s 缺失，但它的父骨 %s 也缺失，无法补" % (name, parent_name))
    if name not in source_bones:
        raise VrmaFormatError("源片段里也没有 %s，无法补" % name)

    parent_index = bones[parent_name]["node"]
    parent_node = doc["nodes"][parent_index]
    adopted = [
        bones[child]["node"]
        for child in CANONICAL_BONES
        if PARENT.get(child) == name and child in bones
    ]
    children = [index for index in parent_node.get("children", []) if index in adopted]

    new_index = len(doc["nodes"])
    doc["nodes"].append({
        "name": name,
        # 单位局部变换：把子骨原样挂进来，不引入任何几何偏移
        "translation": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "scale": [1.0, 1.0, 1.0],
        "children": children,
    })
    parent_node["children"] = [
        index for index in parent_node.get("children", []) if index not in adopted
    ]
    parent_node.setdefault("children", []).append(new_index)
    bones[name] = {"node": new_index}
    notes.append("%s: 新建节点挂在 %s 下（接管 %d 根子骨）" % (name, parent_name, len(children)))

    source_index = source_bones[name]["node"]
    copied = 0
    for animation in _animations(doc):
        for path in ("rotation", "translation", "scale"):
            sampler = _find_channel(source_doc, source_index, path)
            if sampler is None:
                continue
            comps = {"rotation": 4, "translation": 3, "scale": 3}[path]
            times = _read_floats(source_doc, source_bin, sampler["input"])
            values = _read_floats(source_doc, source_bin, sampler["output"])
            times = [value * time_scale for value in times]
            input_index = _append_floats(doc, bin_bytes, times, 1)
            output_index = _append_floats(doc, bin_bytes, values, comps)
            animation["samplers"].append(
                {"input": input_index, "output": output_index,
                 "interpolation": sampler.get("interpolation", "LINEAR")}
            )
            animation["channels"].append({
                "sampler": len(animation["samplers"]) - 1,
                "target": {"node": new_index, "path": path},
            })
            copied += 1
    notes.append("%s: 从源片段搬回 %d 条通道（时间轴 ×%.4f）" % (name, copied, time_scale))
    return notes


def normalize_bytes(data: bytes, source: bytes | None = None,
                    source_name: str = "source") -> tuple[bytes, list[str]]:
    """归一化一个 VRMA；返回 (新字节, 说明行)。"""
    doc, bin_bytes = parse_glb(data)
    missing, extra = survey(doc)
    if not missing and not extra:
        return data, ["已经合规：humanBones=%d" % len(CANONICAL_BONES)]
    notes: list[str] = []
    if extra:
        _drop_extra(doc, extra)
        notes.append("删除规范外槽位: %s" % ", ".join(extra))
    if missing:
        if source is None:
            raise VrmaFormatError(
                "缺少规范槽位 %s；要补请用 --source 指定源片段"
                % ", ".join(missing)
            )
        source_doc, source_bin = parse_glb(source)
        target_duration = _duration(doc, bin_bytes)
        source_duration = _duration(source_doc, source_bin)
        if source_duration <= 0:
            raise VrmaFormatError("%s 的时长为 0，无法对齐时间轴" % source_name)
        buffer = bytearray(bin_bytes)
        for name in missing:
            notes.extend(_insert_missing(doc, buffer, name, source_doc,
                                         source_bin, target_duration / source_duration))
        bin_bytes = bytes(buffer)
    return pack_glb(doc, bin_bytes), notes


def _report(path: Path, notes: list[str], missing: list[str], extra: list[str]) -> None:
    if missing or extra:
        print("FAIL %s" % path)
        if missing:
            print("     缺失规范槽位: %s" % ", ".join(missing))
        if extra:
            print("     规范外槽位: %s" % ", ".join(extra))
    else:
        print("OK   %s" % path)
    for note in notes:
        print("     %s" % note)


def selftest() -> int:
    """拿动作库真实片段做回归：造一个「丢 upperChest + 多眼骨」的坏文件，
    再用源片段归一化，断言骨骼集与通道都回来了。"""
    origin = MOTION_LIBRARY / "female" / "idle.vrma"
    source = origin.read_bytes()
    doc, bin_bytes = parse_glb(source)
    bones = _human_bones(doc)
    upper_chest_node = bones["upperChest"]["node"]
    head_node = bones["head"]["node"]
    # 复现 Blender 导出的树形：模型没有 upperChest 骨，于是这个节点在树里也不存在，
    # 它的子骨直接挂在 chest 下。只删 humanBones 槽位而不动树就不像真实导出了。
    chest_node = doc["nodes"][bones["chest"]["node"]]
    promoted = list(doc["nodes"][upper_chest_node].get("children", []))
    chest_node["children"] = [
        index for index in chest_node.get("children", []) if index != upper_chest_node
    ] + promoted
    del bones["upperChest"]
    # 真实导出里眼骨各有自己的节点；挂到独立节点，顺带放一条眼骨通道，
    # 用来验证「删规范外通道」不会误伤 head 自己的通道。
    eye_node = len(doc["nodes"])
    doc["nodes"].append({"name": "eye.probe", "translation": [0.0, 0.0, 0.0]})
    bones["leftEye"] = {"node": eye_node}
    bones["rightEye"] = {"node": eye_node}
    for animation in _animations(doc):
        animation["channels"].append({
            "sampler": 0,
            "target": {"node": eye_node, "path": "rotation"},
        })
    for animation in _animations(doc):
        animation["channels"] = [
            channel for channel in animation["channels"]
            if channel["target"]["node"] != upper_chest_node
        ]
    broken = pack_glb(doc, bin_bytes)

    missing, extra = survey(parse_glb(broken)[0])
    assert missing == ["upperChest"], missing
    assert extra == ["leftEye", "rightEye"], extra

    fixed, notes = normalize_bytes(broken, source=source, source_name="idle.vrma")
    fixed_doc, fixed_bin = parse_glb(fixed)
    missing, extra = survey(fixed_doc)
    assert not missing and not extra, (missing, extra)

    fixed_bones = _human_bones(fixed_doc)
    # 被删的是眼骨槽位，head 自己的通道不能跟着陪葬
    assert _find_channel(fixed_doc, fixed_bones["head"]["node"], "rotation") \
        is not None, "head 的旋转通道被误删了"
    assert not any(channel["target"]["node"] == eye_node
                   for animation in _animations(fixed_doc)
                   for channel in animation["channels"]), "眼骨通道没删干净"
    restored = fixed_bones["upperChest"]["node"]
    sampler = _find_channel(fixed_doc, restored, "rotation")
    assert sampler is not None, "upperChest 的旋转通道没搬回来"
    source_sampler = _find_channel(parse_glb(source)[0], upper_chest_node, "rotation")
    assert (_read_floats(fixed_doc, fixed_bin, sampler["output"])
            == _read_floats(*parse_glb(source)[0:2], source_sampler["output"])), \
        "upperChest 采样值与源片段不一致"
    # 补进来的骨必须接管原 chest 的孩子，节点树不能断
    parent_index = fixed_bones["upperChest"]["node"]
    assert fixed_doc["nodes"][parent_index]["children"], "upperChest 没接管任何子骨"
    assert fixed_bones["neck"]["node"] in fixed_doc["nodes"][parent_index]["children"]


    # 脏数据：规范外槽位和保留槽位共用同一个节点时，不能把保留骨的通道删掉
    shared_doc, shared_bin = parse_glb(source)
    shared_bones = _human_bones(shared_doc)
    shared_bones["leftEye"] = {"node": shared_bones["head"]["node"]}
    cleaned, _ = normalize_bytes(pack_glb(shared_doc, shared_bin))
    cleaned_doc, _ = parse_glb(cleaned)
    cleaned_bones = _human_bones(cleaned_doc)
    assert "leftEye" not in cleaned_bones
    assert _find_channel(cleaned_doc, cleaned_bones["head"]["node"], "rotation") \
        is not None, "共用节点时把 head 的通道误删了"

    again, _ = normalize_bytes(fixed)
    assert again == fixed, "归一化不是幂等的"

    for note in notes:
        print("  %s" % note)
    print("selftest OK：坏文件已回到 %d 骨，通道与层级都正确" % len(CANONICAL_BONES))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="只报告，不改写；发现不合规时退出码 1")
    parser.add_argument("--source", type=Path,
                        help="缺失槽位从这个片段补回（一般就是导出前的原始 vrma）")
    parser.add_argument("--out", type=Path, help="输出路径；只给一个文件时可用")
    parser.add_argument("--selftest", action="store_true", help="跑内置回归")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.files:
        parser.error("没有输入文件")
    if args.out and len(args.files) > 1:
        parser.error("--out 只能配单个输入文件")

    source = args.source.read_bytes() if args.source else None
    failures = 0
    for path in args.files:
        try:
            data = path.read_bytes()
            missing, extra = survey(parse_glb(data)[0])
        except (OSError, VrmaFormatError, KeyError) as exc:
            print("ERROR %s: %s" % (path, exc))
            failures += 1
            continue
        if args.check:
            _report(path, [], missing, extra)
            failures += 1 if missing or extra else 0
            continue
        try:
            fresh, notes = normalize_bytes(data, source=source,
                                           source_name=str(args.source or ""))
        except VrmaFormatError as exc:
            print("ERROR %s: %s" % (path, exc))
            failures += 1
            continue
        target = args.out or path
        if fresh != data:
            target.write_bytes(fresh)
        _report(path, notes, *survey(parse_glb(fresh)[0]))
        if target != path:
            print("     写出 %s" % target)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
