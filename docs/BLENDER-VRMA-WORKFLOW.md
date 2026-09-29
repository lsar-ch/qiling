# Blender 调整与适配 VRMA 动作规范（2026-09-26）

## 定位

- Blender：制作/修正动作内容，输出标准 `.vrma`。
- 动作实验室 `#/motion-lab`：只调运行时参数（循环 trigger、交叉淡化、时长、冷却、权重），不负责骨骼编辑。

## 工具

- Blender 4.2 或更新版本（官方 addon 支持到 5.x）。
- VRM Add-on for Blender：<https://github.com/saturday06/VRM-Addon-for-Blender>
  - Releases 下载 zip，`Edit > Preferences > Add-ons > Install`，勾选启用。
  - 需要导入 VRM 和导入/导出 VRMA（`VRMC_vrm_animation`）。

## 推荐工作流

### A. 只微调现有动作

1. `File > Import > VRM`，导入角色的 `model.vrm`。
2. 导入现有 `.vrma`（VRM Add-on 的 VRM Animation Import）。
3. 在 Dope Sheet / Graph Editor / NLA 里改关键帧和曲线。
4. `File > Export > VRM Animation (.vrma)` 导出，文件名保持对应 trigger。

### B. Mixamo FBX 重定向到角色 VRM

1. 导入目标角色的 `model.vrm`，这是唯一骨骼基准，不要在别的骨架上改完再对位。
2. 导入 Mixamo FBX（只保留其 Armature 和动作，模型网格可删）。
3. 用重定向工具把 Mixamo 骨映射到 VRM Humanoid 骨：
   - 免费首选：Rokoko Blender addon，自动重定向。
   - 商用可选：Auto-Rig Pro，自带 Mixamo preset。
   - 小量手动：给 VRM 骨加 `Copy Transforms` 约束指向 Mixamo 对应骨，再 Bake。
4. Bake 到 VRM Armature 上：`Pose > Animation > Bake Action`，只 Bake Humanoid 骨。
5. 清理：
   - 只保留 Hips 的 Translation，其余骨全部只有 Rotation。
   - 删除 helper 骨、非 VRM Humanoid 骨，保证导出的 humanoid 骨数与 `check_vrma.mjs` 一致。
   - 一镜动作：首尾帧位姿对齐；循环动作：首尾帧完全一致，运行时循环交给系统，不在 Blender 里复制多圈。
6. 导出 `.vrma`。

## 落地到 DeskMate

1. 文件名必须是 11 个 trigger 之一，例如 `speaking.vrma`：

   `idle`, `listening`, `thinking`, `speaking`, `executing`,
   `awaiting_approval`, `success`, `error`, `click`, `project`, `hover`

2. 放入对应 persona 的资产目录：

   `data/persona-assets/<persona_id>/vrma/<trigger>.vrma`

3. 校验：

   ```bash
   node scripts/vrm/check_vrma.mjs data/persona-assets/vrm_demo/vrma/*.vrma
   ```

4. 在 `#/motion-lab` 选择该 persona，切 trigger 预览，调循环 trigger 与交叉淡化，保存。

## 适配要点

- 永远以 `model.vrm` 为骨骼事实源；VRMA 的骨骼名必须和 VRM 1.0 标准名一致。
- VRMA 只导出 Humanoid 骨旋转、Hips 位移、Expression 预览值和 Look At 目标。
- 循环交给引擎（`loop_triggers`），不要在 VRMA 里做多圈循环，避免文件膨胀和首尾卡顿。
- 先跑 `check_vrma.mjs` 确认结构，再进动作实验室看实机效果；穿模/脚滑问题回 Blender 调根位移和脚部接触。

## 当前缺口

`listening` / `error` / `click` / `hover` 目前是复用凑合动作。建议用上面的 B 工作流替换为语义精确的 Mixamo 源，导出后直接覆盖同名 `.vrma`。
