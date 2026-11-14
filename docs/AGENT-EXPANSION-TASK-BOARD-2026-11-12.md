# Agent / Skill / MCP 扩容任务板

> 更新日期：2026-11-13
> 当前阶段：T17 AgentRun 结构化结果呈现已完成
> 下一步：选择一个明确授权的项目做真实 Agent 执行/授权人工验收
> 关联方案：`栖灵Desktop/01-方向与决策/GitHub热门项目接入计划-2026-11-12.md`
> 关联决策：`栖灵Desktop/01-方向与决策/T-03 执行层策略与竞争力.md`

## 0. 范围与目标

目标：让栖灵成为统一的 Agent 控制面，协调轻量任务、MCP 能力、Skill 工作流和外部 ACP Agent。

执行模式：

- `inline`：栖灵现有 LLM 直接完成搜索整理、总结、翻译、改写和文案。
- `mcp`：栖灵 LLM 调用已授权的 MCP 工具完成搜索、记忆、网页读取和受控操作。
- `acp`：Codex、Claude Code、Gemini CLI、OpenCode 等外部 Agent 负责代码、终端、多文件和长任务。

优先级：`inline → mcp → acp`。没有外部 Agent 时，轻量任务仍必须可用。

## 1. 任务清单

| ID | 任务 | 状态 | 责任范围 | 验收标准 |
|---|---|---|---|---|
| T0 | 重审接入计划并确定三种执行模式 | ✅ 完成 | 规划文档、T-03 对齐 | 接入计划明确 `inline / mcp / acp`、Agent/Skill/MCP 分工和后续顺序 |
| T1 | 定义 `ExecutionProfile` 与扩展元数据 | ✅ 完成 | `packages/contracts/*/extension.*`、`SkillRegistry`、契约/扩展测试 | 已支持 `mode`、`agent_id`、`skill_ids`、`mcp_profile`、`permission`、`workspace`；Skill 已支持 `execution.modes`、`requires`、来源、版本、许可证和兼容 Agent；未知模式会拒绝 |
| T2 | 打通无外部 Agent 的 inline 轻量任务 | ✅ 完成 | `services/ai-service/app/routing/classifier.py`、`services/ai-service/tests/test_task_routing.py` | 纯文案/改写/润色/翻译走现有 LLM inline；“搜索并整理摘要”继续走内置浏览器只读执行器；文案任务不启动 Agent；`./scripts/check.sh` 全绿 |
| T3 | 打通栖灵托管 MCP 的只读任务 | ✅ 完成 | `services/ai-service/app/mcp/manager.py`、`services/ai-service/app/api/chat.py`、`config/mcp-servers.yaml`、MCP 回归测试 | 支持 MCP profile 服务器白名单；显式 profile 只暴露并调用 `access: read` 服务器；未知 profile 拒绝；URL/搜索类任务不启动 ACP；无 profile 保留写工具审批链路；`./scripts/check.sh` 全绿 |
| T4 | 将 Skill 绑定到统一任务 | ✅ 完成 | `packages/contracts/*/task.*`、`services/ai-service/app/skills/registry.py`、`services/ai-service/app/api/{chat,tasks}.py`、相关测试 | 任务可指定 Skill；inline 和 mcp 模式都能加载 Skill 指引；自动选择会跳过不兼容模式；Skill 不扩大权限；定向回归通过，全量回归最后统一执行 |
| T5 | 完成单 Agent ACP 纵向闭环 | ✅ 完成 | AgentRunManager、ACP adapter、AgentRun | ACP 任务会注入已校验 Skill 指引；记录 `agent_id`、`skill_id`、`mcp_profile`、`execution_mode` 与权限 `mode`；结果回写对话；定向回归与真实只读 Codex 探针通过 |
| T6 | 将 MCP profile 传入 ACP 会话 | ✅ 完成 | `McpManager.acp_servers`、AgentRunManager、Codex/acp-cli/WorkBuddy adapter | profile 仅映射已启用且 `access=read` 的服务器到 ACP `session/new.mcpServers`；无 profile 保持空列表；写服务器不会暴露；定向回归通过 |
| T7 | 建立 Agent / Skill / MCP 统一目录入口 | ✅ 完成 | `ExtensionsPage`、扩展目录 API | 扩展页新增 Agent 执行器目录；Skill 显示兼容模式/许可证/版本/依赖/来源；MCP 显示来源/传输/权限；Agent 显示状态/能力/部署命令/来源；Web build 与 API 回归通过 |
| T8 | 接入第二个 ACP Agent | ✅ 完成 | `config/agents.yaml`、通用 `acp-cli`、`services/ai-service/tests/test_acp_cli.py` | Claude Code 已通过通用 `acp-cli` 目录接入；新增 ACP 生命周期/MCP 传递可控回归，11 passed；本机未安装或认证 Claude，未宣称真实外部闭环 |
| T9 | 建立社区扩展部署清单 | ✅ 完成 | `docs/COMMUNITY-TOOLS-DEPLOY-2026-11-12.md`、`apps/web/src/ExtensionsPage.tsx` | 清单覆盖 Agent/Skill/MCP 的来源、部署、凭证、许可证和安全边界；扩展页 Agent tab 提供入口 |
| T10 | 统一运行记录与可恢复状态 | ✅ 完成 | `AgentRun`、事件、对话、记忆 | 运行记录持久化 Agent/Skill/MCP/权限/工作目录/会话/结果；服务重启会收口孤儿任务；已有查询、取消、授权和 ACP session 续接链路 |
| T11 | 多 Agent 工作流编排 | ✅ 完成 | `services/ai-service/app/api/workflows.py`、任务/运行记录 | 新增二步串行工作流 API：实现完成后才启动审查，结果注入下一步；每步复用现有 Task/AgentRun、权限与 MCP 校验，不支持并行/自动重试 |
| T12 | 无真实环境下的工作流产品化验证 | ✅ 完成 | `apps/web/src/ExtensionsPage.tsx`、`apps/web/src/api.ts`、ACP 离线 fixture | Agent 目录提供“实现→审查”入口；无就绪 Agent 时不允许启动；离线 fixture 通过真实 stdio ACP 生命周期，12 passed |
| T13 | 项目中心工作台首版 | ✅ 完成 | `apps/web/src/ProjectNodesPage.tsx`、工作台契约/API | 导航改为“工作台”，保留 `project` 路由；概览整合项目进度、待办、便签和已配置入口；便签/待办按项目路径归属，旧全局记录不自动并入项目；Web build 与后端回归通过 |
| T14 | 工作台 CRUD 补齐 | ✅ 完成 | `apps/web/src/ProjectNodesPage.tsx`、Workbench API 调用 | 便签可编辑；快捷链接可新增/编辑/隐藏/显示/删除；编辑入口保留既有可见状态与排序；切换项目期间旧 mutation 不覆盖当前项目状态；Web build 与定向 API 回归通过 |
| T15 | 工作台项目任务创建 | ✅ 完成 | `apps/web/src/ProjectNodesPage.tsx`、`apps/web/src/api.ts`、`services/ai-service/app/api/tasks.py` | 项目任务页可输入描述并调用现有分流 API；显式项目路径写入 Task.project 并进入当前项目任务列表；旧调用兼容；任务分流测试与 Web build 通过；不自动越权启动 Agent |
| T16 | 工作台 AgentRun 状态与控制 | ✅ 完成 | `apps/web/src/ProjectNodesPage.tsx`、现有 AgentRun API | 显示运行状态/进度/结果/错误；只读为默认模式；执行器未就绪时不提供启动；复用已有运行、取消、批准、拒绝接口；轮询绑定项目快照，防止跨项目状态写入；Web build 与独立审查通过 |
| T17 | AgentRun 结构化结果呈现 | ✅ 完成 | `apps/web/src/ProjectNodesPage.tsx` | 项目任务卡显示产物、检查、阻塞与下一步；运行产物汇入项目文件列表并去重；结构化字段/批准/只读拒绝服务端定向回归 3 passed；Web build 与独立审查通过；真实执行留待明确项目人工验收 |

## 2. 当前状态与下一步

T5-T12 的 Agent / Skill / MCP / ACP 主链路及离线工作流验证已完成。2026-11-13 又通过真实 Codex ACP 隔离探针：只读任务返回预期文本且工作目录无文件；第二个会话成功取消且工作目录无文件。Claude Code 与 Qwen Code 命令已检测到但尚未握手/认证，WorkBuddy 当前 ACP 启动失败，均不计为真实闭环。

工作流重启恢复已补齐：服务启动时读取持久化工作流，与 AgentRun 状态对账；未完成工作流收口为失败/取消，不自动重放步骤；`awaiting_approval` 遗留运行记录和对应 Task 也会失败收口，避免工作流已失败但孤儿运行仍可批准。全部步骤已完成时修正工作流终态。

v0.2 后端首切片已定义共享 `WorkbenchItem` / `WorkbenchSettings` 契约，并接入本地 `settings.local.json` 的设置读写与 `/api/workbench/items` CRUD；支持快捷链接、iframe、内置功能三类条目，以及分组、显隐和排序。校验条目 ID 唯一、类型目标字段匹配、URL 限制 HTTP(S)，损坏设置不会被条目 API 覆盖。

便签与待办使用独立于定时提醒的契约和 JSON 文件存储：`WorkbenchNote` / `WorkbenchTodo`，分别位于 `data/workbench/notes/`、`data/workbench/todos/`；支持 `/api/workbench/notes` 与 `/api/workbench/todos` CRUD。便签正文上限 10000 字，待办描述上限 1000 字、状态为 `pending/completed`；单类最多 500 条，超限拒绝新建且不自动淘汰已有数据。T13 已将其接入项目中心工作台；新增 `project_path` 可选字段来区分项目数据，历史记录保持未关联状态。

T13 工作台首版：原主页未改；导航“项目”改称“工作台”（英文 Workbench），URL/page key 继续使用 `project` 以兼容已有书签。项目概览保留节点进度与运行指标，增加项目待办新增/完成/删除、便签新增/查看/删除，并展示工作台入口。便签和待办按项目目录精确筛选，历史无项目字段的数据不会误归入当前项目。

T14 工作台核心 CRUD：便签增加编辑；快捷链接可在工作台新增/编辑/显隐/删除，沿用服务端 HTTP(S) 校验和已有 CRUD。入口编辑仅提交内容字段，不覆盖原显隐与排序。异步 mutation 回调仅在项目仍为当前选择时刷新；切换项目时清空旧编辑草稿，避免跨项目重归属。

T15 项目任务创建：`RouteRequest` 接受可选 `project`；工作台创建任务时显式传当前项目，后端将其写入 `Task.project`，任务随即通过既有列表接口归入该项目。原有按 conversation 推断项目的调用不变；本步只创建/分流，不启动执行器。

T16 AgentRun 控制：项目任务列表查询并显示运行阶段、进度、执行器、结果和错误；允许使用 ready 执行器运行，模式默认 `read-only`，仅对 `delegate_backend/request_approval` 展示运行入口；运行中可取消，待授权可批准/拒绝；自动轮询只在 active run 存在时启动，并对项目快照做前后校验。未就绪执行器显示提示，登录仍引导到“我的智能体”完成。

T17 结构化结果：任务卡按需展示 AgentRun 的产物、检查、阻塞、下一步四个字段；空数组不占位；产物路径同步汇入项目文件列表并通过 Set 去重。服务端定向回归覆盖结构化结果持久化、批准后完成、read-only 自动拒绝；未对真实项目启动 Agent，因为那会对用户选择的工作目录产生外部写入。

验证：真实 Codex ACP 隔离只读与取消探针通过；工作台/契约定向测试 26 passed；`./scripts/check.sh`：442 Python passed、Web/Desktop 类型检查通过、Desktop 62 passed；`apps/web` `npm run build` 成功（chunk size 提示）；独立代码审查放行，`git diff --check` 通过。

残余风险：便签/待办 JSON 使用直接写入，进程在写入中崩溃可能产生截断文件；启动时损坏记录会被跳过。本地同类存储目前也采用该模式，后续需要统一升级时再改为原子写入并增加损坏记录诊断。

后续顺序：由用户指定并授权一个可写测试项目后，人工验收真实 Agent 执行/审批闭环。iframe 与内置功能条目暂保留现有配置 API，管理 UI 仅覆盖快捷链接。录制 API 目前仍是 stub，暂不纳入近期主线；远程认证只在产品范围扩到局域网/云端时启动。

```text
ExecutionProfile
├── mode: inline | mcp | acp
├── agent_id: string | null
├── skill_ids: string[]
├── mcp_profile: string | null
├── permission: read-only | confirm | full
└── workspace: string | null
```

Skill 元数据至少需要支持：

```yaml
execution:
  modes: [inline, mcp, acp]
requires: [web-search]
supported_agents: [codex, claude-code]
license: MIT
source_url: https://github.com/...
version: "..."
```

T2 的首个回归任务固定为“搜索并整理摘要”和“根据材料生成文案”。

## 3. 依赖顺序

```text
T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11
```

允许并行：

- T7 的目录接口可以在 T4 完成后开始，但不要早于兼容元数据确定。
- T9 可以在 T7 之后穿插进行。

禁止提前做：

- T1 完成前不要扩展多个 Agent 配置。
- T2/T3 完成前不要把“无外部 Agent”判定为不可用。
- T5/T6 完成前不要宣传 Skill 已支持 ACP 执行。
- T10 完成前不要开始多 Agent 协作。

## 4. 每项完成时的回写规则

完成一项后同步更新：

1. 本文件对应行的状态、实际修改文件和验证结果；
2. 必要时更新接入计划中的实施顺序；
3. 新踩坑或新决策追加到根目录 `决策日志.md`；
4. 下一步只保留一个明确的首要任务，避免新对话重新判断入口。

## 5. 验证基线

- Python / 服务端改动：`./scripts/check.sh`
- `apps/web` 改动：`npm run build`
- Desktop 改动：Desktop typecheck/build
- Rust 改动：`cargo check`
- ACP 或 MCP 改动：至少一条真实或可控的端到端回归记录

当前不做：安装任意远程 ZIP、自动执行 Skill 内脚本、一次性接入所有 Agent、在单 Agent 链路未稳定前实现多 Agent 编排。
