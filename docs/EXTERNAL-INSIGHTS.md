# 外部项目可借鉴改进建议

> 来源：MiniCPM-Desk-Pet（https://github.com/OpenBMB/MiniCPM-Desk-Pet）、Open-LLM-VTuber（https://github.com/Open-LLM-VTuber/Open-LLM-VTuber）
> 调研日期：2026-09-08
> 状态：待评估、待排期

## 1. 背景

两个外部桌宠/角色项目（MiniCPM-Desk-Pet、Open-LLM-VTuber）的核心卖点之一是「桌宠监督 Agent 工作」——Cursor / Claude Code 任务完成后弹气泡汇报结果、Agent 等待超时摇铃提醒。

这与 DeskMate Step 6/7 的「任务状态 → 挂件反馈」方向高度吻合，外部项目将该体验做成卖点印证方向正确，值得在 Step 9 把该体验做扎实。

## 2. 当前 DeskMate 相关现状

- Step 6 任务分流四类结果（answer / execute_frontend / delegate_backend / request_approval）已完成
- Step 7 Codex ACP 真实执行、AgentRun 持久化、进度/结果回流已完成
- 挂件已有状态事件（聆听/思考/播报/执行/授权/完成），但任务进度的「挂件主动播报」体验尚未细化打磨
- 对话模式统一（无闲聊/工作模式区分）
- 分发方式仍为开发态（`./scripts/dev.sh service`），未做一键安装包

## 3. 可落地改进建议

### 3.1 任务状态挂件主动播报（高优先级）

**问题**：任务提交到 Codex 后，挂件只在完成时弹一条结果；用户如果切换到其他窗口工作，无法感知中间进度。

**借鉴**：MiniCPM-Desk-Pet 的「任务完成气泡 + 等待超时提醒」是核心卖点。

**建议实现**：

1. AgentRun 进度回流事件（`progress` / `milestone` / `waiting_approval`）触发挂件气泡，内容压缩为一句话摘要
2. 任务等待授权超过 30 秒时，挂件播放轻提醒动画 + 短气泡「需要你的确认」
3. 任务完成时挂件播报一句话结论，长内容引导到主界面 Chat 页
4. 任务失败或超时（如 Codex 无响应）挂件主动告知，并给出「重试 / 查看日志」入口

**影响范围**：挂件事件总线、`WIDGET-STATE-MACHINE.md`、主界面任务台

### 3.2 对话模式切换：闲聊 vs 工作（中优先级）

**问题**：当前对话走同一套提示词和上下文；闲聊和复杂工作任务的推理深度需求不同。

**借鉴**：MiniCPM-Desk-Pet 用 `enable_thinking` 参数切换 No-Think（快答）和 Think（深度推理）；Open-LLM-VTuber 也有类似的双模式思路。

**建议实现**：

1. 路由层（Step 6 `delegate_backend` 判断）增加模式识别：
   - **闲聊模式**：问候、闲聊、简单问答 → 短上下文、快回复、不加载项目记忆
   - **工作模式**：涉及代码、项目、任务 → 完整上下文、项目记忆注入、允许长推理
2. 挂件状态区分两种模式：闲聊时角色姿态放松（idle/listening）；工作时角色姿态专注（thinking/executing）
3. 用户可手动切换模式，也可由路由自动判断（优先级：用户手动 > 路由判断 > 默认闲聊）

**影响范围**：`TASK-ROUTING.md`、对话编排、`config/settings.yaml`（新增 `chat_mode` 字段）

### 3.3 发布阶段一键安装引导（低优先级，Step 8/9 后）

**问题**：当前需要开发者用 `./scripts/setup.sh` + `./scripts/dev.sh service` 启动，非开发者无法使用。

**借鉴**：MiniCPM-Desk-Pet 提供 macOS dmg / Windows exe，首次启动有「环境检查 → 模型预热 → 开聊」引导流程。

**建议实现**：

1. macOS：打包为 `.app`，内置服务启动器，首次打开执行环境检查（Python、Node、依赖）并提示缺失项
2. Windows：打包为安装包（NSIS 或类似），自动配置路径和环境
3. 首次启动引导流程：
   - 检查服务端口 `8736` 是否可用
   - 检查 `config/settings.yaml` 是否已配置模型 key
   - 检查 Codex 是否已安装（可选，缺失时提示降级可用）
   - 引导完成后打开主界面
4. 退出时进程回收（与 Step 8 macOS 人工验收项对齐）

**影响范围**：Tauri 打包配置、`scripts/` 新增 `build-release.sh`、`docs/STEP8-RELEASE-DEGRADATION.md`

## 4. 不借鉴之处

- **全本地小模型路线**：与 DeskMate「云模型可插拔 + 外部执行器集成」路线相反，不采纳
- **宠物优先定位**：DeskMate 是工作伙伴，陪伴服务于工作，不转向桌宠陪伴优先
- **Live2D / 3D 深度角色系统**：PRD 第 9 条明确 V1 不做，延后到 V2

## 6. 优先级与排期建议

| 建议 | 优先级 | 可排入阶段 |
|---|---|---|
| 任务状态挂件主动播报 | 高 | **已完成（2026-09-08）**，见下方实现说明 |
| 对话模式切换 | 中 | Step 9 完成后或 V1.1 |
| 一键安装引导 | 低 | V1 发布阶段（Step 8 收尾后） |

## 7. 相关文档

- `docs/LANDSCAPE.md` — 竞品与差异总览
- `docs/HANAAGENT-ANALYSIS.md` — HanaAgent 详细调研
- `docs/STEP9-UI-POLISH.md` — 当前 V1 视觉打磨范围
- `docs/TASK-ROUTING.md` — 任务分流与路由
- `docs/WIDGET-STATE-MACHINE.md` — 挂件状态机
- `Projects/DeskMate/02-调研/MiniCPM-Desk-Pet调研.md` — 详细调研笔记（Obsidian）
- `Projects/DeskMate/02-调研/Open-LLM-VTuber调研.md` — 详细调研笔记（Obsidian）
