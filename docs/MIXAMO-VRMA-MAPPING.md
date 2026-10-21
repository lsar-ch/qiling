# Mixamo FBX → VRMA 动作映射（2026-09-26）

## 1. 转换结果

用 `fbx2vrma-converter`（github.com/tk256ailab/fbx2vrma-converter，MIT）
批量转换了 `~/Downloads/mixamo-fbx/` 下 13 个 Mixamo FBX，输出到
`~/Downloads/mixamo-vrma/`，全部成功。

每个 VRMA 含 `VRMC_vrm_animation` 扩展、52 个 humanoid 骨骼
（20 根核心人骨 + 30 根手指骨），骨骼 key 为 VRM 1.0 标准名，
与 `@pixiv/three-vrm-animation` 的 `createVRMAnimationClip` 兼容。

## 2. 映射表

Desktop 的 11 个 trigger 已在 `apps/desktop/src/widget/actions.ts` 定义。
当前 qiling 使用 `data/motion-library/female/` 的 **15 条**片段，角色卡里用
`presentation.vrm.library` 选库；未显式列出的 trigger 按同名文件回退；
同状态多动作在 `presentation.vrm.actions` 里列候选（`weight` / `cooldownMs`），不再靠文件名区分。
下表基名相同，只是从“每个 persona 一份”挪到了共享库。

| trigger | Mixamo 源动作 | 类型 | 说明 |
| --- | --- | --- | --- |
| `idle` | Standing W_Briefcase Idle | 精确 | 站立待机 |
| `thinking` | Thinking | 精确 | 思考 |
| `speaking` | Talking | 精确 | 说话 |
| `executing` | Walk In Circle | 精确 | 走动干活 |
| `awaiting_approval` | Teeter | 精确 | 摇晃犹豫 |
| `success` | Clapping | 精确 | 鼓掌庆祝 |
| `project` | Silly Dancing | 精确 | 跳舞 |
| `error` | Teeter（复用） | 凑合 | 摇晃表出错 |
| `click` | Blow A Kiss | 凑合 | 飞吻作点击反馈 |
| `listening` | Thinking（复用） | 凑合 | 倾听凑思考 |
| `hover` | Idle Transition | 凑合 | 悬停凑过渡 |

## 3. 已使用候选池

| 片段 | 所属 trigger | 现状 |
| --- | --- | --- |
| `idle_alt` / `idle_happy` | `idle` | 已配置为低权重、高冷却候选 |
| `speaking_alt` | `speaking` | 已配置为低权重、20s 冷却候选 |
| `project_alt` | `project` | 已配置为低权重、60s 冷却候选 |
| `error` | `click` | 已配置为 `click` 的低权重、8s 冷却候选 |
| `hover` / `idle` | `listening` | 已配置为 `listening` 的低权重、40s 冷却候选 |

## 4. 缺口

`listening` / `error` / `click` / `hover` 四个 trigger 没有语义精确的
Mixamo 动作，当前用复用/凑合动作填充，效果需实测。建议后续从 Mixamo
补：Listening、Disappointed/Shrugging、Pointing、Look Around。

## 5. 回滚

旧占位 VRMA 备份在 `data/persona-assets/vrm_demo/vrma/.backup-2026-09-26/`。

## 6. 验证

结构校验（humanBones 为 52 个 VRM 标准名）：

```bash
node scripts/vrm/check_vrma.mjs data/motion-library/*/*.vrma
```

运行态验证需 `cargo tauri dev` 切到 vrm_demo persona，观察 11 个 trigger
动作是否按预期播放、是否穿模/错位。
