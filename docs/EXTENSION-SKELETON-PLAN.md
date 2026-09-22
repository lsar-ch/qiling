# DeskMate 扩展骨架实施方案（Skill + MCP）

日期：2026-09-22　状态：**已确认并实施完成（P0-P6，2026-09-22）**
关联调研：Obsidian《Super Agent Party：MCP 与插件系统借鉴》

## 1. 目标与非目标

### 目标

- 延续"工作伙伴"概念：系统可接入的技能更多，轻任务（搜索、调查、Office 处理等）本地直办，不再绕后台执行器。
- 内置两套正交能力：
  - **Skill（技能）**：回答"怎么做"——按需加载的指令包（SKILL.md + 可选脚本/资产），扩展脑。
  - **MCP（工具协议）**：回答"能做什么"——标准协议的可调用工具，扩展手。
- 主界面提供统一展示页，并为用户自行添加 Skill / MCP 留完整入口。
- 为后续"一张照片 → 3D 形象 → 骨骼 → 动作 → 可用 VRM"工作流预留同类挂载位（本期不实施）。

### 非目标（本期明确不做）

- 不做 Node sidecar 托管、iframe 前端扩展、自研插件市场、WebSocket 动态工具注册、A2A（YAGNI，出现真实需求再评估）。
- 不做 MCP server 对外暴露（P3 以后可选）。
- 不改写已调试完成的语音闭环、角色卡、记忆三档、任务分流主链路与 Codex ACP 执行。
- 不安装任何新依赖（MCP Python SDK、Office 库等）到实施阶段再单独申请批准。

## 2. 架构总览

### 2.1 分流路径升级（只增不改）

现有分流：分类器 → 本地轻量工具 / agent 执行器。
升级后（前置一条，兜底不变）：

```text
用户任务
  → 1. 命中 Skill？  加载 SKILL.md 指导模型，流程中可调用下列工具
  → 2. MCP 工具直办？ 读类自动放行；写/删/发送类走 awaiting_approval
  → 3. 本地轻量工具（现有）
  → 4. agent 执行器（Codex 等，现有兜底，行为不变）
```

- Skill 选择：模型只看各技能 `name + description`（不加载正文），命中才注入正文；不命中零成本。
- MCP 工具：懒启动（首次调用才拉起进程/建连）+ 空闲回收，**禁止所有 server 常驻保活**。
- 工具命名空间：`<server>.<tool>`；按启用范围注入，避免 prompt 膨胀。

### 2.2 负载纪律

| 项 | 空闲 | 调用时 |
|---|---|---|
| Skill | 0（纯文本懒加载） | 仅占 prompt token，无进程 |
| MCP | 0（懒启动，无配置则完全无代码路径激活） | stdio 子进程几十 MB，远轻于 Codex 执行器 |
| 骨架本身 | 薄模块 + 配置文件，对现有运行时无侵入 | — |

## 3. 首批内置 Skill

| 技能 | 说明 | 动手方式 |
|---|---|---|
| `web-research` 网络调研 | 检索 → 筛选 → 交叉验证 → 结构化汇总 | 搜索走 MCP（或现有抓取能力） |
| `obsidian-archive` Obsidian 归档 | 固化现有 URL 抓取/回灌协议，产出规范笔记 | 现有记忆接口 + 文件写入 |
| `task-breakdown` 任务拆解 | 大任务 → 任务卡 → 验收标准 | 纯指令，无副作用 |
| `weekly-report` 项目周报 | 按任务/记忆/事件整理进度周报 | 读记忆与任务数据 |
| `office-docs` Office 办公 | Word / Excel / PPT 的读取、生成、修改、格式整理 | Skill 自带脚本，调用文档处理库（见 3.1） |

### 3.1 Office 技能边界

- 能力范围：读写 `.docx` / `.xlsx` / `.pptx`，支持模板套数据、批量整理、内容提取与简报表生成。
- 实现方式：`office-docs/scripts/` 内放 Python 脚本，运行在 ai-service 所在解释器。
- 依赖：`python-docx`、`openpyxl`、`python-pptx`（ai-service 当前 requirements 未含）。**用户已于 2026-09-22 批准安装**，在 P2 开工前加入 `services/ai-service/requirements.txt` 并由 `./scripts/setup.sh` 装入现有虚拟环境；三者均为纯 Python 包，无系统级原生依赖。
- 旧文件格式（`.doc` / `.xls`）不承诺支持。

## 4. 文件与契约设计

### 4.1 目录结构（新增，全部为新文件）

```text
skills/builtin/<skill-id>/                # 随仓库分发的内置技能（不被用户覆盖）
  SKILL.md                                # frontmatter: name/description/triggers
  scripts/ assets/（按需）

data/skills/<skill-id>/                   # 用户自行添加的技能（运行时目录，可不入库）
  SKILL.md ...

config/mcp-servers.yaml                   # MCP 配置（builtin + user 条目同文件，标 source）
services/ai-service/app/skills/           # 技能注册、加载、选择（新模块）
services/ai-service/app/mcp/              # MCP 客户端：传输/生命周期/工具转换（新模块）
services/ai-service/app/api/extensions.py # 技能与 MCP 的管理 API（新路由文件）
apps/web/src/ExtensionsPage.tsx           # 主界面"技能扩展"页（新页面）
```

### 4.2 SKILL.md 规范（兼容 Anthropic/Codex skill 格式）

```yaml
---
name: web-research
description: 网络调研：检索、交叉验证并输出结构化报告（模型据此选择，不加载正文）
triggers: ["调研", "查一下", "调查"]
tools: []            # 需要的 MCP 工具或能力标签
enabled: true
---
（正文：方法论、步骤、产出模板，仅命中后注入）
```

### 4.3 MCP 配置格式（沿用 mcpServers 事实标准）

```yaml
version: 1
servers:
  - id: obsidian
    source: builtin          # builtin / user
    enabled: true
    transport: stdio         # stdio / streamablehttp
    command: npx
    args: ["-y", "mcp-obsidian"]
    env: {}
    scope: read              # read / write（write 类工具强制审批）
    idle_timeout_s: 300
  - id: my-remote
    source: user
    enabled: false
    transport: streamablehttp
    url: "http://127.0.0.1:8000/mcp"
```

### 4.4 契约（packages/contracts，Py/TS 强制同步）

新增类型：`SkillInfo`、`McpServerInfo`、`McpToolInfo`、`SkillCreateInput`。
现有契约不动；新字段一律新类型，避免回归。

### 4.5 管理 API（新路由，不碰现有路由）

- `GET    /api/skills`　列表（builtin + user，含启用状态）
- `GET    /api/skills/{id}`　详情（正文）
- `POST   /api/skills/toggle/{id}`　启用/停用
- `POST   /api/skills`　用户新增（zip 上传，或本地目录路径；校验结构与命名空间）
- `DELETE /api/skills/{id}`　仅允许删 user 条目
- `GET    /api/mcp-servers` / `POST /api/mcp-servers`（表单新增）/ `POST /api/mcp-servers/{id}/toggle` / `DELETE /api/mcp-servers/{id}`（仅 user）
- `GET    /api/mcp-servers/{id}/tools`　工具发现结果（含状态：disabled/error）

## 5. 界面展示设计

### 5.1 新增导航项

主界面左侧导航在「我的智能体」与「设置」之间新增一项：

- key: `extensions`，label: **技能扩展**
- 移动端顶栏自动同步，无需额外适配。

### 5.2 页面结构（ExtensionsPage）

顶部两个标签页：

**标签一：智能技能（Skill）**
- 卡片网格：名称、描述、来源（内置/用户）、启用开关、是否带脚本/工具。
- 点击卡片 → 抽屉展开 SKILL.md 正文（只读）。
- 右上「+ 添加技能」按钮 → 弹窗两种方式：
  - 上传技能包 zip（含 SKILL.md，结构同 4.1）；
  - 从本地目录导入（填绝对路径，校验后登记，不搬运文件）。
- 用户技能可删除；内置技能只能停用。

**标签二：MCP 服务器**
- 列表：名称、传输方式（本地命令/远程地址）、状态（未启动/可用/异常/已停用）、权限范围、工具数量。
- 「测试连接」「立即启用/停用」「查看工具清单」操作；工具清单显示每个工具名、描述、读写属性。
- 「+ 添加 MCP 服务器」按钮 → 表单：名称、stdio（命令+参数+环境变量）或 http（URL）、权限范围（读/写）。
- 配置保存即生效；首次真实调用才启动进程。

### 5.3 与其他页面的关系（不改现有页面）

- 设置页仅加一行说明文字，指向「技能扩展」页，不搬配置。
- 角色卡页本期不做"按角色绑技能"（P4 可选增强），技能默认全局生效。
- 对话页发送框下方可显示"本次已启用技能：xxx"小标签（纯展示，P3 再做）。

## 6. 安全与审批

- MCP 工具分级：`read` 自动放行；`write/delete/send` 强制走现有 `awaiting_approval` 链路，前端用已就绪的授权弹窗，不新造审批 UI。
- Skill 脚本执行：仅允许运行技能目录内脚本，参数白名单，禁止任意 shell；用户导入的技能默认 `enabled: false`，人工启用。
- zip 导入做路径穿越校验（复用 import3d 的校验模式）。
- 配置与密钥：MCP env 中的密钥不随列表接口明文返回。

## 7. 分期实施（每期独立可验证、可回退）

| 期 | 内容 | 验收 |
|---|---|---|
| P0 | 本 RFC + contracts 新类型（不接行为） | 契约同步测试通过 |
| P1 | 技能注册/加载模块 + 只读 API + 内置 5 技能落盘 + 技能扩展页只读展示 | `./scripts/check.sh` 全绿；页面可见技能 |
| P2 | Skill 选择与正文注入（接入分流前置路径）+ 启用/停用；Office 库依赖**另行申请** | 轻任务命中技能、不跑执行器；无命中时旧行为不变 |
| P3 | 用户添加/删除技能（zip 与本地目录）；对话页技能标签 | 自定义技能可用；重启后保持 |
| P4 | MCP 客户端 stdio：懒启动、tools/list、工具转 function 注入；MCP 管理 UI 与新增表单 | 首个真实 server 端到端（建议 Obsidian MCP） |
| P5 | 审批接线、streamablehttp、空闲回收、错误标记 disabled、状态展示 | 写类工具必弹授权；断线不拖垮主链路 |
| P6 | `./scripts/check.sh` + web/desktop typecheck + `npm run build` 全量回归 | 全绿，2D/语音/执行器零回归 |

## 8. 对已调试系统的保护措施

- 全部为新增模块/文件/路由/导航项；不改现有函数签名与事件结构。
- 功能开关：MCP 无配置、技能无启用时，代码路径提前返回，系统表现与现状逐字节一致。
- 每个 P 期结束都跑 `./scripts/check.sh`；改 web 必跑 `npm run build`；不新增忽略规则、不删测试。
- 实施与审查分离：编码后由独立 code-review 复查，主 Agent 最终放行。

## 9. 已确认决策（2026-09-22 10:31）

1. 导航项命名：**技能扩展**。
2. 首批 5 个内置技能：**不增不减**（网络调研、Obsidian 归档、任务拆解、项目周报、Office 办公）。
3. Office 依赖：**批准安装** python-docx / openpyxl / python-pptx，P2 前完成。
4. 技能生效范围：**全局生效，不按角色绑定**——避免角色切换导致能力受限、影响使用体验。
5. 第一批动手范围：**P0-P1**。

## 10. 逐模块影响分析

结论：除 P2「分流前插入技能选择」一处接触现有主链路外，其余全部为新增，零改动。

| 模块 | 影响 | 说明 |
|---|---|---|
| 语音闭环（voiceCapture / alwaysListen / TTS / 打断） | 无 | 语音链路不经过技能选择；新模块不在音频路径上 |
| 角色卡（persona / presentation_bridge / 切换广播） | 无 | 技能全局生效、不绑角色；presentation 事件处理不动 |
| 记忆三档（项目记忆 / Obsidian / L1-L3） | 无（只读复用） | obsidian-archive 只调用现有记忆接口与既定协议 |
| 任务分流主链路（routing/classifier） | **P2 有接触** | 分类前插入技能选择，带功能开关；无命中时逐字节走旧路径 |
| AgentRunManager / AgentRegistry / Codex ACP | 无 | 执行器兜底与提交/取消/授权链路不变 |
| 事件总线与 contracts | 仅新增 | 新增 Skill/MCP 类型，不改现有事件结构；同步测试兜底 |
| 主界面 web（apps/web） | 小改 | `App.tsx` 只动三处：PageKey 类型、NAV 数组、页面分支；新页面独立文件 |
| Tauri Rust（lib.rs / widget.rs） | 无 | stdio MCP 是 Python 侧子进程，不经 Rust；窗口配置不动 |
| 挂件窗口（Widget / VrmStage） | 无 | 挂件代码、窗口层级、VRM 渲染不触碰 |
| 持久化 | 无数据库 | 技能状态走 yaml + 文件系统（同 agents.yaml 模式） |
| 依赖与安装 | P2 前新增 3 包 | 纯 Python 装入现有 venv；setup.sh 流程不变 |
| 设置 / 启动器 / 关于页 | 无 | 仅设置页加一行指向「技能扩展」的说明文字 |

## 11. 风险点与守卫

- **P2 分流接触点**是唯一回归风险：功能开关默认关 → dev 先验证 → 无命中路径必须与现状一致，code-review 独立复查 diff。
- **Prompt 注入点**：技能正文只在 chat 组装处条件插入；通用规则仍留 `config/system_prompt.md`，防止主上下文变胖。
- **技能脚本**：只允许技能目录内白名单调用，不开放任意 shell。
- **MCP 子进程**：P4 才引入，懒启动 + 空闲回收；异常/超时不阻塞主请求，失败标 `disabled`。
- **依赖安装失败**：三个 Office 库若安装异常，P2 降级只读，不阻断其余技能上线。
