# 共享动作库（VRM 3D 线）

> 授权声明：本目录的 15 个 `.vrma` 动作由 Mixamo 参考片逐帧重定向并修正后生成，
> 不是 Mixamo 原始文件；完整来源声明见根目录 `NOTICE`。

所有同套角色共用一份，不落各自 `persona-assets/<id>/vrma/`。角色在角色卡里声明用哪套：

```yaml
presentation:
  vrm:
    library: female
```

## 约定

- 目录名即 `vrm.library` 的取值，后端只放行 `male` / `female`（白名单在
  `services/ai-service/app/api/settings.py:_MOTION_VARIANTS`）。
- 文件名必须是 11 个 trigger 之一：`idle, listening, thinking, speaking, executing,
  awaiting_approval, success, error, click, project, hover`。同状态多动作**不靠改文件名**，
  而是在角色卡 `vrm.actions` 里列多个候选（可带 `weight` / `cooldownMs`）。
- 除 11 个基名外，另有按语义加后缀的候选片段，只有被角色卡引用时才加载：

| 片段 | 用在哪 | 来源 |
| --- | --- | --- |
| `idle_alt` / `idle_happy` | `idle` 候选，低权重 + 高冷却 | Mixamo 参考片派生 |
| `speaking_alt` | `speaking` 候选 | Mixamo 参考片派生 |
| `project_alt` | `project` 候选 | Mixamo 参考片派生 |
| `error` | `click` 候选 | Mixamo 参考片派生 |
| `hover` / `idle` | `listening` 候选（低权重 + 40s 冷却） | Mixamo 参考片派生 |

  加新候选就是「丢一个 vrma + 在角色卡 `vrm.actions` 里加一行」，前后端都不用改。
- 预览：动作实验室（`http://localhost:5173/#/motion-lab`）右侧预览区选库 + 选片段即可。
  下拉直接读目录列表（`GET /api/motion-library/{variant}`），新导出的 vrma 丢进库目录就出现，
  不必先写进任何角色卡。
- 朝向/骨骼：VRMA 只含 humanoid 骨旋转 + Hips 位移，按 VRM 1.0 标准骨名导出，
  运行时由 `createVRMAnimationClip` 重定向到具体模型。
- **动物线（2026-10-29 起走 VRM）**：猫的动作同样落在本目录，新增 `cat` 变体
  （角色卡写 `vrm.library: cat`，白名单在 `settings.py:_MOTION_VARIANTS` 放行）。
  - 猫绑 **VRM humanoid 骨**（前腿→手臂、后腿→腿），11 个 trigger 文件名与人物线一致。
  - **尾巴 / 耳朵 / 眼皮不在 VRMA 的承载范围内**（`VRMC_vrm_animation` 只定义 humanoid
    骨旋转、hips 位移、表情、lookAt）。这几处表现由 springBone + 运行时程序化交付，
    **不要试图烘进 clip**，烘了也会在导出时被丢弃。
  - **真四足骨架的猫模型不能进本目录**：过不了 52 骨校验，也播不了 VRMA。
  - 来源只允许自制 / CC0 / 完全所有权输出；Mixamo 与 Fab、Unity 商店动物包禁止（再分发红线）。
- 2026-10-30 之前本文写作"动物线走 2D 动作表、没有 VRMA"，该说法已随 VRM 路线作废。

## 校验

```bash
node scripts/vrm/check_vrma.mjs data/motion-library/*/*.vrma
```

片段必须是同一份 52 骨规范集（VRM 1.0 全集去掉 `leftEye` / `rightEye` / `jaw`），
名单在 `scripts/vrm/humanoid-bones.json`。少了或多了一根都判 FAIL。

**同时强制 in-place**：`hips` 的水平净位移必须 ≤ 20mm，超出判 FAIL。桌面桌宠的移动由
桌面坐标系驱动，片段自带水平位移会造成"双倍位移"；竖直起伏（呼吸、步态 bob）不拦。
阈值可调、可显式豁免：

```bash
node scripts/vrm/check_vrma.mjs --verbose data/motion-library/female/hover.vrma
node scripts/vrm/check_vrma.mjs --hips-tol=0.05 <file.vrma>      # 放宽到 50mm
node scripts/vrm/check_vrma.mjs --allow-root-motion <file.vrma>  # 确认用于非移动场景
```

脚本还会拦 VRMA 规范违规通道：humanoid 骨上的 `scale`、非 `hips` 骨上的 `translation`。

用 Blender 改过动作参数再导出的片段，导出后先归一化再入库：

```bash
python3 scripts/vrm/normalize_vrma.py --source <导出前的原片段> <导出文件>
```

原因见 `docs/VRM-ASSET-NOTES.md` §9：导出的骨骼集是按**模型**的人骨映射重建的，
模型缺的骨会静默丢、模型多挂的眼骨会静默多出来。
