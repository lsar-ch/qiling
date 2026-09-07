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
- 当前阶段：Step 9 V1 视觉与体验打磨进行中；桌面挂件交互层已完成并暂停，等角色卡测试继续调优。主界面六页视觉、Step 8 macOS 人工项与 Windows 验收仍未收口
- 顺序：先按 `docs/STEP9-UI-POLISH.md` 完成主界面视觉；随后跑自动化与真机 macOS/Windows 人工验收；角色卡接入后回到挂件做角色化表现调优

继续工作前优先阅读：

1. `docs/HANDOVER-2026-09-04.md`
2. `docs/HANDOVER-2026-09-07.md`
3. `docs/PROJECT-ROADMAP.md`
4. `docs/V1-IMPLEMENTATION-PLAN.md`
5. 与当前任务相关的专题文档，例如 `docs/STEP9-UI-POLISH.md`、`docs/STEP8-RELEASE-DEGRADATION.md`、`docs/VOICE-ACTIVATION.md`、`docs/TASK-ROUTING.md`、`docs/MAIN-INTERFACE.md`

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
