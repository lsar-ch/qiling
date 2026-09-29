"""把外部 GLB 角色转成符合本项目规格的 VRM 1.0 文件。

用法：
  blender --background --python scripts/vrm/build_vrm_from_glb.py

环境变量：
  DESKMATE_SRC_GLB   源 GLB 路径
  DESKMATE_VRM_OUT   输出 .vrm 路径
  DESKMATE_VRM_BLEND 可选，保存中间 .blend
  DESKMATE_VRM_THUMB 可选，输出缩略图 .png

设计要点（都是这个 GLB 的实测结论，改动前先读）：
  1. 源网格的 rest pose 就是标准 T-pose，但 pose bone 上带了一个 A-pose
     偏移四元数，导致蒙皮结果手臂下垂。必须先清空 action 再把所有
     pose bone 归零，否则 humanoid T-pose 判定和后续表情都会错。
  2. 源网格 40 万面、全平直着色（0 个 smooth 面），直接减面会变成水晶
     棱角，所以减面后必须补一次 smooth-by-angle。
  3. 五官坐标是用正交无光照特写 + 像素聚类 + 几何前表面探测得到的，
     不要凭感觉改；换模型要重新跑检测。
"""

import bpy
import math
import os
import sys
from mathutils import Matrix, Vector

SRC_GLB = os.environ.get(
    "DESKMATE_SRC_GLB",
    "/Users/lxb/Downloads/7c692c80-238a-4dad-b0c7-94e769d7b823.glb",
)
OUT_VRM = os.environ.get(
    "DESKMATE_VRM_OUT",
    "/Users/lxb/Documents/desktop assistant project/build/vrm/"
    "deskmate_glb/model.vrm",
)
OUT_BLEND = os.environ.get("DESKMATE_VRM_BLEND", "")
OUT_THUMB = os.environ.get("DESKMATE_VRM_THUMB", "")

DECIMATE_RATIO = float(os.environ.get("DESKMATE_DECIMATE", "0.09"))
TEX_SIZE = int(os.environ.get("DESKMATE_TEX", "1024"))

MAX_TRIS = 40000
MAX_MATERIALS = 16
MAX_SPRING_JOINTS = 30


def log(msg):
    print("[glb2vrm] " + msg)


# --------------------------------------------------------------------------
# 1. 导入与清理
# --------------------------------------------------------------------------

def use_english_ui():
    """VRM 插件的 zh_CN 翻译串占位符写错了（{human_bone} vs {human_bone_name}），
    在中文语言环境下 error_messages() 会直接 KeyError，所以强制切英文。"""
    try:
        prev = bpy.context.preferences.view.language
        bpy.context.preferences.view.language = "en_US"
        log("UI 语言 %s -> en_US（绕开插件中文翻译 bug）" % prev)
    except Exception as err:
        log("切换 UI 语言失败: %s" % err)


def import_source():
    # 注意：这里不能用 read_factory_settings，那会连带把 VRM 扩展一起禁用；
    # 只清空启动场景里的默认物体，保留用户偏好里已启用的插件。
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for block_list in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures,
                       bpy.data.actions, bpy.data.images, bpy.data.cameras,
                       bpy.data.lights, bpy.data.worlds):
        for block in list(block_list):
            if block.users == 0:
                block_list.remove(block)
    if not os.path.isfile(SRC_GLB):
        raise FileNotFoundError(SRC_GLB)
    bpy.ops.import_scene.gltf(filepath=SRC_GLB)

    # 源文件里混了一个默认圆球（"棱角球"），必须删掉
    for obj in list(bpy.data.objects):
        if obj.type not in {"MESH", "ARMATURE"}:
            bpy.data.objects.remove(obj, do_unlink=True)

    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("GLB 里没有骨架，无法做 humanoid 绑定")

    meshes = [o for o in bpy.data.objects
              if o.type == "MESH" and o.parent == armature]
    if not meshes:
        meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    body = max(meshes, key=lambda o: len(o.data.vertices))
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj is not body:
            log("删除多余网格 %s" % obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)

    return armature, body


def restore_t_pose(armature):
    """清掉 pose bone 上的 A-pose 偏移，让蒙皮结果回到 rest（T-pose）。"""
    if armature.animation_data and armature.animation_data.action:
        armature.animation_data.action = None
    for pb in armature.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    armature.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()


def tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)
def fix_leg_hierarchy(armature):
    """源骨架把大腿挂在了 Spine 下（Mixamo 导出异常），而 VRM 要求
    upperLeg 是 hips 的直接子骨，插件的层级校验会直接拒绝。这里重挂到
    Hips 并保持 matrix_local 不变，蒙皮结果不受影响。"""
    bones = armature.data.bones
    hips = bones.get("Hips")
    if hips is None:
        return
    targets = [n for n in ("LeftUpLeg", "RightUpLeg")
               if bones.get(n) is not None and bones[n].parent != hips]
    if not targets:
        return
    previous = bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    armature.hide_set(False)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = armature.data.edit_bones
        for name in targets:
            bone = edit_bones[name]
            local = bone.matrix.copy()
            bone.parent = edit_bones["Hips"]
            bone.use_connect = False
            bone.matrix = local
        log("重挂腿骨到 Hips: %s" % ", ".join(targets))
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    if previous is not None:
        bpy.ops.object.select_all(action="DESELECT")
        previous.select_set(True)
        bpy.context.view_layer.objects.active = previous



def decimate(body):
    before = tri_count(body)
    bpy.ops.object.select_all(action="DESELECT")
    body.hide_set(False)
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    mod = body.modifiers.new("decimate", "DECIMATE")
    mod.ratio = DECIMATE_RATIO
    # 减面器可能不是栈里第一个（前面有 armature），先挪到最前
    while body.modifiers.find("decimate") > 0:
        bpy.ops.object.modifier_move_up(modifier="decimate")
    bpy.ops.object.modifier_apply(modifier="decimate")
    after = tri_count(body)
    log("减面 %d -> %d 三角面 (ratio %.3f)" % (before, after, DECIMATE_RATIO))
    if after > MAX_TRIS:
        raise RuntimeError("减面后仍有 %d 面，超过 %d 上限" % (after, MAX_TRIS))


def smooth_shading(body):
    """源网格 40 万面全平直着色，减到 3.6 万面后会露水晶棱角。

    注意：不能用 bpy.ops.object.shade_auto_smooth()，4.x 里它插的是一个
    "Smooth by Angle" 几何节点修改器，会把网格按边完全 realize 开
    （顶点数 43k -> 108k，等于三角形数 x3，零共享）。18 个 morph target
    各存一份 position+normal 的话，文件会直接从 6MB 涨到 54MB。
    这里只设置 use_smooth 标志，让导出器自己按 UV 接缝拆分。
    """
    for poly in body.data.polygons:
        poly.use_smooth = True
    mesh = body.data
    if mesh.has_custom_normals:
        mesh.request_custom_normals_clear()
    mesh.update()
    log("全网格平滑着色（不使用 Smooth by Angle 修改器）")


def shrink_textures():
    total = 0
    for img in bpy.data.images:
        width, height = int(img.size[0]), int(img.size[1])
        if width <= TEX_SIZE and height <= TEX_SIZE:
            total += width * height
            continue
        log("贴图 %s %dx%d -> %d" % (img.name, width, height, TEX_SIZE))
        img.scale(TEX_SIZE, TEX_SIZE)
        total += TEX_SIZE * TEX_SIZE
    log("贴图总像素 %.1f MP" % (total / 1e6))


# --------------------------------------------------------------------------
# 2. 五官地标（实测值，单位米，模型局部坐标）
# --------------------------------------------------------------------------

FACE_X = 0.0025          # 面部中线
EYE_Z = 1.0015
EYE_DX = 0.0222
BROW_Z = 1.0145
BROW_DX = 0.0300
MOUTH = (FACE_X, -0.0930, 0.9517)
NOSE_TIP = (FACE_X, -0.1033, 0.9714)
CHIN_Z = 0.9448
FACE_FRONT_Y = -0.0909


def eye_center(sign):
    return Vector((FACE_X + sign * EYE_DX, FACE_FRONT_Y, EYE_Z))


def brow_center(sign):
    return Vector((FACE_X + sign * BROW_DX, FACE_FRONT_Y - 0.006, BROW_Z))


def smoothstep(edge0, edge1, x):
    if edge0 == edge1:
        return 0.0 if x < edge0 else 1.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def ellip(co, center, radii):
    dx = (co.x - center[0]) / radii[0]
    dy = (co.y - center[1]) / radii[1]
    dz = (co.z - center[2]) / radii[2]
    d = math.sqrt(dx * dx + dy * dy + dz * dz)
    return smoothstep(1.0, 0.35, d)


def lower_face_weight(co):
    """下巴/下颌区域：只要脸前部，避开头发壳和脖子。"""
    if co.y > -0.020:
        return 0.0
    vert = smoothstep(0.9250, 0.9450, co.z) * smoothstep(0.9950, 0.9750, co.z)
    horiz = smoothstep(0.0820, 0.0550, abs(co.x - FACE_X))
    return vert * horiz


def brow_weight(co):
    if co.y > -0.030:
        return 0.0
    w = max(ellip(co, brow_center(1.0), (0.034, 0.030, 0.016)),
            ellip(co, brow_center(-1.0), (0.034, 0.030, 0.016)))
    return w


def one_brow_weight(co, sign):
    if co.y > -0.030:
        return 0.0
    return ellip(co, brow_center(sign), (0.032, 0.030, 0.015))


def eye_weight(co, sign):
    if co.y > -0.030:
        return 0.0
    return ellip(co, eye_center(sign), (0.0175, 0.0175, 0.0135))


def mouth_weight(co):
    if co.y > -0.030:
        return 0.0
    return ellip(co, MOUTH, (0.0330, 0.0280, 0.0260))


def corner_weight(co, sign):
    """嘴角：左右各一个。"""
    if co.y > -0.030:
        return 0.0
    c = (MOUTH[0] + sign * 0.0255, MOUTH[1] + 0.004, MOUTH[2] + 0.001)
    return ellip(co, c, (0.0150, 0.0220, 0.0140))


def cheek_weight(co, sign):
    if co.y > -0.030:
        return 0.0
    c = (FACE_X + sign * 0.0430, -0.0780, 0.9750)
    return ellip(co, c, (0.0280, 0.0260, 0.0240))


# --------------------------------------------------------------------------
# 3. 表情 shape key
# --------------------------------------------------------------------------

def disp_blink(co):
    out = Vector()
    for sign in (1.0, -1.0):
        w = eye_weight(co, sign)
        if w <= 0.0:
            continue
        c = eye_center(sign)
        out.z += (c.z - co.z) * 0.92 * w
        out.y += 0.0016 * w
    return out


def disp_blink_one(sign):
    def fn(co):
        w = eye_weight(co, sign)
        if w <= 0.0:
            return Vector()
        c = eye_center(sign)
        return Vector((0.0, 0.0016 * w, (c.z - co.z) * 0.92 * w))
    return fn


def disp_look(dx, dz):
    def fn(co):
        out = Vector()
        for sign in (1.0, -1.0):
            w = eye_weight(co, sign)
            if w <= 0.0:
                continue
            out.x += dx * w
            out.z += dz * w
            out.y -= 0.18 * math.hypot(dx, dz) * w
        return out
    return fn


def jaw_rotate(co, angle_rad):
    """绕双耳连线（y=0, z=EAR_Z）把下半脸转一下。"""
    ear_z = 1.0050
    w = lower_face_weight(co)
    if w <= 0.0 or angle_rad == 0.0:
        return Vector()
    a = angle_rad * w
    dy = co.y - 0.0
    dz = co.z - ear_z
    cos_a, sin_a = math.cos(a), math.sin(a)
    ny = dy * cos_a - dz * sin_a
    nz = dy * sin_a + dz * cos_a
    return Vector((0.0, ny - dy, nz - dz))


def disp_viseme(angle, corner_x, corner_z, lip_forward):
    def fn(co):
        out = jaw_rotate(co, angle)
        w = mouth_weight(co)
        if w > 0.0:
            out.y -= lip_forward * w
        for sign in (1.0, -1.0):
            cw = corner_weight(co, sign)
            if cw > 0.0:
                out.x += sign * corner_x * cw
                out.z += corner_z * cw
        return out
    return fn


def disp_emotion(brow_dz, brow_dx, corner_dz, cheek_dz, eye_squint,
                 jaw_angle=0.0):
    def fn(co):
        out = Vector()
        w = brow_weight(co)
        if w > 0.0:
            out.z += brow_dz * w
            for sign in (1.0, -1.0):
                bw = one_brow_weight(co, sign)
                out.x += sign * brow_dx * bw
        for sign in (1.0, -1.0):
            cw = corner_weight(co, sign)
            if cw > 0.0:
                out.z += corner_dz * cw
        cwk = cheek_weight(co, 1.0) + cheek_weight(co, -1.0)
        out.z += cheek_dz * cwk
        if eye_squint:
            for sign in (1.0, -1.0):
                ew = eye_weight(co, sign)
                if ew > 0.0:
                    c = eye_center(sign)
                    out.z += (c.z - co.z) * eye_squint * ew
        out += jaw_rotate(co, jaw_angle)
        return out
    return fn


MORPHS = [
    ("neutral", lambda co: Vector()),
    ("aa", disp_viseme(-0.150, 0.002, -0.001, 0.001)),
    ("ih", disp_viseme(-0.055, 0.004, 0.001, 0.000)),
    ("ou", disp_viseme(-0.060, -0.006, -0.002, 0.006)),
    ("ee", disp_viseme(-0.045, 0.008, 0.002, 0.000)),
    ("oh", disp_viseme(-0.095, -0.003, -0.001, 0.004)),
    ("blink", disp_blink),
    ("blink_left", disp_blink_one(1.0)),
    ("blink_right", disp_blink_one(-1.0)),
    ("lookLeft", disp_look(-0.0055, 0.0)),
    ("lookRight", disp_look(0.0055, 0.0)),
    ("lookUp", disp_look(0.0, 0.0050)),
    ("lookDown", disp_look(0.0, -0.0050)),
    ("happy", disp_emotion(0.004, 0.001, 0.0075, 0.0045, 0.30)),
    ("angry", disp_emotion(-0.008, -0.0035, -0.0050, -0.0020, 0.18)),
    ("sad", disp_emotion(0.002, 0.0040, -0.0060, -0.0025, 0.0)),
    ("relaxed", disp_emotion(-0.002, 0.0005, 0.0022, 0.0010, 0.08)),
    ("surprised", disp_emotion(0.011, -0.001, -0.0020, 0.0000, 0.0,
                               jaw_angle=-0.055)),
]


def build_shape_keys(body):
    if body.data.shape_keys:
        bpy.context.view_layer.objects.active = body
        body.shape_key_clear()
    body.shape_key_add(name="Basis", from_mix=False)
    for name, fn in MORPHS:
        key = body.shape_key_add(name=name, from_mix=False)
        moved = 0
        for idx, vert in enumerate(body.data.vertices):
            d = fn(vert.co)
            if d.length > 1e-7:
                key.data[idx].co = vert.co + d
                moved += 1
        log("shape key %-12s 影响 %d 顶点" % (name, moved))
    body.active_shape_key_index = 0


# --------------------------------------------------------------------------
# 4. VRM 元数据 / 人骨 / 表情绑定
# --------------------------------------------------------------------------

HUMAN_BONES = {
    "hips": "Hips",
    "spine": "Spine",
    "chest": "Spine1",
    "upper_chest": "Spine2",
    "neck": "Neck",
    "head": "Head",
    "right_eye": None,          # 源模型没有眼球骨
    "left_eye": None,
    "jaw": None,
    "right_shoulder": "RightShoulder",
    "right_upper_arm": "RightArm",
    "right_lower_arm": "RightForeArm",
    "right_hand": "RightHand",
    "left_shoulder": "LeftShoulder",
    "left_upper_arm": "LeftArm",
    "left_lower_arm": "LeftForeArm",
    "left_hand": "LeftHand",
    "right_upper_leg": "RightUpLeg",
    "right_lower_leg": "RightLeg",
    "right_foot": "RightFoot",
    "right_toes": None,
    "left_upper_leg": "LeftUpLeg",
    "left_lower_leg": "LeftLeg",
    "left_foot": "LeftFoot",
    "left_toes": None,
}

FINGER_MAP = {
    "Thumb": ("thumb_metacarpal", "thumb_proximal", "thumb_distal"),
    "Index": ("index_proximal", "index_intermediate", "index_distal"),
    "Middle": ("middle_proximal", "middle_intermediate", "middle_distal"),
    "Ring": ("ring_proximal", "ring_intermediate", "ring_distal"),
    "Pinky": ("little_proximal", "little_intermediate", "little_distal"),
}

EXPR_TO_KEY = {
    "neutral": "neutral", "aa": "aa", "ih": "ih", "ou": "ou",
    "ee": "ee", "oh": "oh", "blink": "blink",
    "blink_left": "blink_left", "blink_right": "blink_right",
    "happy": "happy", "angry": "angry", "sad": "sad",
    "relaxed": "relaxed", "surprised": "surprised",
    "look_up": "lookUp", "look_down": "lookDown",
    "look_left": "lookLeft", "look_right": "lookRight",
}
BINARY = {"blink", "blink_left", "blink_right", "happy", "angry", "sad",
          "relaxed", "surprised"}


def set_meta(armature, thumbnail=None):
    meta = armature.data.vrm_addon_extension.vrm1.meta
    meta.vrm_name = "DeskMate GLB Persona"
    meta.version = "1.0.0"
    if not meta.authors:
        meta.authors.add().value = "DeskMate"
    meta.copyright_information = "Copyright 2026 DeskMate"
    meta.contact_information = "local project"
    if not meta.references:
        meta.references.add().value = "https://vrm-addon-for-blender.info/"
    meta.third_party_licenses = (
        "Built with VRM Add-on for Blender (MIT OR GPL-3.0-or-later)")
    # 挂件端要能自由加载、可商用、可二次分发
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


def bind_humanoid(armature, body):
    ext = armature.data.vrm_addon_extension
    ext.spec_version = "1.0"
    bones = ext.vrm1.humanoid.human_bones
    existing = {b.name for b in armature.data.bones}
    assigned = 0

    for vrm_name, bl_name in HUMAN_BONES.items():
        if not bl_name or bl_name not in existing:
            continue
        if not hasattr(bones, vrm_name):
            log("插件无此人骨槽位: %s" % vrm_name)
            continue
        getattr(bones, vrm_name).node.bone_name = bl_name
        assigned += 1

    for side, prefix in (("left", "Left"), ("right", "Right")):
        for finger, attrs in FINGER_MAP.items():
            for i, attr in enumerate(attrs, start=1):
                bl_name = "%sHand%s%d" % (prefix, finger, i)
                slot = "%s_%s" % (side, attr)
                if bl_name in existing and hasattr(bones, slot):
                    getattr(bones, slot).node.bone_name = bl_name
                    assigned += 1

    log("humanoid 映射 %d 根骨骼" % assigned)
    # error_messages / bones_are_correctly_assigned 是方法不是属性
    err = list(bones.error_messages())
    dup = list(bones.human_bone_duplication_error_messages())
    if err or dup:
        raise RuntimeError("人骨映射未通过插件校验: %s | %s"
                           % (err[:6], dup[:6]))
    log("插件人骨校验通过, assigned=%s" % bones.bones_are_correctly_assigned())
    # pose 才是字符串枚举；pose_enum 是 UI 辅助对象
    ext.vrm1.humanoid.pose = "restPositionPose"
    log("humanoid pose = restPositionPose")


def bind_expressions(armature, body):
    vrm1 = armature.data.vrm_addon_extension.vrm1
    preset = vrm1.expressions.preset
    keys = {k.name for k in body.data.shape_keys.key_blocks}
    bound = 0
    for prop, shape_key in EXPR_TO_KEY.items():
        if shape_key not in keys:
            log("WARN 缺少 shape key: %s (%s)" % (prop, shape_key))
            continue
        expr = getattr(preset, prop)
        while len(expr.morph_target_binds):
            expr.morph_target_binds.remove(len(expr.morph_target_binds) - 1)
        expr.is_binary = prop in BINARY
        bind = expr.morph_target_binds.add()
        bind.node.mesh_object_name = body.name
        bind.index = shape_key
        bind.weight = 1.0
        bound += 1
    for value in ("EXPRESSION", "expression"):
        try:
            vrm1.look_at.type = value
            break
        except TypeError:
            continue
    vrm1.look_at.offset_from_head_bone = (0.0, FACE_FRONT_Y - 0.01, 0.0)
    log("表情绑定 %d 个, look_at=%s" % (bound, vrm1.look_at.type))
    return bound


# --------------------------------------------------------------------------
# 5. 缩略图与导出
# --------------------------------------------------------------------------

def flip_normals_to_viewer(body):
    """源 GLB 的头发壳有相当一部分面法线朝内，Blender 会把它们算成黑色，
    缩略图看起来像破面。three.js 对 DoubleSide 材质本来就会把背面法线翻向
    观察者（gl_FrontFacing），所以挂件里的实际渲染是正确的。这里只在渲染
    缩略图时临时模拟同样的行为，渲染完立刻恢复，避免影响插件对材质节点图
    的识别。返回值是一个 restore 回调。"""
    import collections
    mats = [slot.material for slot in body.material_slots if slot.material]
    undo = []
    for mat in mats:
        if not mat.use_nodes:
            continue
        tree = mat.node_tree
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"),
                    None)
        if bsdf is None or "Normal" not in bsdf.inputs:
            continue
        sock = bsdf.inputs["Normal"]
        saved = [link.from_socket for link in tree.links
                 if link.to_node == bsdf and link.to_socket == sock]
        geo = tree.nodes.new("ShaderNodeNewGeometry")
        sign = tree.nodes.new("ShaderNodeMath")
        sign.operation = "MULTIPLY_ADD"
        sign.inputs[1].default_value = -2.0
        sign.inputs[2].default_value = 1.0
        scale = tree.nodes.new("ShaderNodeVectorMath")
        scale.operation = "SCALE"
        tree.links.new(geo.outputs["Normal"], scale.inputs[0])
        tree.links.new(geo.outputs["Backfacing"], sign.inputs[0])
        tree.links.new(sign.outputs[0], scale.inputs["Scale"])
        tree.links.new(scale.outputs[0], sock)
        undo.append((tree, geo, sign, scale, sock, saved))

    def restore():
        for tree, geo, sign, scale, sock, saved in undo:
            for node in (geo, sign, scale):
                tree.nodes.remove(node)
            for src in saved:
                tree.links.new(src, sock)
    return restore


def render_thumbnail(armature, body, path, size=512):
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj not in (armature, body):
            bpy.data.objects.remove(obj, do_unlink=True)
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 24
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.new("thumb_world")
    scene.world = world
    world.use_nodes = False
    world.color = (0.86, 0.86, 0.88)
    # 挂件场景只有 AmbientLight + 两盏 DirectionalLight，从不开 shadowMap；
    # 这里也必须关掉太阳阴影，否则减面后变大贴脸的头发卡片会在脸上留下
    # 一块块shadow acne，看起来像破面。
    scene.eevee.use_shadows = False
    for energy, rx, rz in ((3.2, 55, -25), (1.4, -60, 150)):
        light = bpy.data.lights.new("s", "SUN")
        light.energy = energy
        for attr in ("use_shadow", "casts_shadow"):
            try:
                setattr(light, attr, False)
                break
            except AttributeError:
                continue
        obj = bpy.data.objects.new("s", light)
        scene.collection.objects.link(obj)
        obj.rotation_euler = (math.radians(rx), 0.0, math.radians(rz))
    cam_data = bpy.data.cameras.new("thumb_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 0.30
    cam = bpy.data.objects.new("thumb_cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0.0, -1.5, 1.005)
    cam.rotation_euler = Vector((0.0, 1.0, 0.0)).to_track_quat(
        "-Z", "Y").to_euler()
    scene.render.filepath = path
    restore = flip_normals_to_viewer(body)
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        restore()
    img = bpy.data.images.load(path, check_existing=False)
    img.name = "vrm_thumbnail"
    try:
        img.pack()
    except Exception as err:
        log("缩略图打包失败: %s" % err)
    return img


def export_vrm(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # export_try_sparse_sk: 只存被表情改动过的顶点。我们的 morph 每个只影响
    # 几百~几千顶点，关掉它会让 18 个 target 各存一份完整 pos+normal（27MB），
    # 打开后降到个位数 MB。
    result = bpy.ops.export_scene.vrm(
        filepath=path,
        enable_advanced_preferences=True,
        export_try_sparse_sk=True,
    )
    if result != {"FINISHED"}:
        raise RuntimeError("VRM 导出返回 %s" % result)
    log("导出 %s (%.1f MB)" % (path, os.path.getsize(path) / 1e6))


def main():
    use_english_ui()
    armature, body = import_source()
    restore_t_pose(armature)
    bpy.context.view_layer.update()
    fix_leg_hierarchy(armature)
    bpy.context.view_layer.update()
    log("导入完成: 网格 %s, 骨骼 %d 根, %d 三角面"
        % (body.name, len(armature.data.bones), tri_count(body)))
    decimate(body)
    smooth_shading(body)
    shrink_textures()
    log("材质数 %d" % len(body.data.materials))
    if len(body.data.materials) > MAX_MATERIALS:
        raise RuntimeError("材质数超限")

    build_shape_keys(body)
    bind_humanoid(armature, body)
    set_meta(armature)

    thumb_path = OUT_THUMB or os.path.join(
        os.path.dirname(OUT_VRM), "thumbnail.png")
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    thumb = render_thumbnail(armature, body, thumb_path)
    set_meta(armature, thumbnail=thumb)
    bind_expressions(armature, body)

    if OUT_BLEND:
        os.makedirs(os.path.dirname(OUT_BLEND), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
        log("保存 %s" % OUT_BLEND)

    export_vrm(OUT_VRM)
    log("完成")


if __name__ == "__main__":
    main()
