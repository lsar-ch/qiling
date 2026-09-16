# DeskMate 项目协作规则

## 唯一工作目录

本项目的唯一工作目录是：

```text
/Users/lxb/Documents/desktop assistant project
```

不要使用带前导反斜杠或反斜杠分隔符的变体，例如 `\/Users/...` 或 `\Users\...`。

## 启动必读

每次进入本项目时，先读取全局 Obsidian 记忆，再读取本项目文档。

Obsidian 记忆库：

```text
/Users/lxb/Library/Mobile Documents/iCloud~md~obsidian/Documents/knowledge/knowledge
```

优先通过 Obsidian MCP 工具读取：

1. `AI-Memory/INDEX.md`
2. `AI-Memory/user.md`
3. `AI-Memory/maintenance.md`
4. `AGENTS.md`
5. `AI-Memory/installed-skills.md`，仅在涉及 Skill、MCP、插件时读取

如果当前会话没有暴露 `mcp__obsidian__read_note`、`mcp__obsidian__search` 或 `mcp__obsidian__list_notes`，说明 Obsidian MCP 未连接到本次会话。此时先明确告知用户，并可临时用本地文件只读方式查看上述记忆文件；不要假装 MCP 已经可用。

## 当前项目状态

本项目是 DeskMate 桌面 AI 助理。

- 新架构主线：`apps/`、`services/`、`packages/`、`docs/`
- 早期原型：`src/`，仅作参考，不作为新架构主运行入口
- 已完成：Step 1-3、Step 4 语音闭环、Step 4.5 设置与角色配置、Step 5 本地项目记忆/Obsidian 三档模式、Step 6 任务分流主链路；Step 7 执行器目录与 Codex ACP 真实执行已完成，包括 6 个默认执行器的配置驱动目录（`config/agents.yaml`）、`AgentRunManager`、Codex ACP/stdio 真实提交/取消/授权、`/api/agent-runs` 与前端真实运行控件；Step 8 自动化回归与 Codex 真实 `read-only` 任务已通过（`task_eff6a657ae`）
- 当前阶段：**V1 已收口（2026-09-15）；P1 浏览器窄场景执行已完成；P1 轻量主动性与 P2 发布加固主体已完成（各余 1~2 项部分完成）**。macOS 人工验收、角色化表现、Windows 真机回归（WI-05 复验 T1 3/3 + 18 项回归 18/18）均已完成；第二轮 WI-06/07/08/09/10 已在 macOS 复验通过，详见 `docs/WINDOWS-MIGRATION-2026-09.md`。vite 升级挂 P2
- 质量基线：`./scripts/check.sh` → **204 passed** + web/desktop typecheck 全绿；改 Rust 另跑 `cargo check`；改 `apps/web` 必须 `npm run build`（主界面加载 `apps/web/dist` 构建产物）
- 顺序：主线功能已落地，剩余 V2 收尾 6 项；按 `docs/HANDOVER-2026-09-17.md` 第 4 节推进，动手前先清掉第 2 节真机验收

继续工作前优先阅读：

1. `docs/HANDOVER-2026-09-17.md`（**最新交接：昨夜改动、真机待验收清单、进度盘点、推进顺序、环境坑位**）
2. `docs/PROJECT-ROADMAP.md` 与 `docs/P1-P2-TASK-CARDS.md`
3. `docs/HANDOVER-2026-09-13.md`（V1 收口过程）
4. `docs/V1-IMPLEMENTATION-PLAN.md`
5. `docs/WINDOWS-MIGRATION-2026-09.md`（Windows 迁移主题唯一入口）
6. 与当前任务相关的专题文档，例如 `docs/STEP9-UI-POLISH.md`、`docs/STEP8-RELEASE-DEGRADATION.md`、`docs/VOICE-ACTIVATION.md`、`docs/TASK-ROUTING.md`、`docs/MAIN-INTERFACE.md`

## 工具路由

执行任务前先做轻量判断：

- 代码开发：先读本地代码和文档，优先用 `rg` / `rg --files`
- 网页或外部资料：先判断是否需要实时联网、登录态或浏览器操作
- 本地网页调试：优先使用 Browser 插件或本地开发服务
- Chrome 登录态相关：只有需要用户现有登录态时才使用 Chrome 插件
- 桌面应用操作：需要真实桌面交互时再使用 Computer Use
- 文档、表格、图片、视频：按对应 Skill 或本地工具处理

能并行的只读检查可以并行；有副作用的动作前先确认输入、路径和权限。

## 开发约束

- 默认中文沟通，先给结论，再给必要细节
- 不重构无关代码，不删除用户或其他工具留下的改动
- 手工编辑文件使用 `apply_patch`
- 修改后用最低成本的权威信号验证，例如 `./scripts/check.sh`、类型检查、接口健康检查或页面状态
- API key、音频样本、运行数据和缓存不入库

## 常用命令

```bash
./scripts/setup.sh
./scripts/dev.sh service
./scripts/check.sh
```

端口约定：

- ai-service: `8736`
- web dev: `5173`
- desktop dev: `1420`

## 完成通知

任务完成后调用：

```bash
/Users/lxb/.codex/bin/codex-notify done "..."
```

需要用户扫码、登录、验证码或确认时调用：

```bash
/Users/lxb/.codex/bin/codex-notify need "..."
```

## 开发工作流规范

### 任务开始前

- 单文件、小范围且目标明确的改动，直接实施，不写冗长计划。
- 多文件、跨模块、架构调整或预计超过 30 分钟的任务，先说明：
  - 目标与非目标
  - 当前假设和未决问题
  - 涉及模块与文件
  - 验收标准
  - 实施顺序、风险和验证命令
- 需求存在关键歧义时先询问，不根据猜测扩大范围。
- 修改前读取目标文件、相关测试、调用方和一个相近的现有实现。

### 实施规则

- 优先复用现有代码、依赖、脚本和项目约定。
- 采用能完成任务的最小改动，不新增未经要求的抽象、依赖、配置或兼容层。
- 多文件功能按可运行的纵向切片逐步实施，每个切片都保持项目可构建、可验证。
- Bug 先复现并定位根因，再修复；不要只在表面调用方打补丁。
- 涉及框架或第三方 API 时，先按项目实际版本查阅官方文档。
- 保留用户和其他工具已有的修改，不覆盖、不回滚无关变更。
- 手工编辑继续使用 `apply_patch`。

### 必须先询问

- 修改 `/Users/lxb/.codex/config.toml` 或其他全局 Codex 配置。
- 安装、升级或移除依赖、插件、MCP、Skill 或 hooks。
- 修改数据库结构、CI、发布流程、认证逻辑或外部服务配置。
- 删除文件、批量覆盖、提交、推送、发布或发送外部消息。

### 质量与验证

- 逻辑改动优先补一个能证明行为的最小测试或回归检查。
- 每个实施增量后运行最小有效验证；任务完成前运行项目相关的完整检查。
- 至少检查：需求是否满足、测试/构建结果、错误路径、输入边界和明显安全风险。
- 不得通过删除测试、禁用检查、增加忽略规则或吞掉错误来制造“通过”。
- 完成前对本次改动做一次独立代码审查，优先检查正确性、安全性、回归风险和不必要复杂度。

### 最终汇报

只报告：

1. 修改了什么；
2. 实际运行了哪些验证及结果；
3. 尚存风险、未完成事项或需要用户决定的内容。
