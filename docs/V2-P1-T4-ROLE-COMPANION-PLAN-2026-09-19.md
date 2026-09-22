# V2 P1-T4 角色陪伴入口增强 设计与实施计划（2026-09-19）

> 状态：实施完成（2026-09-19）
> 本文件归档 2026-09-19 讨论结论，是 T4 唯一设计入口。任务定义仍见 `docs/V2-P1-TASK-CARDS.md`。

## 1. 背景与结论

用户关注点：角色动态太单调会失去吸引力。讨论结论：

1. 项目处于 V2 P1，但角色路线图的 V1→V2→V3 是另一套分级，不能因“项目是 V2”就直接上 Live2D/骨骼。
2. 不做完整 C 档（Live2D/骨骼/3D），改做 **C 档分层 2D 动作子集**：分层立绘 + 程序化动画 + 状态帧 + 通用特效层。
3. 先前的 `idle_action_interval_ms` 契约字段未真正接线，是“角色没有生命感”的具体缺口。

采纳的外部项目借鉴：

| 来源 | 借鉴点 |
|---|---|
| QQ 宠物 / DyberPet 类桌宠 | 用户动作→互动事件→角色反馈闭环；空闲低频随机小动作 |
| Open-LLM-VTuber / Warashi / my-neuro | 状态语义与视觉动作分离；语音/任务状态驱动表现 |
| Project N.E.K.O. | 角色参与工作流、有上下文地主动反馈 |
| HanaAgent | 角色卡身份/记忆独立，动作族可随角色复用 |
| Voice-Companion-Bundle | work / companion / service 场景差异 |

不采纳：好感度/饱食度养成、金币/道具、LLM 自由控制动画、强制用户制作分层部件。

## 2. 设计决策

- D1 `motion_family` 三类：`human`（人物）、`animal`（动物）、`anime`（二次元），决定动作库。
- D2 `art_style` 独立字段（`realistic / anime / chibi / pixel`），决定画风，不参与动作选择。
- D3 业务状态机保持不变；状态→候选动作列表→权重/冷却/随机，由前端动作选择器控制。
- D4 通用特效层是所有角色共享资产（魔法阵、星光、速度线、思考气泡、问号、音符）。
- D5 渲染先走 `2d_animated`，契约保留 `lip_sync / live2d / 3d` 为迁移口。
- D6 不引入新依赖，不新增运行时端口，不改变事件通道。
- D7 空闲必须有动作，但是低频、短促、随机间隔、忙碌时暂停。

## 3. 角色分类与动作库

```yaml
persona:
  motion_family: animal   # human | animal | anime
  art_style: anime        # realistic | anime | chibi | pixel，先做可选项
```

| 触发/状态 | human | animal | anime |
|---|---|---|---|
| 空闲 | 呼吸、眨眼、张望、站立 | 呼吸、摇尾巴、竖耳、趴下 | 漂浮、眨眼、星光环绕 |
| 聆听 | 前倾、点头 | 竖耳、歪头 | 睁大眼、前倾 |
| 思考 | 托腮、抬眼 | 歪头、耳朵抖动 | 手指点下巴、省略号 |
| 说话 | 嘴型帧、手势 | 嘴型帧、爪前摆 | 嘴型帧、语气符号 |
| 执行 | 坐下/站立切换、双手忙碌 | 原地小跑、碎步 | 转身、魔法阵 |
| 成功 | 起身、挥手、微笑 | 跳跃、打滚、快速摇尾 | 闪光、跳跃、变身闪 |
| 失败 | 垂肩、摇头 | 垂耳、蜷缩 | 眩晕、汗滴 |
| 单击 | 挥手、点头 | 跳一下、翻身 | 转身面向、魔法火花 |
| 悬停 | 身体倾向鼠标 | 耳朵/头部跟随 | 扭头、视线跟随 |

## 4. 资产与契约影响

### 契约层

- `packages/contracts/py/deskmate_contracts/widget.py`：`PersonaStyle` 扩展 `"anime"`（语义可理解为动作族）；`PersonaPresentation` 增加 `motion_family` 与可选 `art_style`；保留旧 `style` 做兼容映射。
- `packages/contracts/ts/src/widget.ts`：同步镜像。
- `packages/contracts/ts/src/character.ts`：`CharacterConfig` 增加 `motion_family`、`art_style` 可选字段（与 `style` 渲染方式区分）。
- 老角色兼容：配置缺省按 `human` 处理，现有挂件无需强制升级。

### 后端

- `config/personas/*.yaml`：新增可选 `motion_family`、`art_style`。
- `services/ai-service/app/core/presentation_bridge.py`：下发 `motion_family`。
- `services/ai-service/app/api/settings.py` 角色卡接口：读写新字段。
- 不新增事件类型；`ExpressionEvent` 保持现有字段。

### 前端挂件

- `apps/desktop/src/api.ts`：类型镜像。
- `apps/desktop/src/components/Widget.tsx`：
  - 动作选择器（候选动作、权重、冷却、随机）
  - 空闲调度器（消费 `idle_action_interval_ms`，随机抖动，忙碌暂停）
  - 分层渲染（body / eyes / mouth / fx，未分层时回退单图）
  - 互动事件（hover / click / double-click / drag）
  - 项目切换表现（动作 + 3s 摘要气泡）
  - InteractionKind 节奏差异（work / casual / project）
- `apps/desktop/src/components/widget.css`：扩展 `data-persona-style="anime"`、动作 keyframes、特效层样式。

### 动作引擎（新增前端模块）

建议新增 `apps/desktop/src/widget/actions.ts`，只包含纯函数：

```ts
type MotionFamily = "human" | "animal" | "anime";
type ActionId = string;

interface ActionSpec {
  class: string;            // 对应 CSS keyframes
  duration_ms: number;
  loop?: boolean;
  cooldown_ms: number;
  weight: number;
}

function pickAction(
  family: MotionFamily,
  state: WidgetState,
  recent: string[],
): ActionId | null;
```

- 状态映射和动作库配置化，不写死在 Widget 组件内。
- 动画选择是纯函数，可单测。

### 资产

- 先做一套通用特效 PNG：`sparkle`、`magic_circle`、`speed_lines`、`thought`、`question`、`note`。
- 每角色可选的 `asset-manifest.json / layers.json`：`body / eyes / mouth / accessory / fx` 图层与锚点。
- 无分层资产时，用单张 `main.png` + 通用特效层，保证旧角色可动。

### InteractionKind 来源

- 优先级：最近一次任务/对话的 `interaction_kind`；未知时默认 `casual`。
- 后端在合适载荷中带上 `interaction_kind`，或挂件通过现有状态接口轮询；实现时选定一种，不做双通道。

## 5. 实施步骤

### 阶段 A：契约与配置（预计 1 个切片）

1. `widget.py` / `widget.ts` 扩展 `PersonaStyle` 与 `PersonaPresentation`，`character.py` / `character.ts` 增加可选字段。
2. `config/personas/*.yaml` 增加 `motion_family`、`art_style`。
3. `presentation_bridge.py`、角色卡接口读写新字段。
4. 补 contracts 同步测试与 presentation 测试。

验证：`./scripts/check.sh` 中 contracts 同步与后端测试通过；角色卡接口能保存/回读 `motion_family`。

### 阶段 B：通用动作库与特效资产（1 个切片）

1. 新增 `actions.ts`：三类动作库、状态映射、权重/冷却、`pickAction`。
2. 新增通用特效资源并接入 layers 渲染（先回退单图）。
3. CSS keyframes 覆盖三类动作。

验证：`pickAction` 单测通过；挂件在 `human/animal/anime` 下分别能播放空闲与成功动作。

### 阶段 C：挂件动作引擎与互动（1 个切片）

1. Widget 接入空闲调度器，消费 `idle_action_interval_ms`。
2. 接入 hover / click / drag / double-click 反馈。
3. 动作进行中阻止重复触发；非 idle 状态暂停空闲动作。
4. 单测覆盖冷却与随机去重。

验证：桌面挂件实测：空闲随机动作、单击/悬停响应、双击打开主界面；动画在任务状态结束后恢复 idle。

### 阶段 D：项目上下文与 InteractionKind（1 个切片）

1. 挂件显示当前项目 + 最近任务状态。
2. 项目切换触发动作 + 3s 摘要气泡。
3. InteractionKind 调整动作节奏与气泡风格。

验证：切换项目后 3 秒内出现摘要；work/casual/project 三种模式下动作频率与气泡风格可区分。

### 阶段 E：收敛验收

1. `apps/desktop` 重新构建 widget dist。
2. 全量 `./scripts/check.sh`。
3. 手动验收 T4 三范围：项目显示、模式差异、切换摘要。
4. 更新任务卡与进度文档为“已完成”。

## 6. 影响分析

- 依赖：零新增运行时依赖。
- 平台：纯 Web/Tauri 前端，不碰 macOS/Windows 原生层；但需重建 desktop dist。
- 兼容：旧角色无分层资产时仍可用；旧配置默认 `human`；老挂件忽略新字段。
- 数据：persona YAML 全为可选字段，无迁移脚本。
- 性能：动作播放集中在 CSS 合成动画，复杂度可控；需避免多个循环特效叠加。
- 风险：特效/动作过多会变成干扰，默认参数保守（低权重、长冷却），用 presentation 参数可调。
- 不做：不在本任务内做 Live2D/骨骼、专属逐帧动画批量生产、口型同步、角色资产训练。

## 7. 参考

- `docs/CHARACTER-INTERACTION-ROADMAP.md`
- `docs/CHARACTER-STAGE-DESIGN-2026-09-10.md`
- `docs/EXTERNAL-INSIGHTS.md`
- `docs/HANAAGENT-ANALYSIS.md`
- `packages/contracts/py/deskmate_contracts/widget.py`
- `packages/contracts/py/deskmate_contracts/character.py`
