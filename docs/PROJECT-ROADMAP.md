# DeskMate 项目路线图

## 当前定位

DeskMate 当前收敛为：

> 角色化、本地优先、懂项目记忆的 AI 工作伙伴。

产品优先级：

1. 语音和挂件带来的自然交互
2. 项目记忆带来的持续上下文
3. 外部 Agent 集成带来的真实工作价值
4. 授权、状态和结果反馈带来的可控性

不把通用 Computer Use 作为核心竞争方向。

## 当前进度

**截至 2026-09-17：V1 已收口。P1 浏览器执行器已完成；P1 轻量主动性 T1-T4 已完成；P2 发布加固 T1-T6 已完成，V2 六项收尾也已完成。主线与收尾全部落地。本轮验证：`./scripts/check.sh` 全绿 —— pytest **211 passed**、`apps/web` 与 `apps/desktop` typecheck 均 RC=0、`cargo check` 通过、`apps/web/dist` 已重建（`assets/index-CE1ebdZE.js`，vite 6）。**

**2026-09-17 傍晚追加**：真机 9 项复验全部通过；修掉 `window.prompt` 在 Tauri 窗口静默失效（连带两处无提示删除）、新增角色卡删除、vite 升 6.4.3 清掉 dev-server 漏洞、修掉 Intel Mac 干净安装必挂的 `cryptography` wheel 缺失。细节与剩余待办见 `docs/HANDOVER-2026-09-17.md` 第 7 节。

**2026-09-17 凌晨两项修复（`60c23c4` / `5a661b4`，自动化与真机均已通过）**：① WorkBuddy 授权链路 —— 模式映射改真值（`read-only→plan` 才是真只读，旧值 `dontAsk` 只是不弹窗、不隔离）、授权选项按 `kind` 匹配 `optionId`（修掉「允许一次」静默升级成永久放行）、授权卡片显示真实命令、5 分钟超时自动按拒绝收口；② 主界面隐藏时把语音租约交给挂件 —— 关闭走 `hide()` 不销毁，页面继续心跳持租约，导致挂件语音永远是「关」；现在只在真隐藏/真显示时广播 `main-ui-visibility`（最小化、失焦、遮挡不触发），挂件自动接管「听」。验收清单见 `docs/HANDOVER-2026-09-17.md` 第 2 节。**

已完成：

- Tauri 桌面运行时、FastAPI 本地服务、React 主界面和 contracts
- 桌面挂件、状态事件、浏览器主界面
- 文字对话、SSE 流式回复、会话保存
- DashScope STT、MiniMax TTS、声音克隆链路
- 常开 VAD、静默/唤醒词、基础播报停止
- 回声抑制和长回复摘要自动播报
- 设置页、角色卡与本地 settings/personas API（Step 4.5）
- 本地 L1/L2/L3 项目记忆、FTS 检索、记忆页 CRUD、Obsidian 只读三档模式（Step 5）
- 任务分流四类结果、任务 JSON 持久化、任务 API、聊天自动分流、本地任务台（Step 6）
- 统一 Agent Adapter/Registry 契约、基于 `config/agents.yaml` 的执行器目录与配置接口（6 个默认）；Codex 与 WorkBuddy ACP 真实接入，其余执行器保留扩展位
- Codex ACP/stdio 真实执行：AgentRun 持久化、任务提交、进度回流、取消/授权、`/api/agent-runs` 与主界面真实运行控件（Step 7 Phase 2）
- Step 8 发布回归：`/api/health` 能力汇总、LLM/语音/Codex 降级自动化覆盖、前端“执行器不可用”提示、运行时隐私目录忽略；Codex ACP 真实任务已成功验收（真机启动/麦克风/Windows 人工验收已于 2026-09-15 V1 收口完成）

## 近期路线

### Step 4：语音闭环（已完成，2026-09-07）

- 真机验收麦克风 → VAD → STT → LLM → TTS
- 校准唤醒灵敏度、静音判定和播报打断
- 完成主声与克隆声的配置验证

### Step 4.5：设置和角色基础配置（已完成，2026-09-07）

- API key 录入入口
- 角色名称和唤醒词
- 音色、语速、语气标签
- 监听、静默和权限配置

### Step 5：最小项目记忆（已完成，2026-09-07）

- 会话和任务事件
- 项目进度与技术决策
- Obsidian 只读检索
- 记忆查看、编辑、删除

记忆从这里提前进入主线，不再作为最后才实现的附加模块。

### Step 6：任务分流（已完成，2026-09-07）

- `answer`
- `execute_frontend`
- `delegate_backend`
- `request_approval`

先实现项目相关的窄场景，不实现通用桌面自动化。

### Step 7：执行器目录与 Codex ACP 真实执行（已完成，2026-09-07）

已完成：

- 通用 Agent Adapter 接口
- Agent Registry 注册与探测
- 执行器目录与配置接口：`config/agents.yaml` 默认注册 6 个执行器，配置驱动可扩展
- Codex 本地探测
- Claude Code / Qwen Code / Kimi CLI / Reasonix 保留 pending 适配器（真实协议接入前不执行任务）
- Codex ACP/stdio 真实连接与任务提交、AgentRun 持久化、进度/结果回流与记忆归档
- WorkBuddy ACP/stdio 真实连接、桌面端登录态探测、只读任务提交、取消与子进程回收
- `/api/agents` 探测 API、`/api/agent-runs` 运行/取消/授权 API
- 前端“我的智能体”执行器状态展示与真实运行/取消/批准控件

验收记录：Codex 本机 provider/model 已调整为当前 relay 支持的 `deepseek-v4-flash`，并通过 DeskMate API 完成一次 `read-only` 真实任务（`task_eff6a657ae` / `run_c560a3ca9c`）。WorkBuddy `2.137.1` 于 2026-09-13 完成真实只读任务、取消、错误路径和进程回收复验（`task_b0a1e73e07` / `run_76f49ee353`）。其他执行器仍按目录接入对应 adapter。

### Step 8：V1 回归与发布

状态：已完成。自动化、Codex 真实任务与 macOS/Windows 人工验收均已于 2026-09-15 V1 收口完成。验收范围见 `docs/STEP8-RELEASE-DEGRADATION.md`。

**借鉴 here（2026-09-10）**：打包脚本参考 here 的 `build_bundle.py`——smoke test、按需安装（--with-*）、模型外置、CI 双平台。

已完成的自动化/工程收尾：

- 健康接口返回 text/voice/memory 与执行器可用性汇总，不暴露密钥；本轮 `/api/health` 新增 `diagnostics`（llm/voice/memory/agents 四项，中文 detail + `fix_hint`/`fix_action`，`services/ai-service/app/api/health.py:103`），主页据此渲染能力诊断卡与「去修复」跳转（`apps/web/src/App.tsx:1569`）
- LLM 调用失败、语音供应商禁用/异常、Codex 未安装或不可执行均有明确降级与回归测试
- 前端任务台对不可用执行器显示可见提示，任务仍可保留在本地任务台
- `.gitignore` 覆盖会话、任务、Agent Run、日志、音频、本地记忆等运行时数据

已完成：

- Codex 真实成功任务：2026-09-07 通过 DeskMate `read-only` ACP 运行完成并返回有效结论
- 人工验收：macOS 启动器和退出进程回收、麦克风授权与无麦克风/拒绝授权降级、Windows 启动与权限回归，已于 2026-09-15 V1 收口完成（见 `docs/WINDOWS-MIGRATION-2026-09.md`）

### Step 9：V1 视觉与体验打磨

状态：页面视觉、八页导航、390px/1440px 响应式审计已完成；待随最终角色接入再做一次回归。范围见 `docs/STEP9-UI-POLISH.md`。

这一步处理“整个页面美化”，但不引入 V2 的重资产表现：

- 浏览器主界面：Home / Chat / Memory / Knowledge Base / My Agents / Settings
- 桌面挂件与主界面的状态视觉一致性
- 设计变量、排版、卡片层级、响应式与可读性
- 角色形象与工作台的配合，不把页面做成营销式落地页
- 视觉改动后的自动化回归，以及最后把 Step 8 人工验收再做一轮

已完成（桌面挂件交互层）：

- 透明紧凑挂件窗口 `280x304`：无边框、置顶、右下角定位、可拖动
- 角色舞台入口交互：单击激活、双击打开主界面、`Space` 打开输入条
- 短回复气泡仅展示当前挂件轮次回复，不在监听/静默态展示旁路回复内容
- 语音识别无效音频在监听/静默态静默丢弃，不再反复提示失败
- 激活光圈只在输入态出现，拖动后不残留圆圈；输入条支持 `Esc` / 点击角色 / 失焦收起

剩余收口：无（2026-09-13 完成挂件角色化表现收口，详见 `docs/STEP9-UI-POLISH.md`）。

- ✅ 挂件角色化表现：情绪动效可分辨、角色切换、气泡与点击打断均已人工验收
- ✅ 顺带修掉「情绪从未进入 WS 广播」的根因（`EventHub` 序列化早于 `on_publish` 钩子）
- 保留：频率参数留在 CSS，不对用户暴露；`presentation.animations` 预留不接线

V1 不做 Live2D / 3D 或复杂情绪动画；那些仍在后续方向。

### Step 9.5：统一表现事件流与角色级表现（已完成，2026-09-11）

状态：表现事件 schema、后端桥接、前端消费和基础情绪动效已完成。角色资产接入单列为 V1 收口工作。范围见 `docs/EXPRESSION-EVENT-SCHEMA.md`。

这一步是连接「后端状态」↔「挂件渲染」的桥梁，以及角色级表现的配置驱动化。

#### 背景

- 已将业务状态、情绪、气泡和主题色纳入统一表现事件链路
- 已完成角色卡 presentation 配置、后端情绪解析和挂件消费
- 当前剩余问题是资产来源仍以默认/示范形象为主，尚未完成用户自主导入闭环

#### 排期

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | `docs/EXPRESSION-EVENT-SCHEMA.md` — 两层载荷 schema（ExpressionEvent + PersonaPresentation）、情绪推导规则、WS 协议扩展 | ✅ 完成 |
| P1 | 后端 contracts 扩展（widget.py / events.py 新增字段） | ✅ 完成 |
| P1 | PersonaPayload 六段式 profile（identity/personality/speech/relationship/preferences/boundaries）+ build_system_prompt()（借鉴 here） | ✅ 完成（2026-09-11） |
| P1 | 后端 state_mapper 增强（emotion_for() + ExpressionEvent 输出） | ✅ 完成 |
| P1 | 独立 emotion_resolver 模块——情绪名归一化+映射表（借鉴 here） | ✅ 完成（2026-09-11） |
| P1 | 后端 presentation_bridge（角色切换时广播 PersonaPresentation） | ✅ 完成 |
| P2 | 前端 WsMessage 扩展 + Widget 消费 emotion/bubble/theme | ✅ 完成 |
| P2 | widget.css `.emotion-*` 视觉变体（改为立绘级动效：浮动/摇摆/弹跳/抖动；光环已按用户要求移除） | ✅ 完成（2026-09-11） |
| V1 收口 | 单张基础形象上传/预览，按角色隔离保存到运行时目录 | ✅ 完成（2026-09-11） |
| V1 收口 | 上传格式/尺寸校验、运行时 `asset-manifest.json`、挂件读取真实角色形象 | ✅ 完成（2026-09-11） |
| V1 收口 | 去背景/边缘清理/固定画布等图像规范化增强 | ✅ 完成（2026-09-13） |
| V1 收口 | 人物/动物程序化动作预设、悬停/拖动轻互动与挂件真实角色接入 | ✅ 完成（2026-09-11，待真机验收） |
| V1.5 | 完整状态帧导入/生成，不拆组件 | 后续 |
| V2/V3 | 半自动分层、参数化 SVG/Canvas、`layers.json`、骨骼/网格 | 后续备选 |
| ~~P3~~ | ~~提示词模板定稿（文生图拆层）~~ | 已放弃（用户实测不可用，见方向文档 §2） |

#### 资产管线（用户侧）

采用渐进式方案，完整规划见 `docs/CHARACTER-INTERACTION-ROADMAP.md`：

1. V1：用户只需提供或生成一张高清基础形象
2. DeskMate 自动去背景、清理边缘、裁切、对齐、缩放
3. V1 通过完整图和程序化动态表达角色状态
4. V1.5 才提供可选的完整状态帧生成，不要求用户制作组件
5. V2 再评估半自动部件识别与分层
6. V3 再评估骨骼、网格或 Live2D 类渲染

Codex 精灵表只能作为可选导入/导出格式，DeskMate 不依赖 Codex 或 WorkBuddy 才能运行。

## 后续方向

V1 验证成功后再考虑：

- 浏览器窄场景自动化：优先 Browser Use/CDP，先做打开 URL、搜索、读取、提取和翻页
- 更强的桌面感知
- 实时全双工语音
- 多 Agent 调度
- 更丰富的角色表现
- Live2D / 3D
- 多平台消息投递（WeChat/Telegram 等，参考 here 的 MessagingRegistry 架构）

角色资产与互动的完整渐进式边界见 `docs/CHARACTER-INTERACTION-ROADMAP.md`；资产生成路线见 `docs/CHARACTER-ASSET-GENERATION.md`。

## 执行记录（2026-09-13）

1. ✅ 完成只读基线检查。
2. ✅ 完成 macOS 侧 P0 平台缺口与人工验收；Windows 安装、权限和退出回收仍需真机执行。
3. ✅ 平台修改均先确认方案后实施。
4. ✅ 每项修改完成了当前 macOS 环境可执行的验证。
5. ✅ 合并 WorkBuddy 执行器，并完成 macOS 真实只读任务、取消和错误路径复验。
6. ✅ 浏览器执行器 P1 完成（2026-09-16）：搜索/打开/翻页/读页面/附件上传端到端验证通过。
7. ⏸ 通用 CUA 暂不进入。
7. 后续：WorkBuddy 适配器允许注入 `mcpServers`，并把「日常/工作/项目」映射为 prompt 能力说明。
8. 后续：先评估 Qwen Code CLI 的 ACP 接入，再决定是否新增 qwen 执行器；不接千问桌面端内部协议。

## N.E.K.O. 对比后的推进计划（2026-09-12）

### P0：完成 V1 收口 ✅ 已完成（2026-09-15）

- ✅ 角色基础形象规范化和挂件真机验收（2026-09-13）
- ✅ macOS 启动器、麦克风权限、退出回收人工验收（麦克风两项按日常使用确认，不再单列）
- ✅ Windows 真机回归：WI-01~05 / WP-01~03 已全部修复并验证；WI-05 真机复验（T1 3/3）
  与 18 项回归（18/18）2026-09-14 回传全绿，第二轮 WI-06/07/08/09/10 于 2026-09-15
  在 macOS 复验通过，见 `docs/WINDOWS-MIGRATION-2026-09.md`
- 保持当前产品边界：角色化、本地优先、项目记忆、可控 Agent 执行

### P1：V1.1 浏览器窄场景执行 ✅ 完成（2026-09-16）

目标是先获得稳定的网页工作能力，不直接建设通用 Computer Use。

实施顺序：

1. 在现有 `AgentAdapter` / `AgentRegistry` 上增加浏览器执行器，不在前端增加浏览器特例。
2. 先实现打开 URL、搜索、读取页面、提取结果、翻页和滚动。滚动因无状态适配器限制交 WorkBuddy agent 处理。
3. 执行器优先采用页面级 DOM/CDP。
4. 复用 `AgentRun`、进度事件、取消、授权和结果归档。
5. 登录、验证码、提交、发送、删除和支付统一暂停并请求用户确认。
6. 先用一个代表性任务做端到端验收（真实搜索/打开/读页面已通过，表单填写不实施）。

验收信号：

- 浏览器会话能创建、复用、失效重建和关闭
- 每一步都有可展示的进度/失败原因
- 用户取消后浏览器和任务状态都能正确收口
- 任务结果可进入 Chat、挂件反馈和项目记忆

### P1：轻量主动性与语音优化（任务卡已落定）

> 详见 `docs/P1-P2-TASK-CARDS.md`

| 编号 | 任务 | 来源 | 状态 |
|------|------|------|------|
| P1-T1 | TTS 增量分块播报（首响 <1s） | VC-Bundle 建议3 + P1 短播报需求 | ✅ 已完成：Web 端已走分块播放（`app/speech/base.py:66` / `app/api/voice.py:319` / `apps/web/src/api.ts:934` / `ChatPage.tsx:317`）；挂件同样走分块（`apps/desktop/src/components/Widget.tsx:381`、`:434`，保留 barge-in），首块耗时看 dev 日志 `[widget-tts] first chunk ms`（`Widget.tsx:386`），无自动化断言 |
| P1-T2 | 任务完成/失败主动短播报 | 原 P1 范围 | ✅ 已完成（`app/agents/runtime.py:467` 发 bubble + speak_text，`ChatPage.tsx:469` 自动播报）；挂件侧 2s 合并队列已补（`Widget.tsx:349` `playTts` + `flushAnnouncements`） |
| P1-T3 | 记忆更新气泡提示（低频 5min） | 原 P1 范围 | ✅ 已完成（2026-09-16 修复）：原 `ChatPage.tsx` 把 `memory.updated` 挡在 `TASK_EVENT_TYPES` 白名单外是死代码，现已把 `env.source !== "task"` 与事件类型过滤拆开（`ChatPage.tsx:428`、`:429`、`:443`），后端 `app/agents/runtime.py:544` 的事件可被消费；5min 限频 + 5s 自动清除保留；新增回归测试 `tests/test_agent_runtime.py::test_completed_task_publishes_memory_updated_event` |
| P1-T4 | 工作模式自适应记忆深度 | 原 P1 范围 | ✅ 已完成（`app/api/chat.py:77` mode 字段、`:337` casual 压到 800 字/空 surfaces、work 全量，测试 `tests/test_chat.py:231`）；本轮补上手动切换分段控件（`ChatPage.tsx:63`、`:1179`）；`ChatMode` 已进 py/ts contracts（`packages/contracts/py/deskmate_contracts/conversation.py:12`），桌面端可传 `auto/casual/work` |

执行顺序：P1-T1 → P1-T2（依赖分块），P1-T3/T4 可并行。

### P2：发布加固（任务卡已落定）

> 详见 `docs/P1-P2-TASK-CARDS.md`

| 编号 | 任务 | 来源 | 状态 |
|------|------|------|------|
| P2-T1 | 一键安装脚本（smoke test + 按需安装） | 原 P2 + here 打包借鉴 | ✅ 已完成（`scripts/setup.sh`：工具链检测 / .venv 复用 / `npm ci` / `--with-voice` / `--with-browser` / smoke test / 修复入口 / Windows 指向迁移文档；本轮修掉 `fetch_health` 超时 2s→8s（`:83`）与语音 key 检测漏读项目根 `.env`（`:224`））；遗留未在干净 macOS 上跑完整 `setup.sh`（会清 node_modules 并重建 dist，需单独授权） |
| P2-T2 | 首次启动配置引导 | 原 P2 范围 | ✅ 已完成（`app/api/settings.py:288` `GET /api/setup/status`、`apps/web/src/App.tsx:1756` SetupWizard、测试 `tests/test_settings_api.py:255`）；范围偏差：只有 2 步（LLM 必填 → 语音可选可跳过），无「角色选择」步；完成标记写入 `data/settings.local.json`（`app/config.py:163`）而非 `config/settings.yaml`，刻意让密钥不进仓库配置 |
| P2-T3 | 能力汇总与故障诊断 Dashboard | 原 P2 范围 | ✅ 已完成（`app/api/health.py:103` `_diagnostics` 带中文 detail + `fix_hint`/`fix_action`、`App.tsx:1569` 卡片与「去修复」跳转、测试 `tests/test_health.py:46`）；偏差：诊断项合并为 4 类（llm/voice/memory/agents）而非任务卡列的 6 项，且仅在有诊断项时渲染 |
| P2-T4 | Persona 预设模板（work/companion/service） | VC-Bundle 建议1 | ✅ 已完成（2026-09-16 修复）：原 `app/core/persona_prompt.py` 只在 profile 完全为空时才用预设，而 `config/personas/default.yaml:35` 有完整 profile → `preset: work` 是死字段；现改为「预设作底座 + profile 非空字段覆盖」（`persona_prompt.py:105`），并补 3 个测试（`tests/test_persona_prompt.py:88`、`:99`、`:106`），实测默认角色提示词零变化；预设切换已接 API/UI（`apps/web/src/api.ts:187` `preset`、`apps/web/src/CharacterPage.tsx:564` 四态选择） |
| P2-T5 | 音色/形象后台任务状态机 | VC-Bundle 建议4 | ✅ 已完成（最小可用）：`scripts/persona_asset_import.py` 状态机 + 合法流转表（`:32`）+ JSON 落盘 `data/persona-tasks/` + CLI；`/api/persona-tasks`（`services/ai-service/app/api/persona_tasks.py:16`）按 `AgentRun` 形状读写，角色页显示最近任务进度。偏差：音色克隆的实际后台执行仍走 `probe_minimax.py`/CLI，未自动触发 |
| P2-T6 | AvatarDriver 字段预留（procedural_2d） | VC-Bundle 建议2 | ✅ 已完成：`AvatarDriver` 已进 py/ts contracts（`packages/contracts/py/deskmate_contracts/character.py:11`、`packages/contracts/ts/src/character.ts:4`），默认 `procedural_2d`、预留 `video_stream`；暂无消费方（V1 零依赖预留，符合预期） |

执行顺序：P2-T1 → P2-T2，P2-T3/T4 并行，P2-T5/T6 并行。

### V2 待办（累计 6 项，均为收尾；推进顺序见 `docs/HANDOVER-2026-09-17.md` 第 4 节）

1. ✅ 挂件接 TTS 分块链路：`Widget.tsx` 已用 `synthesizeSpeechStream` 逐块播放，并保留 barge-in。
2. ✅ 挂件播报合并队列：2s 窗口内多条任务播报合并为一句。
3. ✅ `ChatMode` 已进 py/ts contracts，`chat.py` 与桌面端 `streamChat` 可传 `auto/casual/work`。
4. ✅ persona 预设切换：`PersonaPayload.preset` + 角色页四态选择（自定义/工作/陪伴/服务）。
5. ✅ P2-T5 接 AgentRun：新增 `/api/persona-tasks`，以 `AgentRun` 形状暴露资产任务，角色页显示进度。
6. ✅ `AvatarDriver` 已补进 py/ts contracts，默认 `procedural_2d`，预留 `video_stream`。

### P3：仅在真实需求出现后评估通用 CUA

只有当浏览器、无障碍接口和系统快捷键无法覆盖真实任务时，才评估截图 + VLM + `pyautogui`。届时必须先单独验证：

- macOS 辅助功能和屏幕录制权限
- Windows DPI、坐标和多显示器
- 截图隐私、敏感窗口屏蔽和请求预算
- 单步执行、取消、超时、失败回退和高风险授权

## 暂不做的事

- 不自研通用 Computer Use
- 不提前建设插件市场
- 不提前建设云端任务平台
- 不并行铺开多个外部 Agent

## 待评估想法（未排期，2026-09-09 记录）

### 系统自检 / 修复窗口（分级路由）

背景：外部进程误改/损坏项目文件可能导致应用拉不起或功能缺失，应预留「检测 + 安全修复」能力。
用户确认的分情况设计：

- 重故障（挂件/桌面都拉不起来、环境损坏）→ 以「启动器窗口」为入口：启动失败时已会自动弹出，升级为检测清单 + 分类结果 + 修复按钮。
- 轻问题（功能级降级：语音 STT/TTS 不可用、记忆库路径失效、服务偶发不健康）→ 在浏览器主界面（主页）提供检测与修复入口。

建议细节（待深入探讨后再定阶段）：

- 后端提供统一健康报告接口（检测项 + 严重级别 + 可执行修复动作），两个入口共用同一份数据与动作。
- 修复分级：只自动执行幂等且无害的动作（重启服务、重跑 setup 式安装）；删改文件类必须人工确认。
- 触发方式：异常自动弹出（按严重级别路由到对应入口）+ 用户主动「检测」入口并存。

候选安排：V1 收口（Step 9 视觉/Step 8 人工验收）后，随发布加固或 Step 10 维护能力再做，不提前排期。

## Voice-Companion-Bundle 调研（2026-09-16）

> 项目：[github.com/JunWan666/voice-companion-bundle](https://github.com/JunWan666/voice-companion-bundle)
> 定位：Windows + WSL2 本地数字人语音交互整合包（Faster-Whisper → LLM → Qwen3-TTS → LiveTalking/Wav2Lip）

5 条建议已合并入 P1/P2 任务卡：

| 建议 | 内容 | 落点 |
|------|------|------|
| 1 | persona 预设模板（work/companion/service） | P2-T4 |
| 2 | AvatarDriver 字段预留（procedural_2d/video_stream） | P2-T6 |
| 3 | TTS 增量分块 + 打断队列 | P1-T1 |
| 4 | 音色/形象后台任务状态机 | P2-T5 |
| 5 | 不改变 V1 定位（轻量桌面伙伴 ≠ 赛博女友） | 已有共识 |

不做的：Wav2Lip/LiveTalking（Windows CUDA 依赖重，放 V2 可选驱动）。
