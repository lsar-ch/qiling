# VRM 资产导出规范（T1）

日期：2026-09-25　配套闸门实现见 `services/ai-service/app/core/vrm_validator.py`

目标：**在导出工具侧一次做对**，让资产进 DeskMate 后不需要任何手工调整。
这份文档是给「导出的人」看的清单；判据与踩坑细节在 `VRM-ASSET-NOTES.md`。

## 0. 一句话流程

```text
VRoid Studio / Blender 按本规范导出
  → 打成 assets.zip（结构见 §4）
  → 导入 DeskMate 角色页
  → 闸门自动校验：通过即落盘，不通过直接拒绝并列出原因
```

## 1. 硬性规格（闸门会拦，必须满足）

| 项目 | 要求 | 不满足时 |
| --- | --- | --- |
| 格式 | **VRM 1.0** | 导出时选 1.0；0.x 先跑 `scripts/vrm/optimize_vrm.py` |
| 三角面 | ≤ 40000 | 减面 |
| 材质数 | ≤ 16 | 合并材质/贴图集 |
| spring bone 关节 | ≤ 30（数法见 §3） | 裁剪物理骨预算 |
| 核心人骨 | 20 根齐全 | 导出前补骨映射 |
| 必备表情 | 15 项齐全 | 补齐表情 |
| 授权四项边界 | 全部 false | 在导出工具里关掉 |
| 缩略图 | 建议有 | 只警告，不拦 |
| 体积 | 建议 < 12MB | 只警告，不拦 |

## 2. 必备表情与动作命名

**15 个表情 preset**（缺一个就会被拦）：

`aa` `ih` `ou` `ee` `oh` `blink` `happy` `angry` `sad` `relaxed` `neutral`
`lookUp` `lookDown` `lookLeft` `lookRight`

**11 个 VRMA 动作名**（文件名即 trigger，缺哪个运行时回退 idle）：

`idle` `listening` `thinking` `speaking` `executing` `awaiting_approval`
`success` `error` `click` `project` `hover`

## 3. spring bone 的关节怎么数（最容易踩的坑）

VRM 1.0 的 `springs[].joints` 是**骨链**，不是骨列表：相邻两项配对成一个
关节，每条的末节点只当尾巴。

```text
实际关节数 = 所有 joints 条目数 - spring 链数
```

例：17 条链 / 47 个条目 → 30 个关节（正好卡上限）。

Blender 插件的 `assign_spring_bone1_from_vrm0` 会把关节炸到几百，**不要用**；
按 `scripts/vrm/optimize_vrm.py` 的骨链形式重建。

## 4. 资产包结构

```text
assets.zip
├── model.vrm              # 必需，且只能有一个
├── vrma/                  # 可选
│   ├── idle.vrma          # 文件名必须是 §2 的 11 个 trigger 之一
│   └── success.vrma
└── avatar.png             # 可选，文件名以 avatar 开头；加载期占位图
```

导入是**整体替换**语义：新包不带某个动作，旧动作会被清掉。
zip 内路径不允许含 `..`。

## 5. VRoid Studio 导出清单

1. VRM Settings → Export Format 选 **VRM 1.0**
2. 表情：确认自带 15 项基础表情（VRoid 默认齐全，改动面部后要复查）
3. 头发物理：VRoid 默认物理链较多，导出后先跑 §7 校验；超 30 关节需裁剪
4. 授权：按实际意图设置；模型来自第三方时，**保持原作者的收紧条款**
5. 导出后立即跑 §7 校验，再打包

## 6. Blender 导出清单

1. 用 `scripts/vrm/optimize_vrm.py` 走完整流水线（已实现下面前 4 条）：
   - 按 bind 引用清理无用 shape key（38MB → 9MB 的关键）
   - `spec_version=1.0` + 补齐缺失人骨槽位（重点查 `upperChest`）
   - 补齐 15 个表情（look 系列按眼球顶点组生成）
   - 重建 spring 为骨链形式并控在 30 关节内
   - 按源文件收紧授权
2. 导出前跑 `python3 scripts/vrm/verify_vrm.py <model.vrm>`
3. 打包成 §4 结构

## 7. 导出后自检（30 秒）

```bash
python3 scripts/vrm/verify_vrm.py <model.vrm>
cd apps/desktop && node scripts/check_vrm.mjs <model.vrm>
```

第一条是结构层（与导入闸门同一份规则），第二条是 three-vrm 运行时层。
**两条都绿不等于渲染正确**：像 skinIndex 被重组导致饰件不显示这类问题，
只有真实截图对照能发现，见 `VRM-ASSET-NOTES.md` §5.4。

## 8. 闸门不能替你做的事

闸门只判定**结构**。下面这些修不了，只能导出侧保证：

- 模型本身的绑定/权重质量（穿模、飞件）
- spring 手感（僵硬、抽搐）——需要真实观察动画
- 表情是否「好看」，闸门只看有没有绑定
- 授权条款是否与实际使用相符（闸门只检查四项边界）
