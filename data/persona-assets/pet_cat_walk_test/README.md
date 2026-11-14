# pet_cat_walk_test（蓝猫 · 现行正式角色资产）

> **现行资产（2026-11-12）：v5 定稿** —— `model.glb` 为 83,221,276 B / 33 clip，
> SHA256 `f28ecbd8b36356abeba98eda3818a6cc3b5b708d5b4a89040173ad23de595a6c`，
> `sit_idle` 按 v17 原轨迹重建、时长 4.8s。权威归档与判据见
> `~/Documents/角色资料库/蓝猫/正式资产/00-资产清单.md`。
> **下方「最终版 v4」整节是 2026-11-02 的历史记录（14.28 MB / 174 骨 / 单条 Walking），
> 不代表当前文件。** 现行基线以 `manifest.json` 的 `glb.sha256` 与
> `正式资产/冻结指纹-v5-20261112.md` 为准。

---

# 历史记录：pet_cat_walk_test（测试资产）

## 当前内容（最终版 v4 · 2026-11-02 20:10）

- `model.glb`
  来源：`/Users/lxb/Documents/角色资料库/蓝猫/最终版/cat_metarig_walk_v4_refmatch.glb`
  网格：128,885 顶点 / 233,150 三角面 / 1 材质 / 3 张 2048 JPEG / **14.28 MB**
  骨架：`cat_metarig`，**174 关节**，带逆绑定矩阵，每顶点 4 权重
  动作：**仅 Walking**，1.000 秒（24 帧 @24fps），无缝循环
  上游定稿：`角色资料库/蓝猫/最终版/蓝猫_FINAL_v4_20261102.blend`（场景名 `cat_FINAL_v4`）
  冻结基线说明：`角色资料库/蓝猫/冻结基线/冻结点说明_v4.md`

**v4 是当前最终版**，唯一相对 v3 的改动是 baseColor 贴图灰度对齐角色设定原图。
几何 / 骨骼 / 权重 / 动画与 v3 逐字节一致（指纹校验 11 项全等，仅 basecolor md5 变化）。

### v4 相对 v3：把贴图亮度降回参考图灰度

用户反馈 v3「太亮、深色毛发体现不出来」。实测根因：v3 曲线在中低灰阶是全局 `x^0.5` 抬升，
把暗部整体抬了 +60 灰阶、明暗标准差从 31 压到 20.8，深色层次被压平。
v4 从**原始深色贴图**重做 LUT：黑场锚定 + 中间调对齐参考原图 + 高光保护，
控制点 `0→40, 37→72, 58→90, 91→124, 110→147, 133→167, 149→184, 161→194, 185→205, 255→225`。

| 项目 | 参考原图 | v3（旧） | **v4（最终版）** |
|---|---|---|---|
| baseColor 均值 | 145 | 163 | **144.9** |
| baseColor P5 / P50 / P90 | 90 / 147 / 184 | 122 / 167 / 183 | **90 / 146 / 184** |
| baseColor 明暗标准差 | 32.1 | 20.8 | **30.5** |
| 挂件光照下屏幕均值 | — | 144.7 | **127.9** |
| 屏幕 P5 / P95 / 最亮 | — | 84 / 203 / 244 | **61 / 192 / 239** |
| 几何 / 骨骼 / 动画 | — | — | 完全不变（522 通道、1.0 秒） |

参考基准：角色设定原图（毛发灰度 mean 145 / P5=90 / P50=147 / P90=184 / std 32.1），已逐分位对齐。
对比图：`角色资料库/蓝猫/阶段性产物/对比_参考图_当前v3_新v4_20261102.png`（左参考/中v3/右v4）。

### 历史版本（v1→v3，均已归档）

| 项目 | v1 | v2 | v3 |
|---|---|---|---|
| baseColor 均值 | 111/255 | 161/255 | 163/255 |
| >208 灰阶占比 | 0.4% | 2.0% | 0.12% |
| GLB 体积 | 16.26 MB | 14.48 MB | 14.11 MB |

v2 曲线 `out = 1-(1-in)^1.8` 会把毛尖推到接近纯白；v3 改成「中间调提亮 + 高光保护」
`w = smoothstep(0.45,0.85,x)`、`out = (1-w)·x^(1/2.0) + w·x`，但暗部抬升过多 → 由 v4 修正。
metallicRoughness 贴图与法线贴图全程未动。

### 配套的挂件灯光（在代码里，不在 GLB 里）

`apps/desktop/src/widget/AnimalStage.tsx`：

| 项目 | 值 |
|---|---|
| 色调映射 | `NeutralToneMapping`，`toneMappingExposure = 1.0` |
| 环境光 | AmbientLight **1.35** |
| 主光 | 3.3 暖白 `0xfff6ec` @ (0.55, 2.4, 1.6) |
| 补光 | 0.7 冷白 `0xe0eaff` @ (-0.9, 0.7, 1.2) |
| 轮廓光 | 0.3 `0xfffcf7` @ (-0.7, 1.4, -1) |

**若挂件里还偏亮/偏暗：改 `toneMappingExposure` 一个数即可，不用重新导出模型。**
注意该改动对所有动物类 persona 生效。

## 备份

- `model.glb.bak-20261102-2005-v3`  v3（提亮版）14.11 MB ← 上一版
- `model.glb.bak-20261102-1620-v2`  v2（旧提亮曲线）14.48 MB
- `model.glb.bak-20261102-1601-v1`  v1（未提亮）16.26 MB
- `model.glb.bak-20261102-1545-pre-stage18`
  最原始版本：128,885 顶点 / 27 关节 / Idle + Running + Walking + Walking.001（各 1.958 秒）
  md5：`b6c0ab9a3baecf43b5a52fec319c1b7b`（17,606,468 bytes）

## 回滚

```bash
cd "/Users/lxb/Documents/desktop assistant project/data/persona-assets/pet_cat_walk_test"
cp model.glb.bak-20261102-2005-v3 model.glb        # 回到 v3（提亮版）
cp model.glb.bak-20261102-1620-v2 model.glb        # 回到 v2
cp model.glb.bak-20261102-1601-v1 model.glb        # 回到 v1（未提亮）
cp model.glb.bak-20261102-1545-pre-stage18 model.glb   # 回到原始 27 关节版
```

改完需重启桌面应用才生效（GLB 通过 fetch 加载，`settings.local.json`
的 `active_persona_id` 当前为 `pet_cat_walk_test`）。

## 已知差异与缺口

1. 只有一条动作。挂件 `AnimalStage.tsx` 在 idle 类状态下找 `Idle` 后缀的 clip，
   找不到就不播放动画，表现为**模型静止站立**。点击触发（executing/click）时才播 Walking。
2. 关节数从 27 变为 174。Three.js 骨骼矩阵走纹理，理论开销可忽略，但需实测挂件帧率。
3. 前胸在动作第 20 帧左右有轻微变形，已由用户确认接受，不再修。
4. **GLB 不带 Blender 里的灯光**。要调整观感只能改贴图 / 材质，或改挂件灯光代码（优先改
   `toneMappingExposure`）。
5. **面部暂无任何可动性**：72 根面部骨（Rigify face rig）存在但权重全为 0
   （stage8 时剥除、映射到 `spine.006`）。要做表情/面部动态必须新增数据，
   会改动 `WEIGHTS_0` 或新增形态键 → 冻结基线须由 v4 升到 v5，动工前先建 v5 基线。

## 后续改动范围（用户 2026-11-02 20:10 确认）

**只允许改动画；若要动面部动态或做精细处理，须先升级冻结基线。
形象（贴图/材质/比例）与骨架（174 骨 / 拓扑 / 权重）已冻结。**

## 改动作 / 重新导出的标准流程

```bash
# 1) 从 v4 工程文件另存新 blend，在里面改动作
# 2) 一键导出（自动换回 v4 冻结贴图 + 自动比对指纹）
/Users/lxb/Documents/角色资料库/蓝猫/临时文件/metarig手K-20261102/export_frozen.sh \
   <新blend> <输出.glb> 24
```

链路：`export_glb_anim.py` → `glb_replace_image.py`（换回 **v4** 冻结贴图）→
`freeze_fingerprint.py` → `verify_frozen.py`（基线 `冻结点_v4_20261102.json`）。
输出 `PASS` 表示只有动画变了，可以上真机。

> 2026-11-02 20:10 修复：该脚本此前写死 v3 的 `cat_basecolor_frozen.jpg` 并用 v3 基线校验，
> 会在导出动作时把 v4 贴图静默覆盖回提亮版，且校验仍显示 PASS。现已默认使用 v4
> （可用 `BASE=<json> TEX=<jpg>` 环境变量覆盖）。空转自检结果：PASS。

## 其他可用工具

```bash
cd "/Users/lxb/Documents/角色资料库/蓝猫/临时文件/metarig手K-20261102"

# 按挂件真实光照预览（Three.js 物理单位等比还原，可直接看有没有过曝）
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python render_glb_app.py -- \
  "<glb>" test 6 1.35 3.3 0.7 0.3 "Khronos PBR Neutral" 1.0 natural

# 直接换贴图（不重新导出，体积不膨胀）
python3 glb_replace_image.py <in.glb> basecolor <new.jpg> <out.glb>

# 校验动画没被静态化
python3 verify_glb2.py <glb>
```

`render_glb_app.py` 的换算关系（Three.js r155+ 物理单位）：
`SUN 强度 = DirectionalLight.intensity`，`WORLD 强度 = AmbientLight.intensity / π`，
`view_transform = Khronos PBR Neutral` 等价于 `THREE.NeutralToneMapping`。
