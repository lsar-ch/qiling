# VRM 资产处理手册（踩坑与判据）

日期：2026-09-24　设计规格见 `docs/WIDGET-VRM-3D-PLAN.md`。

这是一份**判据手册**，不是教程。每条按「现象 → 判据 → 动作」写，
目的是下次换模型时不用重建知识。

配套工具（改模型前先跑，别凭记忆判断）：

| 工具 | 作用 |
| --- | --- |
| `scripts/vrm/optimize_vrm.py` | VRM0 → VRM1 优化流水线（Blender headless） |
| `scripts/vrm/verify_vrm.py` | 静态结构校验（GLB JSON 层） |
| `apps/desktop/scripts/check_vrm.mjs` | three-vrm 运行时校验（表情/人骨/加载） |

## 0. 出问题先跑这两条

```bash
python3 scripts/vrm/verify_vrm.py <model.vrm>
cd apps/desktop && node scripts/check_vrm.mjs <model.vrm>
```

静态校验全绿**不代表**运行时正常。这次就是静态 OK、运行时 spring 拿到 0 关节。
物理是否真在动必须实测，见 §3.1。

## 1. VRM 0.x 与 VRM 1.0 的结构差异

写代码前先认清版本，字段名和形状都不同，混用会静默出错。

| 项目 | VRM 0.x | VRM 1.0 |
| --- | --- | --- |
| 扩展键 | `VRM` | `VRMC_vrm` |
| 人骨 | `humanBones` 是 **list**，项为 `{bone, node}` | `humanBones` 是 **dict**，`{boneName: {node}}` |
| 槽位命名 | camelCase，如 `leftUpperLeg` | snake_case，如 `left_upper_leg` |
| `upperChest` | **不存在这个槽位** | 存在 |
| 表情 preset 名 | `joy`/`sorrow`/`fun`/`a`/`i`/... | `happy`/`sad`/`relaxed`/`aa`/`ih`/... |
| spring | `secondaryAnimation.boneGroups`，字段 `jointNames`，拼写是 `stiffiness` | `springs`，字段 `joints`，`stiffness` |
| 授权 | `Redistribution_Prohibited` 等枚举 | `allowRedistribution` 布尔等 |

**动作**：别手写字段映射，让 Blender 的 VRM 插件导入后再导出，
只补它没覆盖的槽位（见 §2.1、§4）。

## 2. Blender / bpy 陷阱

### 2.1 bpy 对象不能用 `is` 比较

**现象**：`if walker is not chest` 永远为真，人骨补位静默不执行，
日志里只有一条 WARN，模型少一根人骨。

**判据**：每次访问 `data.bones[...]` 都返回**新的包装对象**，身份不相等。

**动作**：比较用 `!=`，或直接比 `.name`。日志要打印实际结果，
不要只打印「跳过」——否则失败和成功长得一样。

### 2.2 中文 UI 下 `error_messages()` 会崩

**现象**：插件的 `bones.error_messages()` 在 `zh_CN` 下抛异常，导出前校验中断。

**判据**：插件翻译串的占位符有误，属插件 bug，不是模型问题。

**动作**：脚本开头把 `bpy.context.preferences.view.language` 切成 `en_US`。

### 2.3 `bones_are_correctly_assigned()` 是方法不是属性

**判据**：写成属性会拿到函数对象，永远 truthy。

**动作**：`bones.bones_are_correctly_assigned()`，且要在切英文 UI 之后调用。

## 3. spring bone：最容易静默失败的地方

### 3.1 VRM1 的 `joints` 是骨链，不是骨列表

**现象**：导出的 JSON 里 `springs` 有数据、`verify_vrm.py` 也通过，
但模型加载后头发**完全不动**，`vrm.springBoneManager._joints.length` 是 0。

**判据**：three-vrm 的 VRM1 导入按**相邻两项配对**建关节
（`joints[i]` 当骨、`joints[i+1]` 当尾巴），代码形态是 `if (prevSchemaJoint)`。
所以**单关节的 spring 会被整条跳过**。

**动作**：每条 spring 至少写两个节点（骨 + 子骨）。要还原 VRM0 手感，
就写「根骨 → 首子骨 → … → 叶节点」的完整链。

**必须实测的检查**（静态校验查不出来）：

```bash
cd apps/desktop && node --input-type=module -e '
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import fs from "node:fs";
globalThis.self = globalThis;
globalThis.Image = class { constructor(){this.width=1;this.height=1;}
  set src(_v){setTimeout(()=>this.onload&&this.onload(),0);} };
if (!globalThis.URL.createObjectURL) {
  globalThis.URL.createObjectURL=()=>"blob:stub"; globalThis.URL.revokeObjectURL=()=>{};
}
const l = new GLTFLoader(); l.register((p)=>new VRMLoaderPlugin(p));
const b = fs.readFileSync(process.argv[1]);
const g = await l.parseAsync(b.buffer.slice(b.byteOffset, b.byteOffset+b.byteLength), "");
const vrm = g.userData.vrm; VRMUtils.rotateVRM0(vrm);
const joints = [...vrm.springBoneManager._joints];
const before = joints.map(j=>j.bone.quaternion.clone());
for (let i=0;i<180;i++) vrm.update(1/60);
const moved = joints.filter((j,i)=>j.bone.quaternion.angleTo(before[i])>1e-4).length;
console.log("关节数:", joints.length, "摆动:", moved);
if (joints.length === 0) { console.error("spring 全丢：joints 是单节点链"); process.exit(1); }
' <model.vrm>
```

### 3.2 插件自带的迁移会把关节数炸开

**现象**：`vrm.assign_spring_bone1_from_vrm0` 把 66 根骨迁成 **352 个关节**，
是规格上限（30）的十倍。

**判据**：它按骨骼层级把每棵子树完整展开，而 VRM0 的 `boneGroups[].bones`
只是链根骨，子树会自动跟随；展开后父子链互相重叠。

**动作**：别用这个 API，按源组自己建链（见 `optimize_vrm.py:migrate_spring_bones`）。
预算不够时按「源组顺序 + 组内骨头顺序」贪心保留；本模型取舍是
头发（5 链 14 关节）> 帽子铃铛（11 链）> 裙摆（1 链），共 30 关节。

### 3.3 `center` 必须是链首的祖先

**判据**：导出插件会向上遍历链首的祖先链做校验，不是祖先就**丢弃 center**，
不会报错。

**动作**：`center` 取链首骨的 `parent`；导出后确认 JSON 里 `center` 字段存在。

## 4. 表情（expression）

### 4.1 缺失的 preset 不会报错，只会不生效

**判据**：`lookAt.type` 需要 `lookUp/Down/Left/Right` 四个 preset。
挂件代码若 `setValue("lookLeft", …)` 而模型没有该槽位，调用会被静默忽略。

**动作**：用 `apps/desktop/scripts/check_vrm.mjs` 逐项检查 15 个必备表情，
不要只检查「有没有 expressions 字段」。

### 4.2 `neutral` 允许空绑定

**判据**：`neutral` 就是 rest 状态，VRM 1.0 允许 `morphTargetBinds` 为空
（本模型源文件就是 0 bind）。校验脚本要把它当合法，否则永远 FAIL。

### 4.3 眼球位移表情要按顶点组选，不能按空间半径

**判据**：眼球骨在颅腔内部，半径法取不到眼球面片。

**动作**：用 `Eye_L`/`Eye_R` **顶点组权重**筛选顶点（本模型 160 个）。
`head` 网格的 `matrix_world` 可能带 180° Z 翻转，位移要经
`matrix_world.to_3x3().inverted()` 换回本地空间，否则左右会颠倒。

## 5. 体积与性能

### 5.1 大文件通常死在无人引用的 morph target

**判据**：本模型 38MB 里 **36MB** 是 morph target，共 340 个；
但 VRM0 的 `blendShapeGroups.binds` 只引用了 head 网格的 24 个，
body 的 56 个一个都没用。

**动作**：按「有 bind 引用的 shape key 名」反查，删掉其余（本模型删 89 个）。
**不掉画质**，因为 Basis 就是 rest 状态。删完 38MB → 9.17MB。

**注意**：删除要按索引倒序逐个 `shape_key_remove(all=False)`。

### 5.2 导出的 morph target 数会被 primitive 放大

**判据**：校验脚本常按 `sum(len(primitive.targets))` 统计，同一 shape key
在多个 primitive 上各算一次（85 = body 1 + head 25 + 尾巴 2，再乘 primitive 数）。
真实 shape key 只有 28 个。别把这个数当「表情数量」。

### 5.3 稀疏 morph 能显著减小体积

**动作**：导出时开 `export_try_sparse_sk=True`（配合
`enable_advanced_preferences=True`）。

### 5.4 别调用 VRMUtils.combineSkeletons()，会把帽子类刚性饰件弄丢

**现象**：Blender 里帽子完好，运行时整顶礼帽不渲染（就是「形象修改后帽子不对」）。

**判据**：`combineSkeletons()` 重建 `skinIndex` 与 Skeleton（514→509 根骨），
挂在 spring 骨上的刚性饰件（Hat1/Hat3/Hat5）在播放 VRMA 后才暴露问题：
无动画时两版仅差 1 像素，播 120 帧后差 16323 像素。顶点/骨骼数值探针抓不到，
**只有 A/B 截图对照能验证**。

**动作**：`VrmStage` 只保留 `removeUnnecessaryVertices()`。性能上也无需它：
只省 5 根骨，没有实际收益。

## 6. 授权（每次都确认，别偷懒继承）

**判据**：源文件 `meta` 的授权条款是法律边界，转换**只能收紧不能放宽**。
本模型源文件是 `Redistribution_Prohibited` + 商用禁止。

**动作**：转换后逐项核对并打印。本模型写入的是：
`avatarPermission=onlyAuthor`、`commercialUsage=personalNonProfit`、
`creditNotation=required`、`allowRedistribution=False`、
`modification=prohibited`、四个 `allow*Usage` 全 False。

**坑**：`modification` 的枚举只有 `prohibited` /
`allowModification` / `allowModificationRedistribution`，
**没有** `prohibitedModification` 这个写法。

## 7. 换新模型的标准流程

1. 导入源文件，打印网格/骨骼/面数/材质，确认总量在规格内
2. 按 bind 引用清理无用 shape key
3. 切 `spec_version=1.0`，补齐缺失人骨槽位（重点查 `upperChest`）
4. 对照 15 个必备表情，缺的补（look 系列按眼球顶点组生成）
5. 重建 spring（骨链形式，控制在 30 关节内）
6. 按源文件收紧授权
7. 跑 §0 的两条校验 + §3.1 的运行时摆动实测
8. 确认缩略图渲染正常（MToon 背面法线要模拟 three.js 的翻转）

## 8. 已知未解 / 待验证

- `q裙摆` 组只保留 1 条链，裙子基本无物理；要恢复需放宽 30 关节预算，
  或对裙摆骨骼做局部降采样
- `neutral` 空绑定在当前壳子里合法；若将来有壳子严格要求非空，
  需要挂一个空的 Basis 绑定
- 缩略图渲染里 MToon 背面法线靠临时改节点树模拟，未在真实三维查看器复核

## 9. VRMA 往返编辑（拿 Blender 改动作参数）

### 9.1 导出的骨骼集跟着模型漂，不跟着源片段

**现象**：拿 k81 / komano 的 VRM 导一条动作库的 `idle.vrma` 再导回去，
文件从 52 骨变成 53 骨：`upperChest` 没了，多出 `leftEye` / `rightEye`。

**判据**：导出的 `humanBones` 是按**当前模型**的人骨映射重建的，不是照源片段。
k81 / komano 的骨架本来就是 Chest → Neck，中间没有 upperChest 骨
（`optimize_vrm.py:ensure_upper_chest` 的 BFS 探过，确属真缺失，不是脚本没跑），
而模型的映射里挂着 eye.left / eye.right，于是导出就带眼骨。

**动作**：导出后跑一遍归一化，别手改 JSON：

```bash
python3 scripts/vrm/normalize_vrma.py --source /tmp/idle_original.vrma <导出文件>
```

它删掉眼骨/jaw 槽位，并把 `upperChest` 的节点与通道从源片段搬回来（时间轴按目标
时长缩放）。`--check` 只体检。校验脚本 `check_vrma.mjs` 已按 52 骨规范集卡死，
少了或多了一根都 FAIL。

### 9.2 场景帧范围会静默截断长动作

**现象**：345 帧（14.33s）的 `idle.vrma` 导入后导回去只剩 250 帧 / 10.38s，
动作被砍掉四分之一，没有任何报错。

**判据**：Blender 场景默认 `frame_end = 250`，导出只覆盖场景帧范围。

**动作**：导出前按导入后的动作长度撑开帧范围，或直接用
`scripts/vrm/roundtrip_vrma.py`（它同时处理帧范围与幅度/时长倍数）：

```bash
blender --background --python scripts/vrm/roundtrip_vrma.py -- \
    --model data/persona-assets/k81/model.vrm \
    --motion /tmp/idle_original.vrma --out build/vrma/idle_edited.vrma \
    --amplitude 1.5 --duration 1.4
python3 scripts/vrm/normalize_vrma.py --source /tmp/idle_original.vrma build/vrma/idle_edited.vrma
```

### 9.3 模型缺 upperChest 不影响挂件播放

**判据**：`createVRMAnimationClip` 按**模型**的人骨建轨道：拿 k81 跑 52 骨和
53 骨的片段都只出 52 条轨道，`upperChest` 那路被丢掉不报错；换成带 upperChest 的
`vrm_demo` 才有 `Normalized_Upper_Chest.quaternion`。所以骨骼集漂移是**文件卫生**
问题（库要统一、闸门要拦得住），不是 k81 上看得见的动作缺失。
