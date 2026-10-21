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
- 动物线不在这里：猫狗走 2D 动作表（`motion_family: animal`），没有 VRMA。

## 校验

```bash
node scripts/vrm/check_vrma.mjs data/motion-library/*/*.vrma
```

片段必须是同一份 52 骨规范集（VRM 1.0 全集去掉 `leftEye` / `rightEye` / `jaw`），
名单在 `scripts/vrm/humanoid-bones.json`。少了或多了一根都判 FAIL。

用 Blender 改过动作参数再导出的片段，导出后先归一化再入库：

```bash
python3 scripts/vrm/normalize_vrma.py --source <导出前的原片段> <导出文件>
```

原因见 `docs/VRM-ASSET-NOTES.md` §9：导出的骨骼集是按**模型**的人骨映射重建的，
模型缺的骨会静默丢、模型多挂的眼骨会静默多出来。
