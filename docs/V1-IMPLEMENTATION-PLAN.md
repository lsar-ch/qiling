# DeskMate V1 实现结构与顺序

## 1. 目录策略

当前已有的 Python 代码保留为原型参考，不立即删除或大规模搬迁。

正式实现建议逐步收敛到以下结构：

```text
desktop-assistant-project/
├── apps/
│   ├── desktop/                 # 桌面运行时：挂件、托盘、权限、启动服务
│   └── web/                     # 浏览器主界面：中文 UI、对话、任务、记忆、设置
├── services/
│   └── ai-service/              # 本地 AI 服务
│       ├── conversation/        # 对话编排
│       ├── speech/              # STT、TTS、VAD、打断
│       ├── routing/             # 任务分类与 Agent Router
│       ├── memory/              # L1/L2/L3 记忆
│       ├── agents/              # Codex 等 Adapter
│       ├── tools/               # 浏览器、桌面、知识库工具
│       └── api/                 # HTTP、WebSocket、事件接口
├── packages/
│   ├── contracts/               # 前后端共享数据结构和事件类型
│   ├── persona/                 # 角色配置和语气规范
│   └── config/                  # 配置 schema 与默认配置
├── assets/
│   └── characters/              # 2D 角色原始稿、分层资源、状态资源
├── data/                        # 本地数据库、缓存、音频、日志
├── scripts/                     # 启动、检查、打包脚本
├── docs/                        # 产品和技术文档
├── .env.example
├── README.md
└── package / Python 配置文件
```

## 2. 模块职责

### `apps/desktop`

- 启动本地 AI 服务
- 管理桌面挂件
- 管理系统托盘和全局快捷键
- 打开默认浏览器主界面
- 处理系统权限
- 接收事件并更新挂件状态

### `apps/web`

- 默认中文界面
- 对话和语音控制
- 任务进度与结果
- 记忆管理
- Codex 状态
- 设置和权限确认

### `services/ai-service`

- 接收文字和语音输入
- 调用 LLM / STT / TTS
- 执行任务分流
- 管理记忆
- 管理工具和外部 Agent
- 向挂件和浏览器推送事件

### `packages/contracts`

集中定义：

- `Conversation`
- `Task`
- `TaskStatus`
- `WidgetState`
- `ApprovalRequest`
- `Memory`
- `AgentEvent`
- `VoiceSettings`

这个目录是防止前后端消息格式漂移的关键。

## 3. V1 实现顺序

### Step 1：接口与开发基线

- 确定运行时组合
- 创建前后端最小工程
- 固定共享数据结构
- 固定本地服务启动方式
- 固定事件格式

验收：

- 桌面运行时能启动本地服务
- 浏览器能打开主界面
- 前后端能完成健康检查

### Step 1 基线决策（2026-09-04 已冻结）

开工前定稿，避免返工：

| 项 | 决策 |
|---|---|
| 运行时组合 | Tauri 2（桌面运行时壳）+ React/TS 浏览器主界面（`apps/web`）+ Python FastAPI 本地 AI 服务（`services/ai-service`） |
| 主界面打开方式 | 生产模式由 ai-service 托管 `apps/web` 静态资源；桌面运行时用系统默认浏览器打开 `http://127.0.0.1:<port>/` |
| 端口规范 | ai-service `8736` / web dev `5173` / desktop dev `1420`，默认只绑定 `127.0.0.1` |
| 契约策略 | `packages/contracts/py`（pydantic）为单一事实源；`packages/contracts/ts` 为镜像类型；一致性测试兜底，暂不引入代码生成工具链 |
| 事件格式 | `EventEnvelope` v0.1：event_id / event_type / timestamp / conversation_id / task_id / source / payload；广播经 WS `/api/events` |
| 本地服务启动 | `.venv/bin/python -m uvicorn app.main:app`（工作目录 `services/ai-service`）；桌面运行时拉起并在退出时终止；无桌面环境用 `scripts/dev.sh` |
| 原型处置 | `src/`（PyQt6 + chromadb/向量记忆）仅保留参考：`voice/`、`config/` 思路迁移，`ui/`、`memory/` 不沿用（与 Markdown 档案 + FTS 方案冲突） |
| 界面语言 | 中文默认；中英切换入口按 `MAIN-INTERFACE.md` 在后续步骤加入 |

Step 1 完成标准：

- 桌面运行时能拉起 ai-service 并轮询健康状态
- `/api/health`、`/api/session` 可用
- 桌面「在浏览器打开」能打开主界面（ai-service 托管 `apps/web` 静态页）
- contracts 一致性测试通过

> 状态（2026-09-04）：**Step 1 已完成并验收通过** —— 桌面运行时自动拉起 ai-service、健康检查 200、主界面由 ai-service 托管、契约一致性测试通过、退出桌面应用时服务随之停止。

### Step 2：挂件与浏览器主界面


- 2D 角色占位图
- 空闲、聆听、思考、说话、执行、授权、完成状态
- 双击打开浏览器
- 中文页面基础布局

验收：

- 挂件可以常驻、拖拽、切换状态
- 浏览器页面能收到状态事件

> 状态（2026-09-04）：**Step 2 已完成并验收通过** —— ai-service 事件发布/状态派生/WS 回放；主界面 6 页面基础布局 + 状态演练；桌面挂件窗口（透明置顶、SVG 状态角色、拖拽条、双击开浏览器）；退出与进程清理兜底。

### Step 3：文字对话闭环

- 文字输入
- LLM Provider
- 流式文本回复
- 短回复气泡
- 长回复进入主界面

验收：

- 能完成一次完整问答
- 对话记录能保存

> 状态（2026-09-04）：**Step 3 已完成并验收通过** —— LLM Provider（OpenAI 兼容 + echo 演示）、会话 JSONL 保存、SSE 流式对话、短回复气泡 / 长回复自动展开主界面（`conversation.completed` 事件）。

### Step 4：语音闭环

- 麦克风采集
- VAD
- STT
- TTS
- 停止播报
- 基础 barge-in

验收：

- 能说话提问
- 能听到回复
- 播报过程中插话可以停止当前播报

> 状态（2026-09-07）：**Step 4 语音闭环已完成并验证** —— 方案见 `docs/VOICE-PROVIDERS.md`；
> 云供应商适配层（DashScope 已实现、火山预留）、`/api/voice/status|recognize|synthesize`、
> 前端麦克风采集（录音→WAV→识别→对话→TTS 播报→按钮打断）、常开 VAD / 静默 / 唤醒词、
> 回声抑制与长回复摘要自动播报均已接通；`./scripts/check.sh` 通过（56 项 Python 测试 + Web/Desktop typecheck）。
> 真实云端识别与合成行为仍以用户配置的 API key/账号为准。

### Step 4.5：设置与基础角色配置

- API key 录入入口
- 角色名称、唤醒词、静默词
- 音色、语速、语气标签
- 监听和权限配置

验收：

- 用户能在主界面完成主要模型、语音和角色配置
- 配置能被本地服务读取并影响语音链路

> 状态（2026-09-07）：**Step 4.5 已完成并验证** —— 主界面设置页支持模型、语音、记忆模式、权限级别与 API key 录入；
> settings/personas API 可保存配置并重建 LLM/语音 Provider，角色名称与唤醒词会进入语音链路；
> `./scripts/check.sh` 通过。

### Step 5：最小项目记忆

- 会话和任务事件
- 用户偏好、项目进度、技术决策
- Obsidian 只读检索
- 记忆查看、编辑、删除

验收：

- 用户能查看当前项目相关记忆
- 对话能引用相关项目上下文
- 用户能修改或删除记忆

> 状态（2026-09-07）：**Step 5 已完成并验证** —— `data/memory` 的 L1 trace、L2/L3 Markdown、FTS 检索、
> 会话留痕与对话上下文注入已接通；记忆页可查看、编辑、删除、搜索和导出；
> Obsidian 只读检索按 `standalone` / `obsidian_linked` / `export_import` 三档模式配置生效；
> `./scripts/check.sh` 通过。

### Step 6：任务分流

- 纯问答判断
- 前台执行判断
- 后台任务判断
- 风险等级判断

验收：

- 简单问题直接回复
- 复杂问题进入任务队列
- 高风险问题先进入授权状态

> 状态（2026-09-07）：**Step 6 任务分流主链路已完成并验证** —— 分类器返回
> `answer` / `execute_frontend` / `delegate_backend` / `request_approval`；
> 任务以 JSON 落盘，`/api/tasks` 提供路由、查询与状态推进；聊天请求自动分流并显示在本地任务台；
> `./scripts/check.sh` 通过。真实 Codex/浏览器执行器不在 Step 6 范围内。

### Step 7：执行器目录与 Codex ACP 真实执行（已完成，2026-09-07）

Step 7 已完成两个阶段。目录以 `config/agents.yaml` 为事实源，统一 Agent Adapter / Registry 接口：

- `AgentInfo` / `AgentAdapter` / `AgentRegistry` 契约
- 执行器 catalog/config 可扩展：以 `config/agents.yaml` 为目录源，默认注册 6 个执行器；非 Codex 当前为 pending/not_installed，不执行任务
- `CodexAdapter` 本地可用性探测
- `claude-code` / `workbuddy` 等非 Codex pending 适配器
- `GET /api/agents` 探测 API
- 前端“我的智能体”执行器状态展示
- `AgentRun` / `AgentRunStore` / `AgentRunManager` 真实运行链路
- CodexAdapter 通过 `codex-acp` 完成 initialize / session / prompt / cancel / close
- `/api/tasks/{id}/execute`、`/api/tasks/{id}/run`、`/api/agent-runs`、取消与授权接口
- 前端真实运行、模式选择、进度轮询、取消/批准控件

验收记录：ACP 真实任务可进入 Codex 会话并回流失败原因；测试使用 fake adapter 覆盖完成/失败/重复执行/取消/授权/pending 拒绝。Codex 本机 provider/model 调整为 `deepseek-v4-flash` 后，已通过 DeskMate API 完成一次 `read-only` 成功任务验收（2026-09-07，`task_eff6a657ae`）。

### Step 8：V1 回归与发布

状态：进行中（2026-09-07），自动化与 Codex 真实成功任务已完成。验收范围与人工清单见 `docs/STEP8-RELEASE-DEGRADATION.md`。

- macOS 启动、退出回收与权限提示（权限提示＝麦克风拒绝降级，2026-09-13 已在真机浏览器复验通过；启动/退出回收见当日 handover）
- Windows 启动测试（待 Windows 人工）
- 语音供应商禁用/异常与设备异常降级（自动覆盖禁用/供应商异常；设备权限拒绝降级 2026-09-13 已人工复验）
- Codex 未安装/不可执行降级（自动测试 + 前端不可用提示已完成）
- 数据、密钥和隐私边界检查（`.gitignore` 已覆盖运行时数据目录）
- 健康接口发布前能力汇总（已完成：text/voice/memory + executor summary）

Step 8 自动化与 Codex 真实成功任务已通过；剩余完成标准为桌面真机人工清单。

## 4. 开发阶段的协作方式

Step 1-6 主线已验证并稳定，可以引入有边界的并行收尾，例如独立调研 Codex Adapter 协议，或在接口冻结后并行处理前端/后端收尾任务；Step 7 主链路仍建议先由一个主 Agent 维护，避免 Codex 接入与路由接口漂移。

后续适合并行的情况：

- 需要并行研究多个外部 Agent 协议
- 前端和后端可以同时开发且接口已经冻结
- 需要独立代码审查、测试和跨平台验证

## 5. 云服务判断

当前不需要立刻开通云服务。

V1 建议：

- 本地运行桌面运行时
- 本地运行 AI 服务
- 本地接入 Codex
- 用户自行配置 LLM / STT / TTS

后续需要云服务的情况：

- 本地设备算力不足
- 需要运行长时间任务
- 需要统一管理多个 Agent
- 需要远程访问或多设备同步
- 需要多人使用或商业化部署

推荐最终采用混合模式：

```text
本地：挂件、语音入口、敏感数据、权限确认
云端：可选的重任务、长任务、远程 Agent
```

## 6. 当前结论

- 可引入有边界的并行收尾，主线 Step 7 Codex Adapter 仍由一个主 Agent 推进
- V1 阶段仍不购买或搭建云服务，产品内先接入本地 Codex
- 先按本地优先完成 V1 主链路
- 产品内的 Codex 接入仍然属于 V1 必做
- 云端和多 Agent 编排作为 V1 后的扩展能力


### Step 10: Dashboard 信息可视化 + 扩展性预留

> 详见 `docs/STEP10-DASHBOARD-AND-EXTENSIBILITY.md`

**目标：** Home 页加入系统仪表盘；预留 RecordingSession / CharacterConfig 契约；细化 CPU/GPU 降级逻辑。

**执行顺序：**
1. 降级逻辑细化（`performance_mode` + health 扩展）
2. 形象训练准备（CharacterConfig 契约 + Settings 占位）
3. RecordingSession 接口预留（契约 + API stub）
4. Home Dashboard 信息可视化

**验收：** `./scripts/check.sh` 全部通过；Home 页显示系统状态卡片；Settings 页支持性能模式切换。
