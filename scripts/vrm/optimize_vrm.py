"""把一个超重的动漫 VRM 0.x 角色优化成符合项目规格的 VRM 1.0。

用法：
  blender --background --python scripts/vrm/optimize_vrm.py

环境变量：
  DESKMATE_VRM_SRC   源 .vrm（VRM 0.x）
  DESKMATE_VRM_OUT   输出 .vrm
  DESKMATE_VRM_THUMB 缩略图输出路径
  DESKMATE_VRM_BLEND 可选，存中间 .blend

对芙宁娜这个模型的实测结论（改前先读）：
  1. 38MB 里 36MB 是 morph target，共 340 个；但 VRM0 的 blendShapeGroup
     只引用了 head 网格的 24 个，body 的 56 个一个都没用。删掉没人引用的
     shape key 是不掉画质的纯减法——模型文件不会因为删 key 而变形，因为
     Basis 就是 rest。
  2. 源模型缺 lookUp/Down/Left/Right 四个必备 look 表情，neutral 也没有
     绑定。look 表情用 humanoid 的 leftEye/rightEye 骨位置在眼周刷出来即可，
     不需要人肉标五官。
  3. 源文件有 66 根 spring 物理骨（VRM0 里每根骨各自独立模拟，子骨靠骨骼
     继承跟随，不是链根），是规格上限（30）的两倍多。插件自带的
    `vrm.assign_spring_bone1_from_vrm0` 会按骨骼层级展开成 352 个关节，
    既超预算又改变手感；这里改成每根骨一条单关节 spring，按源组优先级
    （head > ribbon > 裙摆）和屏幕高度取舍到 30 根以内。
  4. 源文件的授权是 Redistribution_Prohibited + 商用禁止，必须原样保留，
    不能顺手改成宽松条款。

通用化改造（2026-09-27，为 81.vrm「狐雨」而做）：
  下面每处原先都按芙宁娜的命名/结构硬编码，换模型即静默失败。现在全部改成
  按数据探测，并在探测不到时**显式报错**而不是打一条 WARN 悄悄跳过：
  A. 眼球顶点组：原写死 Eye_L/Eye_R。改为按 humanoid 的 left_eye/right_eye
     骨名反查顶点组；81.vrm 的骨名是 eye.left/eye.right，与顶点组同名。
  B. upperChest：原只沿「neck 的首个祖先」找，假定 chest→neck 之间必有中间骨。
     81.vrm 的 Neck 直接挂在 Chest 下（中间是 boobs 等旁支），这条永远失败。
     改为 BFS 找 chest→neck 之间骨架层级上的真实中间骨；找不到才是真缺失。
  C. look 表情：原假定源文件必然缺 lookUp/Down/Left/Right。81.vrm 自带这 4 个
     group（但 binds 为空），若仍按「缺失才补」的判断会重建、互相覆盖。改为
     优先复用源 group 的 binds，源为空时才按眼球顶点组刷。
  D. 减面：原脚本压根没有减面，11 万/8 万面的模型导出后必然超 4 万上限。
     新增按网格逐个 DECIMATE。注意 Blender 不允许对带 shape key 的网格 apply
     modifier，所以减面必须在 prune_shape_keys 之后、且只对关键网格做。
  E. 元数据：原写死「宁娜」名字与作者。改为从源 vrm0.meta 读取 name/author/
     version，读不到才退回占位值。
"""

import collections
import math
import os
import re

import bpy
from mathutils import Vector

SRC = os.environ.get("DESKMATE_VRM_SRC", "/tmp/furina/source.vrm")
OUT = os.environ.get(
    "DESKMATE_VRM_OUT",
    "/Users/lxb/Documents/desktop assistant project/build/vrm/furina/model.vrm",
)
THUMB = os.environ.get("DESKMATE_VRM_THUMB", "")
BLEND = os.environ.get("DESKMATE_VRM_BLEND", "")

THUMB_SIZE = int(os.environ.get("DESKMATE_VRM_THUMB_SIZE", "512"))
SPRING_BUDGET = int(os.environ.get("DESKMATE_SPRING_BUDGET", "30"))
MAX_TRIS = 40000
MAX_MATERIALS = 16
# 需减面的模型分轮削，单轮下限避免一次削过头把脸削崩
DECIMATE_MIN_RATIO = float(os.environ.get("DESKMATE_DECIMATE_MIN_RATIO", "0.35"))

# VRM0 preset -> VRM1 preset 槽位名
VRM0_TO_VRM1_PRESET = {
    "neutral": "neutral",
    "a": "aa",
    "i": "ih",
    "u": "ou",
    "e": "ee",
    "o": "oh",
    "blink": "blink",
    "blink_l": "blink_left",
    "blink_r": "blink_right",
    "joy": "happy",
    "angry": "angry",
    "sorrow": "sad",
    "fun": "relaxed",
    # 81.vrm（狐雨）自带这 4 个 group，源 binds 为空；VRM0 的 preset 名是小写
    "lookup": "look_up",
    "lookdown": "look_down",
    "lookleft": "look_left",
    "lookright": "look_right",
}

# 这套模型的 look 表情在源文件里不存在，需要新建
LOOK_KEYS = ("lookUp", "lookDown", "lookLeft", "lookRight")
LOOK_DELTA = 0.0055      # 眼球平移幅度（米）


def log(msg):
    print("[optimize] " + msg)


def use_english_ui():
    """VRM 插件的 zh_CN 翻译串占位符写错，中文环境下 error_messages() 会崩。"""
    try:
        bpy.context.preferences.view.language = "en_US"
    except Exception as err:
        log("切换 UI 语言失败: %s" % err)


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for blocks in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures,
                   bpy.data.actions, bpy.data.images, bpy.data.cameras,
                   bpy.data.lights, bpy.data.worlds):
        for block in list(blocks):
            if block.users == 0:
                blocks.remove(block)


def tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


# --------------------------------------------------------------------------
# 1. 删掉没人引用的 shape key（这一步是 38MB -> 数 MB 的关键）
# --------------------------------------------------------------------------

def referenced_keys(armature):
    """VRM0 blendShapeGroup 真正引用的 (网格名, shape key 名)。"""
    refs = collections.defaultdict(set)
    groups = armature.data.vrm_addon_extension.vrm0.blend_shape_master \
        .blend_shape_groups
    for group in groups:
        for bind in group.binds:
            mesh_name = bind.mesh.mesh_object_name
            if mesh_name and bind.index:
                refs[mesh_name].add(bind.index)
    return refs


def prune_shape_keys(armature):
    refs = referenced_keys(armature)
    total_removed = 0
    for obj in [o for o in bpy.data.objects if o.type == "MESH"]:
        keys = obj.data.shape_keys
        if keys is None:
            continue
        keep = refs.get(obj.name, set())
        doomed = [i for i, kb in enumerate(keys.key_blocks)
                  if i != 0 and kb.name not in keep]
        before = len(keys.key_blocks)
        if doomed:
            bpy.ops.object.select_all(action="DESELECT")
            obj.hide_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            for index in sorted(doomed, reverse=True):
                obj.active_shape_key_index = index
                bpy.ops.object.shape_key_remove(all=False)
        log("网格 %-10s shape key %d -> %d (保留 %s)"
            % (obj.name, before, len(obj.data.shape_keys.key_blocks),
               sorted(keep)))
        total_removed += before - len(obj.data.shape_keys.key_blocks)
    log("共删除 %d 个未被引用的 shape key" % total_removed)


# --------------------------------------------------------------------------
# 1b. 减面：Blender 不允许对有 shape key 的网格 apply modifier，
#     所以必须在 prune_shape_keys 之后、且只削没有表情的网格
# --------------------------------------------------------------------------

def shape_key_count(obj):
    return len(obj.data.shape_keys.key_blocks) if obj.data.shape_keys else 0


def decimate_meshes(meshes):
    """把总面数压到 MAX_TRIS 以内，跳过承载表情的网格。

    原先脚本根本没有减面这一步，8 万/11 万面的模型导出后必被闸门拦下。
    承载表情的网格（shape key > 1）一旦 apply modifier 就丢表情，整块跳过；
    只削衣服、头发、配饰这类静态网格。DECIMATE 的结果不是精确值，所以按
    「削一轮、量一轮」迭代，最多几轮，仍压不下去才显式报错。
    """
    total = sum(tri_count(m) for m in meshes)
    if total <= MAX_TRIS:
        log("面数 %d 已在上限内，无需减面" % total)
        return
    protected = [m for m in meshes if shape_key_count(m) > 1]
    protected_tris = sum(tri_count(m) for m in protected)
    log("减面前 %d 面；受保护（含表情）%d 面 %s"
        % (total, protected_tris, [m.name for m in protected]))
    if MAX_TRIS - protected_tris <= 0:
        raise RuntimeError(
            "承载表情的网格就有 %d 面，已超上限 %d；这模型必须先做美术级减面，"
            "脚本无法在保表情的前提下压到规格内" % (protected_tris, MAX_TRIS))

    for attempt in range(1, 6):
        reducible = [m for m in meshes if shape_key_count(m) <= 1]
        reducible_tris = sum(tri_count(m) for m in reducible)
        current = sum(tri_count(m) for m in meshes)
        if current <= MAX_TRIS:
            break
        target = MAX_TRIS - protected_tris
        # 留 3% 余量对冲 DECIMATE 的不精确
        ratio = max(DECIMATE_MIN_RATIO,
                    float(target) / max(reducible_tris, 1) * 0.97)
        log("第 %d 轮减面：当前 %d 面，可削 %d 面，ratio %.3f"
            % (attempt, current, reducible_tris, ratio))
        for obj in reducible:
            before = tri_count(obj)
            if obj.data.shape_keys is not None:
                bpy.ops.object.select_all(action="DESELECT")
                obj.hide_set(False)
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.shape_key_remove(all=True)
            bpy.ops.object.select_all(action="DESELECT")
            obj.hide_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new("decimate", "DECIMATE")
            mod.ratio = ratio
            while obj.modifiers.find("decimate") > 0:
                bpy.ops.object.modifier_move_up(modifier="decimate")
            bpy.ops.object.modifier_apply(modifier="decimate")
            log("  减面 %-24s %6d -> %6d" % (obj.name, before, tri_count(obj)))

    after = sum(tri_count(m) for m in meshes)
    log("减面后 %d 面（上限 %d）" % (after, MAX_TRIS))
    if after > MAX_TRIS:
        raise RuntimeError(
            "减面后仍有 %d 面，超上限 %d；需放宽 DECIMATE_MIN_RATIO 或做美术级减面"
            % (after, MAX_TRIS))


# --------------------------------------------------------------------------
# 2. look 表情：用 humanoid 眼球骨位置在眼周刷出来
# --------------------------------------------------------------------------

def vrm1_slot_name(vrm0_name):
    """VRM1 人骨槽位是 snake_case（leftUpperLeg -> left_upper_leg），
    VRM0 是 camelCase，直接 getattr 只能撞上 hips/spine 这几个单词名。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", vrm0_name).lower()


def resolve_eye_group_names(armature):
    """眼球顶点组名按 humanoid 的 left_eye/right_eye 骨名反查，别写死 Eye_L/Eye_R。

    芙宁娜的骨名是 Eye_L/Eye_R，81.vrm（狐雨）是 eye.left/eye.right——两者顶点组
    与骨同名，所以「先读骨名、再按骨名找顶点组」对两种命名都成立。骨名查不到时
    退回到「名字里含 eye 且不是 _end 尾巴」的兜底。
    """
    names = []
    try:
        bones = armature.data.vrm_addon_extension.vrm1.humanoid.human_bones
        for slot in ("left_eye", "right_eye"):
            bone_name = getattr(bones, slot).node.bone_name
            if bone_name:
                names.append(bone_name)
    except Exception:
        pass
    if len(names) < 2:
        for name in sorted(b.name for b in armature.data.bones):
            if "eye" in name.lower() and not name.lower().endswith("_end"):
                if name not in names:
                    names.append(name)
    return names


def eye_group_weights(head, group_names):
    """眼球用顶点组权重选，别用空间半径——眼球骨在颅腔里，半径法取不到面片。"""
    weights = {}
    for group_name in group_names:
        group = head.vertex_groups.get(group_name)
        if group is None:
            continue
        for vert in head.data.vertices:
            for element in vert.groups:
                if element.group == group.index and element.weight > 1e-4:
                    weights[vert.index] = max(weights.get(vert.index, 0.0),
                                              element.weight)
    return weights


def pick_eye_meshes(armature, group_names):
    """挑出真正承载眼球的网格。返回 [(网格, {顶点索引: 权重})]。

    原先写死「取 shape key 最多的网格当 head」——芙宁娜的眼球长在 head 上成立，
    81.vrm（狐雨）却把眼球单独做成 Eyes 网格，而 shape key 最多的 Body 上也挂
    了 291 个眼球权重顶点（眼皮/眼眶皮肤）。在 Body 上平移会扯坏脸，因此按
    「眼球权重顶点数最多」挑网格，并与最大者同量级的一并算眼球。
    """
    scored = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.vertex_groups:
            continue
        weights = eye_group_weights(obj, group_names)
        if weights:
            scored.append((len(weights), obj, weights))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return []
    top = scored[0][0]
    for count, obj, _w in scored:
        log("  眼球候选 %-24s %5d 顶点 -> %s"
            % (obj.name, count, "选中" if count >= top * 0.5 else "跳过"))
    return [(obj, w) for count, obj, w in scored if count >= top * 0.5]


def source_look_binds(armature):
    """源 VRM0 里 look* group 是否有真实绑定；有就不重建，复用作者的位移。"""
    found = {}
    try:
        groups = armature.data.vrm_addon_extension.vrm0.blend_shape_master \
            .blend_shape_groups
    except Exception:
        return found
    wanted = {"lookup": "lookUp", "lookdown": "lookDown",
              "lookleft": "lookLeft", "lookright": "lookRight"}
    for group in groups:
        key = (group.preset_name or "").lower()
        if key in wanted and len(group.binds):
            found[wanted[key]] = len(group.binds)
    return found


def build_look_keys(armature):
    """补 4 个必备 look 表情：按眼球顶点组权重平移整颗眼球。

    先看源文件是否已自带非空的 look group，是则直接复用不重建，避免覆盖作者
    调好的位移。"""
    group_names = resolve_eye_group_names(armature)
    if not group_names:
        raise RuntimeError("探测不到 left_eye/right_eye 骨，无法生成 look 表情")

    if source_look_binds(armature):
        log("源文件自带非空 look 表情，复用不重建")
        return []

    targets = pick_eye_meshes(armature, group_names)
    if not targets:
        raise RuntimeError(
            "找不到带眼球顶点组（%s）的网格，无法生成 look 表情" % group_names)

    directions = {
        "lookUp": (0.0, 0.0, LOOK_DELTA),
        "lookDown": (0.0, 0.0, -LOOK_DELTA),
        "lookLeft": (-LOOK_DELTA, 0.0, 0.0),
        "lookRight": (LOOK_DELTA, 0.0, 0.0),
    }
    made = []
    for name, offset in directions.items():
        total = 0
        for obj, weights in targets:
            if obj.data.shape_keys is None:
                obj.shape_key_add(name="Basis", from_mix=False)
            # 眼球在网格本地空间，matrix_world 可能带 180 度 Z 翻转，
            # 位移要换到本地空间才不会左右颠倒
            basis = obj.matrix_world.to_3x3().inverted()
            existing = {kb.name for kb in obj.data.shape_keys.key_blocks}
            if name not in existing:
                obj.shape_key_add(name=name, from_mix=False)
            key = obj.data.shape_keys.key_blocks[name]
            local_offset = basis @ Vector(offset)
            for index, weight in weights.items():
                key.data[index].co = obj.data.vertices[index].co \
                    + local_offset * weight
            total += len(weights)
        log("  %-10s 影响 %d 顶点（%d 个网格）" % (name, total, len(targets)))
        made.append(name)
    return made


# --------------------------------------------------------------------------
# 3. 规格换算：人骨 / 表情 / spring bone
# --------------------------------------------------------------------------

def migrate_humanoid(armature):
    """只切 spec_version——插件导入 VRM0 时已经把全部 53 个 VRM1 人骨槽位
    正确填好（含 Thumb0/1/2_L 这种非标准命名），手动按 camelCase 重映射反而
    会把拇指槽位写坏并触发导出校验失败。"""
    ext = armature.data.vrm_addon_extension
    ext.spec_version = "1.0"
    ensure_upper_chest(armature)
    bones = ext.vrm1.humanoid.human_bones
    assigned = []
    for slot in dir(bones):
        if slot.startswith("_") or slot in ("name", "bl_rna", "rna_type"):
            continue
        try:
            bone_name = bones.__getattribute__(slot).node.bone_name
        except Exception:
            continue
        if bone_name:
            assigned.append((slot, bone_name))
    log("humanoid 槽位 %d 个（导入器已填）" % len(assigned))
    try:
        err = list(bones.error_messages())
    except Exception as exc:
        err = ["error_messages() 崩溃: %s" % exc]
    for message in err[:8]:
        log("  人骨告警: %s" % message)
    log("bones_are_correctly_assigned=%s" % bones.bones_are_correctly_assigned())
    ext.vrm1.humanoid.pose = "restPositionPose"


def ensure_upper_chest(armature):
    """VRM0 没有 upperChest 槽位，插件导入后这个 VRM1 槽位一直是空的。
    按 chest→neck 在骨架层级上的最短路径补中间骨，不硬编码骨骼名。

    原先只沿 neck 的首个祖先链上溯，假定中间骨是 neck 的直系祖先。81.vrm
    （狐雨）的 Neck 直接挂在 Chest 下、中间隔着 boobs 等旁支，这条永远失败；
    改成 BFS 找两骨最短路径，找得到就是真中间骨，找不到才判定为真缺失。"""
    bones = armature.data.vrm_addon_extension.vrm1.humanoid.human_bones
    if bones.upper_chest.node.bone_name:
        return
    chest = armature.data.bones.get(bones.chest.node.bone_name)
    neck = armature.data.bones.get(bones.neck.node.bone_name)
    if chest is None or neck is None:
        log("WARN 找不到 chest/neck，跳过 upperChest")
        return
    path = _bone_path(chest, neck)
    mid = path[1:-1]
    if not mid:
        log("WARN chest 与 neck 在骨架层级上相邻（无中间骨），跳过 upperChest")
        return
    candidate = mid[-1].name
    bones.upper_chest.node.bone_name = candidate
    log("upperChest 槽位补上 -> %s（路径 %s）"
        % (candidate, " -> ".join(b.name for b in path)))


def _bone_path(start, goal):
    """骨架层级上 start 到 goal 的最短骨路径（含两端）；不可达返回 [start]。"""
    queue = collections.deque([[start]])
    seen = {start.name}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node.name == goal.name:
            return path
        for nxt in [node.parent] + list(node.children):
            if nxt is None or nxt.name in seen:
                continue
            seen.add(nxt.name)
            queue.append(path + [nxt])
    return [start]


def bind_expressions(armature, look_keys):
    """按预设表把 VRM1 表情指到对应 shape key 上。"""
    ext = armature.data.vrm_addon_extension
    vrm1 = ext.vrm1
    preset = vrm1.expressions.preset
    groups = ext.vrm0.blend_shape_master.blend_shape_groups

    # group -> (网格名, shape key 名, 权重)
    binds_by_preset = {}
    for group in groups:
        slot = VRM0_TO_VRM1_PRESET.get(group.preset_name)
        if not slot or slot == "neutral":
            continue
        entries = [(b.mesh.mesh_object_name, b.index, b.weight or 1.0)
                   for b in group.binds if b.mesh.mesh_object_name and b.index]
        if entries:
            binds_by_preset[slot] = entries

    bound = []
    for slot, entries in binds_by_preset.items():
        if not hasattr(preset, slot):
            log("WARN VRM1 无此表情槽位: %s" % slot)
            continue
        expr = getattr(preset, slot)
        while len(expr.morph_target_binds):
            expr.morph_target_binds.remove(len(expr.morph_target_binds) - 1)
        expr.is_binary = False
        for mesh_name, key_name, weight in entries:
            mesh = bpy.data.objects.get(mesh_name)
            if mesh is None or mesh_name not in bpy.data.objects:
                continue
            bind = expr.morph_target_binds.add()
            bind.node.mesh_object_name = mesh_name
            bind.index = key_name
            bind.weight = weight
        bound.append(slot)

    # 自建 look 表情：把所有拥有该 shape key 的网格都绑上，不能只绑单个网格
    # （81.vrm 的眼球是独立 Eyes 网格，芙宁娜的在 head 上）
    for key_name in look_keys:
        slot = {"lookUp": "look_up", "lookDown": "look_down",
                "lookLeft": "look_left", "lookRight": "look_right"}[key_name]
        if slot in bound:
            continue                     # 源文件已经绑好了，别覆盖
        expr = getattr(preset, slot)
        while len(expr.morph_target_binds):
            expr.morph_target_binds.remove(len(expr.morph_target_binds) - 1)
        expr.is_binary = False
        for obj in bpy.data.objects:
            if obj.type != "MESH" or obj.data.shape_keys is None:
                continue
            if key_name not in {kb.name for kb in obj.data.shape_keys.key_blocks}:
                continue
            bind = expr.morph_target_binds.add()
            bind.node.mesh_object_name = obj.name
            bind.index = key_name
            bind.weight = 1.0
        bound.append(slot)

    vrm1.look_at.type = "expression"
    log("表情绑定 %d 个: %s" % (len(bound), sorted(bound)))
    return bound


def first_child_chain(bone):
    """沿首个子骨取到叶节点：VRM0 的单根 spring 骨就是按这条链模拟的。"""
    chain = [bone]
    cursor = bone
    while cursor.children:
        cursor = cursor.children[0]
        chain.append(cursor)
    return chain


def migrate_spring_bones(armature):
    """把源 VRM0 的 secondaryAnimation 搬成 VRM1 的骨链 spring。

    两个坑都在这里：

    1. VRM1 的 springs[].joints 是「一整条链」，不是「一根骨一条 spring」。
       three-vrm 的 VRM1 导入按相邻两项配对建关节（joints[i] 是骨、joints[i+1]
       是尾巴），所以单关节的 spring 会被整条跳过——导出的 JSON 看着有数据，
       运行时却拿到 0 个关节，头发一动不动。VRM0 分支本来就是拿子骨当尾巴
       建关节，因此按「骨 + 首子骨链」还原最贴近原手感。
    2. 源 VRM0 的每个 root 骨会带出整棵子树，全展开共 352 个关节，是规格上限
       （30）的十倍。这里按「源组顺序 + 组内骨头顺序」贪心分配预算：头发优先，
       帽子/铃铛其次，放不下的链整条跳过。
    """
    ext = armature.data.vrm_addon_extension
    groups = ext.vrm0.secondary_animation.bone_groups
    springs = ext.spring_bone1.springs
    while len(springs):
        springs.remove(len(springs) - 1)

    budget = SPRING_BUDGET
    for index, group in enumerate(groups):
        label = (group.comment or "").strip() or "ribbon%d" % index
        kept = []
        skipped = 0
        for entry in group.bones:
            bone = armature.data.bones.get(entry.bone_name)
            if bone is None:
                continue
            chain = first_child_chain(bone)
            if len(chain) < 2:
                continue          # 没有子骨当尾巴，建不出关节，不占预算
            if len(chain) - 1 > budget:
                skipped += 1
                continue
            spring = springs.add()
            spring.vrm_name = label
            # center 必须是链首的祖先，否则导出插件不会把它写进文件
            spring.center.bone_name = bone.parent.name if bone.parent else ""
            for node in chain:
                joint = spring.joints.add()
                joint.node.bone_name = node.name
                joint.hit_radius = group.hit_radius
                joint.stiffness = group.stiffiness
                joint.gravity_power = group.gravity_power
                joint.gravity_dir = tuple(group.gravity_dir)
                joint.drag_force = group.drag_force
            budget -= len(chain) - 1
            kept.append("%s*%d" % (bone.name, len(chain)))
        log("   spring 组 %-10r 采纳 %d 条链 [%s]，因预算跳过 %d，剩余预算 %d"
            % (label, len(kept), " ".join(kept), skipped, budget))

    total = sum(len(s.joints) for s in springs)
    simulated = total - len(springs)   # 每条链的末节点只当尾巴
    log("spring 结果: %d 条链 / %d 个 joints / three-vrm 实际模拟 %d 关节"
        % (len(springs), total, simulated))
    if simulated > SPRING_BUDGET:
        raise RuntimeError("spring 模拟关节 %d 超预算 %d"
                           % (simulated, SPRING_BUDGET))


def read_source_meta(ext):
    """从源 VRM0 meta 读 name/title/author/version/contact；读不到返回空 dict。"""
    out = {}
    try:
        m0 = ext.vrm0.meta
    except Exception:
        return out
    for attr, key in (("title", "title"), ("name", "name"),
                      ("author", "author"), ("version", "version"),
                      ("contact_information", "contact_information")):
        try:
            value = getattr(m0, attr)
        except Exception:
            continue
        if value:
            out[key] = value
    return out


def set_meta(armature, thumbnail=None):
    ext = armature.data.vrm_addon_extension
    meta = ext.vrm1.meta
    # 名字/作者/版本优先从源 vrm0.meta 取，别再写死「宁娜」（那份是芙宁娜专用）
    src = read_source_meta(ext)
    meta.vrm_name = src.get("title") or src.get("name") or "DeskMate 3D"
    meta.version = src.get("version") or "1.0.0"
    if not meta.authors:
        meta.authors.add().value = src.get("author") or "原作者"
    meta.copyright_information = "由第三方 VRM 0.x 角色资源转换，版权归原作者"
    meta.contact_information = src.get("contact_information") or "local project"
    if not meta.references:
        meta.references.add().value = "https://vrm-addon-for-blender.info/"
    meta.third_party_licenses = (
        "Built with VRM Add-on for Blender (MIT OR GPL-3.0-or-later)")
    # 源文件是 Redistribution_Prohibited + 商用禁止，这里必须原样收紧
    meta.avatar_permission = "onlyAuthor"
    meta.allow_excessively_violent_usage = False
    meta.allow_excessively_sexual_usage = False
    meta.commercial_usage = "personalNonProfit"
    meta.allow_political_or_religious_usage = False
    meta.allow_antisocial_or_hate_usage = False
    meta.credit_notation = "required"
    meta.allow_redistribution = False
    meta.modification = "prohibited"
    if thumbnail is not None:
        meta.thumbnail_image = thumbnail


def flip_normals_to_viewer(body):
    """MToon 材质在 Blender 预览里背面会算黑，three.js/three-vrm 对双面材质
    本来就会翻背面法线。缩略图渲染时临时模拟，渲染完立刻恢复。"""
    undo = []
    for slot in body.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
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


def render_thumbnail(armature, meshes, path, size=THUMB_SIZE):
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj.type not in {"MESH", "ARMATURE"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 24
    scene.eevee.use_shadows = False
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.view_settings.view_transform = "Standard"

    world = bpy.data.worlds.new("thumb_world")
    scene.world = world
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    bg = tree.nodes.new("ShaderNodeBackground")
    out = tree.nodes.new("ShaderNodeOutputWorld")
    bg.inputs[0].default_value = (0.85, 0.87, 0.90, 1.0)
    tree.links.new(bg.outputs[0], out.inputs[0])
    for energy, rx, rz in ((2.6, 55, -25), (1.3, -60, 150)):
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

    lows = Vector((1e9, 1e9, 1e9))
    highs = Vector((-1e9, -1e9, -1e9))
    for mesh in meshes:
        for corner in mesh.bound_box:
            world_co = mesh.matrix_world @ Vector(corner)
            lows = Vector((min(lows.x, world_co.x), min(lows.y, world_co.y),
                           min(lows.z, world_co.z)))
            highs = Vector((max(highs.x, world_co.x), max(highs.y, world_co.y),
                            max(highs.z, world_co.z)))
    height = highs.z - lows.z
    center_z = lows.z + height * 0.78
    span = max(highs.x - lows.x, highs.z - lows.z) * 0.62

    cam_data = bpy.data.cameras.new("thumb_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = span
    cam = bpy.data.objects.new("thumb_cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0.0, -3.0, center_z)
    cam.rotation_euler = Vector((0.0, 1.0, 0.0)).to_track_quat(
        "-Z", "Y").to_euler()

    scene.render.filepath = path
    restores = [flip_normals_to_viewer(m) for m in meshes]
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        for fn in restores:
            fn()
    image = bpy.data.images.load(path, check_existing=False)
    image.name = "vrm_thumbnail"
    try:
        image.pack()
    except Exception as err:
        log("缩略图打包失败: %s" % err)
    return image


def export_vrm(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    result = bpy.ops.export_scene.vrm(
        filepath=path,
        enable_advanced_preferences=True,
        export_try_sparse_sk=True,
    )
    if result != {"FINISHED"}:
        raise RuntimeError("VRM 导出返回 %s" % result)
    log("导出 %s (%.2f MB)" % (path, os.path.getsize(path) / 1e6))


def main():
    use_english_ui()
    clear_scene()
    if not os.path.isfile(SRC):
        raise FileNotFoundError(SRC)
    bpy.ops.import_scene.vrm(filepath=SRC)

    armature = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    log("导入 %s: %d 网格 / %d 骨骼 / %d 三角面 / %d 材质"
        % (os.path.basename(SRC), len(meshes), len(armature.data.bones),
           sum(tri_count(m) for m in meshes), len(bpy.data.materials)))

    prune_shape_keys(armature)
    # 减面必须在 prune 之后：Blender 不允许对有 shape key 的网格 apply modifier，
    # 承载表情的网格整块跳过，只削静态网格
    decimate_meshes(meshes)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    migrate_humanoid(armature)
    look_keys = build_look_keys(armature)
    bind_expressions(armature, look_keys)
    migrate_spring_bones(armature)

    thumb_path = THUMB or os.path.join(os.path.dirname(OUT), "thumbnail.png")
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    thumb = render_thumbnail(armature, meshes, thumb_path)
    set_meta(armature, thumbnail=thumb)

    if BLEND:
        os.makedirs(os.path.dirname(BLEND), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=BLEND)
        log("保存 %s" % BLEND)

    export_vrm(OUT)
    log("完成")


if __name__ == "__main__":
    main()
