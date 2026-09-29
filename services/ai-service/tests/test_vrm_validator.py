"""VRM 校验器：阈值边界与降级行为。"""

from __future__ import annotations

import json
import struct

from app.core.vrm_validator import (
    MAX_MATERIALS,
    MAX_SPRING_JOINTS,
    MAX_TRIS,
    validate_vrm,
    validate_vrma,
)


def glb(doc: dict, bin_bytes: bytes = b"") -> bytes:
    payload = json.dumps(doc).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunks = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    if bin_bytes:
        padded = bin_bytes + b"\x00" * ((4 - len(bin_bytes) % 4) % 4)
        chunks += struct.pack("<II", len(padded), 0x004E4942) + padded
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def spec_doc(*, tris: int = 300, materials: int = 1, spring_joints: int = 1,
             expressions: int = 15, spec_version: str = "1.0") -> dict:
    """可调参数的合规文档，用于把某个维度推到阈值边界。"""
    presets = [
        "aa", "ih", "ou", "ee", "oh", "blink", "happy", "angry", "sad",
        "relaxed", "neutral", "lookUp", "lookDown", "lookLeft", "lookRight",
    ][:expressions]
    human = {name: {"node": 0} for name in (
        "hips", "spine", "chest", "upperChest", "neck", "head",
        "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
        "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
        "leftUpperLeg", "leftLowerLeg", "leftFoot",
        "rightUpperLeg", "rightLowerLeg", "rightFoot",
    )}
    human["hips"] = {"node": 0}
    human["leftUpperArm"] = {"node": 2}
    human["rightUpperArm"] = {"node": 3}
    human["head"] = {"node": 1}
    return {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["VRMC_vrm", "VRMC_springBone"],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": spec_version,
                "meta": {
                    "avatarPermission": "onlyAuthor",
                    "allowExcessivelyViolentUsage": False,
                    "allowExcessivelySexualUsage": False,
                    "allowPoliticalOrReligiousUsage": False,
                    "allowAntisocialOrHateUsage": False,
                    "thumbnailImage": 0,
                },
                "humanoid": {"humanBones": human},
                "expressions": {"preset": {p: {"morphTargetBinds": []} for p in presets}},
            },
            "VRMC_springBone": {
                # 实际关节数 = entries - chains；这里 chains=1，故 entries = joints + 1
                "springs": [{"joints": [{"node": 0}] * (spring_joints + 1)}],
            },
        },
        "materials": [{"name": f"m{i}"} for i in range(materials)],
        "images": [],
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0},
                "indices": 1,
                "targets": [{"POSITION": 2} for _ in range(15)],
            }],
        }],
        "accessors": [
            {"count": 10, "type": "VEC3", "componentType": 5126},
            {"count": tris * 3, "type": "SCALAR", "componentType": 5123},
            *[{"count": 10, "type": "VEC3", "componentType": 5126} for _ in range(15)],
        ],
        "nodes": [
            {"name": "Hips"},
            {"name": "Head"},
            {"name": "LeftUpperArm", "translation": [0.15, 0.0, 0.0]},
            {"name": "RightUpperArm", "translation": [-0.15, 0.0, 0.0]},
        ],
    }


def test_mirrored_arms_flagged() -> None:
    """两臂落在中轴同侧 = 真的镜像颠倒，必须拦。"""
    doc = spec_doc()
    doc["nodes"][2] = {"name": "LeftUpperArm", "translation": [0.15, 0.0, 0.0]}
    doc["nodes"][3] = {"name": "RightUpperArm", "translation": [0.15, 0.0, 0.0]}
    report = validate_vrm(glb(doc))
    assert not report.ok
    assert any("分居两侧" in e for e in report.errors), report.errors


def test_missing_upper_chest_is_advisory() -> None:
    """upperChest 是 VRM1 可选骨，缺失只提示，不拦导入。"""
    doc = spec_doc()
    doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"].pop("upperChest")
    report = validate_vrm(glb(doc))
    assert report.ok, report.errors
    assert any("upperChest" in w for w in report.warnings), report.warnings


def test_spec_document_passes() -> None:
    report = validate_vrm(glb(spec_doc()))
    assert report.ok, report.errors
    assert report.stats["spec_version"] == "1.0"
    assert report.stats["spring"]["joints"] == 1


def test_thresholds_at_and_over_limit() -> None:
    at_limit = validate_vrm(glb(spec_doc(
        tris=MAX_TRIS, materials=MAX_MATERIALS, spring_joints=MAX_SPRING_JOINTS,
    )))
    assert at_limit.ok, at_limit.errors

    over_tris = validate_vrm(glb(spec_doc(tris=MAX_TRIS + 1)))
    assert not over_tris.ok
    assert any("三角面" in e for e in over_tris.errors)

    over_mats = validate_vrm(glb(spec_doc(materials=MAX_MATERIALS + 1)))
    assert not over_mats.ok
    assert any("材质" in e for e in over_mats.errors)

    over_spring = validate_vrm(glb(spec_doc(spring_joints=MAX_SPRING_JOINTS + 1)))
    assert not over_spring.ok
    assert any("spring bone" in e for e in over_spring.errors)


def test_missing_expression_is_blocking() -> None:
    report = validate_vrm(glb(spec_doc(expressions=14)))
    assert not report.ok
    assert any("必备表情" in e for e in report.errors)


def test_vrm0_is_rejected_with_upgrade_hint() -> None:
    report = validate_vrm(glb(spec_doc(spec_version="0.0")))
    assert not report.ok
    assert any("optimize_vrm.py" in e for e in report.errors)


def test_garbage_bytes_do_not_raise() -> None:
    report = validate_vrm(b"not a glb at all")
    assert not report.ok
    assert "GLB" in report.errors[0]


def test_vrma_requires_extension_and_animation() -> None:
    good = glb({"extensionsUsed": ["VRMC_vrm_animation"], "animations": [{"channels": []}]})
    assert validate_vrma(good) == []
    assert validate_vrma(glb({"animations": [{"channels": []}]}))
    assert validate_vrma(glb({"extensionsUsed": ["VRMC_vrm_animation"]}))
    assert validate_vrma(b"junk")
