"""Headless Blender build of 栖灵's original VRM 1.0 mascot.

Run:  blender --background --python scripts/vrm/build_qiling_vrm.py
Requires the "VRM format" add-on (extension id: vrm) installed and enabled.

Environment variables:
  QILING_VRM_OUT           output model.vrm       (required)
  QILING_VRM_BLEND         output source .blend   (optional)
  QILING_VRM_THUMB         output thumbnail .png  (optional)
  QILING_VRM_SKIP_THUMB=1  skip the EEVEE render

Blender space convention: +Z up, -Y forward, +X is the character's left side,
which the VRM exporter mirrors into the VRM "*Right*" bones.
"""

import addon_utils
import bmesh
import bpy
import math
import os
import sys
from mathutils import Vector


def log(*args):
    print(*args)
    sys.stdout.flush()


SKULL_CENTER = Vector((0.0, 0.0, 0.90))
SKULL_RADII = Vector((0.175, 0.170, 0.165))
OUTLINE = (0.055, 0.045, 0.055)

# material: (srgb rgba, roughness, toon shading shift, outline width in m)
PALETTE = {
    "skin": ((0.930, 0.800, 0.720, 1), 0.65, -0.12, 0.0),
    "hair": ((0.085, 0.130, 0.200, 1), 0.45, -0.05, 0.0035),
    "hair_tie": ((0.780, 0.520, 0.150, 1), 0.50, -0.05, 0.0030),
    "eye_white": ((0.960, 0.955, 0.940, 1), 0.25, 0.0, 0.0),
    "iris": ((0.620, 0.320, 0.100, 1), 0.20, -0.10, 0.0),
    "pupil": ((0.045, 0.035, 0.035, 1), 0.20, 0.0, 0.0),
    "brow": ((0.070, 0.100, 0.155, 1), 0.50, 0.0, 0.0018),
    "mouth": ((0.430, 0.140, 0.160, 1), 0.55, 0.0, 0.0018),
    "cardigan": ((0.545, 0.230, 0.215, 1), 0.80, -0.15, 0.0035),
    "shirt": ((0.905, 0.880, 0.835, 1), 0.80, -0.12, 0.0030),
    "tie": ((0.780, 0.520, 0.150, 1), 0.70, -0.10, 0.0030),
    "skirt": ((0.135, 0.150, 0.205, 1), 0.85, -0.10, 0.0035),
    "socks": ((0.905, 0.880, 0.835, 1), 0.80, -0.10, 0.0030),
    "shoes": ((0.230, 0.150, 0.120, 1), 0.55, -0.08, 0.0035),
}

_MATERIALS = {}


def to_linear(c):
    """PALETTE is authored in sRGB; Blender and VRM want linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

# Rest pose (T-pose). Only ".L" entries; ".R" mirrors X.
RIG = {
    "hips": ((0.0, 0.0, 0.475), (0.0, 0.0, 0.545)),
    "spine": ((0.0, 0.0, 0.545), (0.0, 0.0, 0.625)),
    "chest": ((0.0, 0.0, 0.625), (0.0, 0.0, 0.735)),
    "neck": ((0.0, 0.0, 0.735), (0.0, 0.0, 0.790)),
    "head": ((0.0, 0.0, 0.790), (0.0, 0.0, 0.945)),
    "eye.L": ((0.062, -0.150, 0.905), (0.062, -0.190, 0.905)),
    "shoulder.L": ((0.025, 0.0, 0.730), (0.100, 0.0, 0.730)),
    "upper_arm.L": ((0.100, 0.0, 0.730), (0.190, 0.0, 0.720)),
    "lower_arm.L": ((0.190, 0.0, 0.720), (0.268, 0.0, 0.712)),
    "hand.L": ((0.268, 0.0, 0.712), (0.312, 0.0, 0.708)),
    "upper_leg.L": ((0.058, 0.0, 0.455), (0.058, 0.0, 0.275)),
    "lower_leg.L": ((0.058, 0.0, 0.275), (0.058, 0.0, 0.095)),
    "foot.L": ((0.058, 0.0, 0.095), (0.058, -0.115, 0.012)),
    "toes.L": ((0.058, -0.115, 0.012), (0.058, -0.168, 0.012)),
}

FINGER_PREFIXES = ("thumb_", "index_", "middle_", "ring_", "little_")

HAIR_CHAINS = {
    "hair_back": [
        (0.0, 0.115, 1.000),
        (0.0, 0.175, 0.945),
        (0.0, 0.218, 0.862),
        (0.0, 0.238, 0.772),
        (0.0, 0.232, 0.692),
    ],
    "hair_side.L": [
        (0.156, -0.030, 0.955),
        (0.174, -0.036, 0.878),
        (0.181, -0.030, 0.800),
    ],
    "hair_side.R": [
        (-0.156, -0.030, 0.955),
        (-0.174, -0.036, 0.878),
        (-0.181, -0.030, 0.800),
    ],
}

COLLIDERS = [
    ("collider_head", (0.0, 0.0, 0.900), (0.0, 0.0, 0.060), 0.215),
    ("collider_chest", (0.0, 0.0, 0.660), (0.0, 0.0, 0.060), 0.150),
]


def active():
    return bpy.context.active_object


def to_object_mode():
    obj = bpy.context.object
    if obj and obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def clear_scene():
    to_object_mode()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def material(name):
    if name in _MATERIALS:
        return _MATERIALS[name]
    srgb, rough, shift, outline = PALETTE[name]
    linear = tuple(to_linear(c) for c in srgb[:3]) + (srgb[3],)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = linear
        bsdf.inputs["Roughness"].default_value = rough
    mtoon = mat.vrm_addon_extension.mtoon1
    mtoon.enabled = True
    mtoon.pbr_metallic_roughness.base_color_factor = linear
    mtoon.pbr_metallic_roughness.roughness_factor = rough
    mtoon.pbr_metallic_roughness.metallic_factor = 0.0
    mtoon.alpha_mode = "OPAQUE"
    mtoon.shading_shift_factor = shift
    mtoon.shading_toony_factor = 0.45
    mtoon.shade_color_factor = tuple(to_linear(c) * 0.55 for c in srgb[:3])
    mtoon.gi_equalization_factor = 0.9
    if outline > 0:
        mt = mtoon.extensions.vrmc_materials_mtoon
        mt.outline_width_mode = "worldCoordinates"
        mt.outline_width_factor = outline
        mt.outline_color_factor = tuple(to_linear(c) for c in OUTLINE)
    _MATERIALS[name] = mat
    return mat


def rigid(obj, bone):
    """Bind every vertex of obj to a single bone (rigid skinning)."""
    group = obj.vertex_groups.get(bone) or obj.vertex_groups.new(name=bone)
    group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")


def finish(obj, mat, bone, smooth=True):
    obj.data.materials.append(material(mat))
    if smooth:
        for poly in obj.data.polygons:
            poly.use_smooth = True
    rigid(obj, bone)
    return obj


def bake(obj):
    """Move the object transform into the mesh so coords are world-relative."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def ellipsoid(name, center, radii, mat, bone, segments=24, rings=14):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments, ring_count=rings, radius=1.0, location=center
    )
    obj = active()
    obj.name = name
    obj.scale = radii
    bake(obj)
    return finish(obj, mat, bone)


def capsule(name, p0, p1, radius, mat, bone, squash=1.0):
    """Ellipsoid stretched along p0->p1: reads as a rounded art-toy limb."""
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    length = max(axis.length * 0.62, 0.002)
    quat = axis.normalized().to_track_quat("Z", "Y")
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=20, ring_count=12, radius=radius, location=(p0 + p1) / 2
    )
    obj = active()
    obj.name = name
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = quat
    obj.scale = (1.0, squash, length / radius)
    bake(obj)
    return finish(obj, mat, bone)


def box(name, center, size, mat, bone, bevel=0.0, rotation=None):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = active()
    obj.name = name
    obj.scale = size
    if rotation:
        obj.rotation_euler = rotation
    bake(obj)
    if bevel > 0:
        mod = obj.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod.limit_method = "NONE"
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return finish(obj, mat, bone, smooth=False)


def warp(obj, fn):
    for vert in obj.data.vertices:
        vert.co = fn(vert.co)


def clamp_front(obj, limit, keep_above):
    """Flatten an eye part onto one side of limit so morph masks stay exact."""
    if keep_above:
        warp(obj, lambda co: Vector((co.x, max(co.y, limit), co.z)))
    else:
        warp(obj, lambda co: Vector((co.x, min(co.y, limit), co.z)))


def keep_verts(obj, predicate):
    """Delete vertices whose position fails predicate(); re-bind what is left."""
    mesh = obj.data
    before = len(mesh.vertices)
    doomed = [i for i, v in enumerate(mesh.vertices) if not predicate(v.co)]
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in doomed], context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    rigid(obj, "head")
    log("HAIRCUT kept %d/%d verts" % (len(mesh.vertices), before))


# Face features sit in the lower half of the skull so the forehead has room for
# brows and bangs (chibi proportion).
EYE_X = 0.062
EYE_Z = 0.878
BROW_Z = 0.946
MOUTH_C = (0.0, -0.128, 0.805)
# Eye whites flatten to y >= EYE_FRONT, iris parts to y <= IRIS_BACK, so the
# iris mask selects whole vertices instead of slicing the mesh in half.
EYE_FRONT = -0.158
IRIS_BACK = -0.161

FACE = {
    "eye_L": ((EYE_X, -0.152, EYE_Z), (0.048, 0.030, 0.066), None),
    "eye_R": ((-EYE_X, -0.152, EYE_Z), (0.048, 0.030, 0.066), None),
    "iris_L": ((EYE_X, -0.170, EYE_Z), (0.038, 0.022, 0.054),
               lambda co: co.y < -0.160),
    "iris_R": ((-EYE_X, -0.170, EYE_Z), (0.038, 0.022, 0.054),
               lambda co: co.y < -0.160),
    "brow_L": ((EYE_X, -0.150, BROW_Z), (0.050, 0.022, 0.018), None),
    "brow_R": ((-EYE_X, -0.150, BROW_Z), (0.050, 0.022, 0.018), None),
    "mouth": (MOUTH_C, (0.032, 0.016, 0.024), None),
    "cheek_L": ((0.100, -0.098, 0.812), (0.042, 0.030, 0.034), None),
    "cheek_R": ((-0.100, -0.098, 0.812), (0.042, 0.030, 0.034), None),
    "jaw": ((0.0, -0.068, 0.740), (0.095, 0.075, 0.048), None),
}

MORPH_ORDER = [
    "neutral", "aa", "ih", "ou", "ee", "oh", "blink",
    "happy", "angry", "sad", "relaxed", "surprised",
    "lookUp", "lookDown", "lookLeft", "lookRight",
]


def mask_weight(co, region):
    center, radii, clip = FACE[region]
    if clip and not clip(co):
        return 0.0
    dx = (co.x - center[0]) / radii[0]
    dy = (co.y - center[1]) / radii[1]
    dz = (co.z - center[2]) / radii[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist >= 1.0:
        return 0.0
    if dist <= 0.60:
        return 1.0
    t = (dist - 0.60) / 0.40
    return 1.0 - t * t * (3.0 - 2.0 * t)


def scale_about(center, scale):
    c, s = Vector(center), Vector(scale)
    return lambda co: c + (co - c) * s


def move(offset):
    o = Vector(offset)
    return lambda co: co + o


def mouth_scale(width, height, hinge_up=0.0):
    return ("mouth", scale_about(
        (MOUTH_C[0], MOUTH_C[1], MOUTH_C[2] + hinge_up), (width, 1.0, height)))


def viseme(width, height, jaw):
    """Mouth opens downward from a hinge at the upper lip line."""
    ops = [mouth_scale(width, height, 0.013)]
    if jaw:
        ops.append(("jaw", move((0.0, 0.008, -jaw))))
    return ops


MORPH_OPS = {
    "aa": viseme(1.05, 0.42, 0.028),
    "ih": viseme(1.28, 0.58, 0.008),
    "ou": viseme(0.55, 0.55, 0.016),
    "ee": viseme(1.42, 0.34, 0.002),
    "oh": viseme(0.80, 0.76, 0.011),
    "blink": [("eye_L", scale_about(FACE["eye_L"][0], (1.0, 1.0, 0.05))),
              ("eye_R", scale_about(FACE["eye_R"][0], (1.0, 1.0, 0.05))),
              ("brow_L", move((0.0, 0.0, -0.004))),
              ("brow_R", move((0.0, 0.0, -0.004)))],
    "happy": [("eye_L", scale_about(FACE["eye_L"][0], (1.02, 1.0, 0.72))),
              ("eye_R", scale_about(FACE["eye_R"][0], (1.02, 1.0, 0.72))),
              ("brow_L", move((0.002, 0.0, 0.010))),
              ("brow_R", move((-0.002, 0.0, 0.010))),
              mouth_scale(1.22, 1.15),
              ("cheek_L", move((0.0, -0.002, 0.008))),
              ("cheek_R", move((0.0, -0.002, 0.008)))],
    "angry": [("brow_L", move((0.006, -0.004, -0.014))),
              ("brow_R", move((-0.006, -0.004, -0.014))),
              ("eye_L", scale_about(FACE["eye_L"][0], (1.0, 1.0, 0.85))),
              ("eye_R", scale_about(FACE["eye_R"][0], (1.0, 1.0, 0.85))),
              mouth_scale(1.10, 0.85, -0.004)],
    "sad": [("brow_L", move((-0.007, 0.0, 0.011))),
            ("brow_R", move((0.007, 0.0, 0.011))),
            ("eye_L", scale_about(FACE["eye_L"][0], (0.98, 1.0, 0.88))),
            ("eye_R", scale_about(FACE["eye_R"][0], (0.98, 1.0, 0.88))),
            mouth_scale(0.90, 0.60, 0.018),
            ("mouth", move((0.0, 0.0, -0.004)))],
    "relaxed": [("brow_L", move((0.001, 0.0, -0.007))),
                ("brow_R", move((-0.001, 0.0, -0.007))),
                ("eye_L", scale_about(FACE["eye_L"][0], (1.0, 1.0, 0.90))),
                ("eye_R", scale_about(FACE["eye_R"][0], (1.0, 1.0, 0.90))),
                mouth_scale(1.05, 0.95)],
    "surprised": [("brow_L", move((0.0, 0.0, 0.020))),
                  ("brow_R", move((0.0, 0.0, 0.020))),
                  ("eye_L", scale_about(FACE["eye_L"][0], (1.04, 1.0, 1.18))),
                  ("eye_R", scale_about(FACE["eye_R"][0], (1.04, 1.0, 1.18))),
                  mouth_scale(0.75, 1.20),
                  ("jaw", move((0.0, 0.006, -0.014)))],
    "lookLeft": [("iris_L", move((-0.012, 0.001, 0.0))),
                 ("iris_R", move((-0.012, 0.001, 0.0)))],
    "lookRight": [("iris_L", move((0.012, 0.001, 0.0))),
                  ("iris_R", move((0.012, 0.001, 0.0)))],
    "lookUp": [("iris_L", move((0.0, 0.002, 0.012))),
               ("iris_R", move((0.0, 0.002, 0.012))),
               ("brow_L", move((0.0, 0.0, 0.003))),
               ("brow_R", move((0.0, 0.0, 0.003)))],
    "lookDown": [("iris_L", move((0.0, 0.002, -0.012))),
                 ("iris_R", move((0.0, 0.002, -0.012))),
                 ("brow_L", move((0.0, 0.0, -0.004))),
                 ("brow_R", move((0.0, 0.0, -0.004)))],
}


def build_morphs(obj):
    obj.shape_key_add(name="Basis", from_mix=False)
    basis = [v.co.copy() for v in obj.data.vertices]
    for name in MORPH_ORDER:
        block = obj.shape_key_add(name=name, from_mix=False)
        touched = 0
        if name != "neutral":
            for index, co in enumerate(basis):
                cur = co
                for region, fn in MORPH_OPS[name]:
                    weight = mask_weight(cur, region)
                    if weight <= 0.0:
                        continue
                    cur = cur.lerp(fn(cur), weight)
                block.data[index].co = cur
                if (cur - co).length > 1e-6:
                    touched += 1
        log("MORPH %-10s verts=%d" % (name, touched))
    return obj


def build_rig():
    bpy.ops.icyp.make_basic_armature()
    arm = active()
    arm.name = "栖灵Rig"
    to_object_mode()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    bones = arm.data.edit_bones

    for name, (head, tail) in RIG.items():
        for target, sign in ((name, 1.0), (name.replace(".L", ".R"), -1.0)):
            bone = bones.get(target)
            if bone is None:
                log("WARN no bone %s" % target)
                continue
            bone.head = Vector((head[0] * sign, head[1], head[2]))
            bone.tail = Vector((tail[0] * sign, tail[1], tail[2]))

    for bone in list(bones):
        if bone.name.startswith(FINGER_PREFIXES):
            bones.remove(bone)

    for chain, points in HAIR_CHAINS.items():
        parent = bones["head"]
        for i in range(len(points) - 1):
            bone = bones.new("%s.%d" % (chain, i + 1))
            bone.head = points[i]
            bone.tail = points[i + 1]
            bone.parent = parent
            bone.use_deform = True
            parent = bone

    for name, head, tail, _radius in COLLIDERS:
        bone = bones.new(name)
        bone.head = head
        bone.tail = tail
        bone.parent = bones["head" if name.endswith("head") else "chest"]
        bone.use_deform = True

    bpy.ops.object.mode_set(mode="OBJECT")
    arm.data.vrm_addon_extension.spec_version = "1.0"
    return arm


def build_geometry():
    parts = []

    skull = ellipsoid("skull", SKULL_CENTER, SKULL_RADII, "skin", "head",
                      segments=32, rings=18)

    def chin(co):
        if co.z >= SKULL_CENTER.z:
            return co
        t = min(1.0, (SKULL_CENTER.z - co.z) / SKULL_RADII.z)
        return Vector((co.x * (1.0 - 0.30 * t * t),
                       co.y * (1.0 - 0.16 * t * t), co.z))

    warp(skull, chin)
    parts.append(skull)

    parts.append(ellipsoid("neck", (0, 0.005, 0.760), (0.048, 0.046, 0.060),
                           "skin", "neck"))
    parts.append(ellipsoid("torso", (0, 0, 0.615), (0.112, 0.088, 0.145),
                           "cardigan", "chest", segments=28, rings=16))
    parts.append(ellipsoid("hips", (0, 0, 0.500), (0.100, 0.082, 0.070),
                           "skirt", "hips"))

    skirt = ellipsoid("skirt", (0, 0, 0.478), (0.118, 0.108, 0.072), "skirt",
                      "hips", segments=28, rings=14)

    def flare(co):
        if co.z >= 0.478:
            return co
        t = min(1.0, (0.478 - co.z) / 0.072)
        k = 1.0 + 0.34 * t
        return Vector((co.x * k, co.y * k, co.z))

    warp(skirt, flare)
    parts.append(skirt)

    parts.append(ellipsoid("collar", (0, -0.040, 0.752), (0.048, 0.032, 0.020),
                           "shirt", "chest"))
    parts.append(box("tie", (0, -0.082, 0.686), (0.030, 0.012, 0.075), "tie",
                     "chest", bevel=0.006))

    for side, sign in (("L", 1.0), ("R", -1.0)):
        s = ".%s" % side
        parts.append(ellipsoid("shoulder" + s, (0.102 * sign, 0, 0.727),
                               (0.050, 0.048, 0.050), "cardigan", "shoulder" + s))
        parts.append(capsule("upper_arm" + s, (0.106 * sign, 0, 0.728),
                             (0.188 * sign, 0, 0.720), 0.040, "cardigan",
                             "upper_arm" + s))
        parts.append(capsule("lower_arm" + s, (0.192 * sign, 0, 0.720),
                             (0.264 * sign, 0, 0.712), 0.034, "skin",
                             "lower_arm" + s))
        parts.append(ellipsoid("hand" + s, (0.290 * sign, -0.004, 0.709),
                               (0.040, 0.032, 0.044), "skin", "hand" + s))
        parts.append(capsule("upper_leg" + s, (0.058 * sign, 0, 0.448),
                             (0.058 * sign, 0, 0.280), 0.050, "skin",
                             "upper_leg" + s))
        parts.append(capsule("lower_leg" + s, (0.058 * sign, 0, 0.278),
                             (0.058 * sign, 0, 0.105), 0.044, "socks",
                             "lower_leg" + s))
        parts.append(box("shoe" + s, (0.058 * sign, -0.050, 0.032),
                         (0.052, 0.092, 0.050), "shoes", "foot" + s, bevel=0.016))

        cx = EYE_X * sign
        white = ellipsoid("eye_white" + s, (cx, -0.150, EYE_Z),
                          (0.0340, 0.0120, 0.0500), "eye_white", "head",
                          segments=20, rings=12)
        clamp_front(white, EYE_FRONT, True)
        parts.append(white)
        iris = ellipsoid("iris" + s, (cx, -0.1670, EYE_Z - 0.002),
                         (0.0260, 0.0080, 0.0400), "iris", "head",
                         segments=20, rings=12)
        clamp_front(iris, IRIS_BACK, False)
        parts.append(iris)
        pupil = ellipsoid("pupil" + s, (cx, -0.1705, EYE_Z - 0.004),
                          (0.0115, 0.0060, 0.0175), "pupil", "head",
                          segments=14, rings=8)
        clamp_front(pupil, IRIS_BACK, False)
        parts.append(pupil)
        shine = ellipsoid("highlight" + s, (cx + 0.011 * sign, -0.1720, EYE_Z + 0.018),
                          (0.0080, 0.0055, 0.0100), "eye_white", "head",
                          segments=12, rings=8)
        clamp_front(shine, IRIS_BACK, False)
        parts.append(shine)
        parts.append(box("brow" + s, (cx, -0.148, BROW_Z),
                         (0.040, 0.010, 0.0065), "brow", "head", bevel=0.0035,
                         rotation=(0, math.radians(-6 * sign), 0)))

    parts.append(ellipsoid("mouth", MOUTH_C, (0.0240, 0.0080, 0.0120),
                           "mouth", "head", segments=18, rings=10))

    cap = ellipsoid(
        "hair_cap",
        SKULL_CENTER + Vector((0, 0.004, 0.010)),
        Vector((SKULL_RADII.x * 1.055, SKULL_RADII.y * 1.055,
                SKULL_RADII.z * 1.045)) + Vector((0, 0, 0.004)),
        "hair", "head", segments=32, rings=18,
    )

    def hairline(co):
        # Keep the cap everywhere except inside the oval face opening.
        if co.y >= -0.100:
            return True
        dx = co.x / 0.122
        dz = (co.z - 0.862) / 0.142
        return dx * dx + dz * dz > 1.0

    keep_verts(cap, hairline)
    solid = cap.modifiers.new("solid", "SOLIDIFY")
    solid.thickness = 0.006
    solid.offset = 1.0
    bpy.context.view_layer.objects.active = cap
    bpy.ops.object.modifier_apply(modifier=solid.name)
    rigid(cap, "head")
    parts.append(cap)

    # Bangs: one row of locks sharing a hairline just above the brows.
    for i, (ang, depth) in enumerate([(-0.66, 0.040), (-0.40, 0.052),
                                      (-0.14, 0.046), (0.14, 0.050),
                                      (0.40, 0.044), (0.66, 0.038)]):
        parts.append(ellipsoid("fringe_%d" % i,
                               (math.sin(ang) * 0.126, -0.158, 0.968 + depth),
                               (0.040, 0.024, depth), "hair", "head",
                               segments=16, rings=10))

    for chain, points in HAIR_CHAINS.items():
        for i in range(len(points) - 1):
            radius = (0.040 - 0.006 * i if chain == "hair_back"
                      else 0.028 - 0.004 * i)
            parts.append(capsule(
                "hair_%s_%d" % (chain.replace(".", "_"), i + 1),
                points[i], points[i + 1], radius, "hair",
                "%s.%d" % (chain, i + 1)))

    parts.append(ellipsoid("hair_tie", (0.0, 0.108, 1.004),
                           (0.030, 0.026, 0.024), "hair_tie", "head",
                           segments=16, rings=10))
    return parts


def join_parts(parts, arm):
    to_object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in parts:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = next(
        p for p in parts if p.name == "skull")
    bpy.ops.object.join()
    body = active()
    body.name = "栖灵"
    body.parent = arm
    body.matrix_parent_inverse = arm.matrix_world.inverted()
    body.modifiers.new("Armature", "ARMATURE").object = arm
    return body


def set_meta(arm, thumbnail=None):
    meta = arm.data.vrm_addon_extension.vrm1.meta
    meta.vrm_name = "宁娜 · 栖灵 3D"
    meta.version = "1.0.0"
    if not meta.authors:
        meta.authors.add().value = "栖灵"
    meta.copyright_information = "Copyright 2026 栖灵"
    meta.contact_information = "local project"
    if not meta.references:
        meta.references.add().value = "https://vrm-addon-for-blender.info/"
    meta.third_party_licenses = (
        "Built with VRM Add-on for Blender (MIT OR GPL-3.0-or-later)"
    )
    meta.avatar_permission = "everyone"
    meta.allow_excessively_violent_usage = False
    meta.allow_excessively_sexual_usage = False
    meta.commercial_usage = "corporation"
    meta.allow_political_or_religious_usage = False
    meta.allow_antisocial_or_hate_usage = False
    meta.credit_notation = "unnecessary"
    meta.allow_redistribution = True
    meta.modification = "allowModificationRedistribution"
    if thumbnail is not None:
        meta.thumbnail_image = thumbnail


EXPR_TO_KEY = {
    "neutral": "neutral", "aa": "aa", "ih": "ih", "ou": "ou", "ee": "ee",
    "oh": "oh", "blink": "blink", "happy": "happy", "angry": "angry",
    "sad": "sad", "relaxed": "relaxed", "surprised": "surprised",
    "look_up": "lookUp", "look_down": "lookDown",
    "look_left": "lookLeft", "look_right": "lookRight",
}
BINARY = {"happy", "angry", "sad", "relaxed", "surprised"}


def bind_expressions(arm, body):
    vrm1 = arm.data.vrm_addon_extension.vrm1
    preset = vrm1.expressions.preset
    keys = {k.name for k in body.data.shape_keys.key_blocks}
    for prop, shape_key in EXPR_TO_KEY.items():
        expr = getattr(preset, prop)
        expr.is_binary = prop in BINARY
        bind = expr.morph_target_binds.add()
        bind.node.mesh_object_name = body.name
        bind.index = shape_key
        bind.weight = 1.0
        if shape_key not in keys:
            log("WARN expression %s -> missing shape key %s" % (prop, shape_key))
    for value in ("EXPRESSION", "expression"):
        try:
            vrm1.look_at.type = value
            break
        except TypeError:
            continue
    vrm1.look_at.offset_from_head_bone = (0.0, 0.055, 0.100)
    log("EXPR bound=%d look_at=%s" % (len(EXPR_TO_KEY), vrm1.look_at.type))


def setup_spring_bones(arm):
    sb = arm.data.vrm_addon_extension.spring_bone1
    group = sb.collider_groups.add()
    group.vrm_name = "head_body"
    for name, _head, _tail, radius in COLLIDERS:
        collider = sb.colliders.add()
        collider.node.bone_name = name
        collider.shape.sphere.radius = radius
        collider.shape.sphere.offset = (0.0, 0.0, 0.0)
        group.colliders.add().collider = collider
    for chain, points in HAIR_CHAINS.items():
        spring = sb.springs.add()
        spring.vrm_name = chain
        spring.center.bone_name = "head"
        spring.collider_groups.add().collider_group = group
        for i in range(len(points) - 1):
            joint = spring.joints.add()
            joint.node.bone_name = "%s.%d" % (chain, i + 1)
            joint.hit_radius = 0.014
            joint.stiffness = max(4.0, 22.0 - 3.0 * i)
            joint.gravity_power = 0.0
            joint.gravity_dir = (0.0, 0.0, -1.0)
            joint.drag_force = 0.40
    log("SPRING springs=%d joints=%d colliders=%d groups=%d"
        % (len(sb.springs), sum(len(s.joints) for s in sb.springs),
           len(sb.colliders), len(sb.collider_groups)))


def audit(arm, body):
    bones = set(arm.data.bones.keys())
    orphan = [g.name for g in body.vertex_groups if g.name not in bones]
    unweighted = sum(1 for v in body.data.vertices
                     if sum(g.weight for g in v.groups) < 0.999)
    tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
    log("AUDIT tris=%d mats=%d bones=%d vgroups=%d orphan=%s unweighted=%d"
        % (tris, len(body.data.materials), len(bones), len(body.vertex_groups),
           orphan or "-", unweighted))


def render_thumbnail(path, size=512):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.66, 0.66, 0.70, 1.0)
        bg.inputs[1].default_value = 1.0
    light_data = bpy.data.lights.new("key", "SUN")
    light_data.energy = 3.0
    light = bpy.data.objects.new("key", light_data)
    scene.collection.objects.link(light)
    light.rotation_euler = (math.radians(40), math.radians(-12), math.radians(25))
    cam = bpy.data.objects.new("thumb", bpy.data.cameras.new("thumb"))
    scene.collection.objects.link(cam)
    cam.location = (0.62, -0.92, 0.98)
    target = Vector((0.0, 0.0, 0.63))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.ops.object.select_all(action="DESELECT")
    cam.select_set(True)
    light.select_set(True)
    bpy.ops.object.delete()


def main():
    out = os.environ.get("QILING_VRM_OUT")
    if not out:
        raise SystemExit("QILING_VRM_OUT is required")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    blend_out = os.environ.get("QILING_VRM_BLEND")
    thumb_out = os.environ.get("QILING_VRM_THUMB")

    if not any(m.__name__.endswith("vrm") for m in addon_utils.modules()):
        raise SystemExit("VRM add-on is not installed")
    if not hasattr(bpy.ops.export_scene, "vrm"):
        raise SystemExit("VRM add-on is not enabled")

    clear_scene()
    arm = build_rig()
    body = join_parts(build_geometry(), arm)
    build_morphs(body)
    set_meta(arm)
    bind_expressions(arm, body)
    setup_spring_bones(arm)
    audit(arm, body)

    if blend_out:
        blend_out = os.path.abspath(blend_out)
        os.makedirs(os.path.dirname(blend_out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=blend_out)
        log("BLEND %s" % blend_out)

    if thumb_out and os.environ.get("QILING_VRM_SKIP_THUMB") != "1":
        thumb_out = os.path.abspath(thumb_out)
        os.makedirs(os.path.dirname(thumb_out), exist_ok=True)
        try:
            render_thumbnail(thumb_out)
            set_meta(arm, bpy.data.images.load(thumb_out, check_existing=True))
            log("THUMB %s" % thumb_out)
        except Exception as exc:
            log("THUMB_FAILED %r" % (exc,))

    result = bpy.ops.export_scene.vrm(filepath=out)
    if result != {"FINISHED"}:
        raise SystemExit("VRM export failed: %s" % (result,))
    log("VRM %s %d bytes" % (out, os.path.getsize(out)))


if __name__ == "__main__":
    main()
