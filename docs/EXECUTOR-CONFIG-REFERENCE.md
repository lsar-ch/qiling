# 外部项目执行器对接借鉴点（Qwen Audio Agent / DeepTutor）

> 日期：2026-09-09
> 用途：为 DeskMate「我的智能体」配置入口与执行器接入做参考留档，避免以后重新翻源码。

## Qwen Audio Agent（本地 CLI + 桌面 App）

- 官方仓库：`https://github.com/QwenLM/Qwen-Audio-Agent`（本次核对的是本地副本
  `~/Documents/Codex/2026-09-05/qwen-ui-agent/work/qwen-audio-agent-main`）
- 桌面 App 已安装：`/Applications/Qwen Audio Agent.app`
- Codex 定位：外部 ACP 适配，README 自述「一键安装本体与适配器，需用户配置」
- 跨平台策略：Node/Electron 跨平台安装后命令进 PATH；codex 本体路径用
  `CODEX_PATH` 环境变量显式注入，不靠代码猜系统路径；平台差异统一走注入的
  `platform = process.platform` 分支（如浏览器打开 darwin→open / win32→rundll32）。
  注意：其 backend-runtime-discovery 测试大量 `skip: win32`，Windows 后端启动靠
  桌面端真机验证而非单测。

### 对接机制（源码证据）

- 一键安装：`qwenaudio install <backend>` 同时装好后端本体与所需 ACP 适配器，
  已安装时输出「✓ …已安装」，可重复执行（`cli/src/launcher.mjs`，安装器在 `shared/backend-install.mjs`）
- 参数/选择：CLI 用 `--backend codex` / `install codex`（`cli/src/arguments.mjs`）
- 运行时自动发现（`backend-runtime-discovery`）：
  - 优先用已安装的 `codex-acp`；缺失时回退到固定版本包
    `@agentclientprotocol/codex-acp@1.1.7`（pin 版本，可复现）
  - 路径可用 `CODEX_PATH` 覆盖；运行方式用 `CODEX_ACP_RUNTIME`（`auto|binary|package`）
- 状态报告：backend 带 `id / selected / ready / adapter.source('managed') /
  authentication('backend-managed')`，界面据此显示「当前 / 可安装 / 需配置」

### 可借鉴点（映射 DeskMate）

| 借鉴点 | DeskMate 落点 |
|:---|:---|
| 一键安装本体 + ACP 适配器 | codex 卡片提供「检测/补齐」动作：探测到本体缺 ACP 时提示安装命令或引导 |
| 自动发现 + 环境变量可覆盖 | 探测顺序 = PATH → 常见安装位置 → `agents.local.yaml` 手动路径覆盖 |
| ACP 适配器固定版本兜底 | 将来真实执行 codex-acp 时 pin 版本，避免上游漂移 |
| 可重复执行、幂等安装 | 「检测」按钮可反复点，不改状态不重装 |
| `CODEX_PATH` 显式注入通道 | DeskMate resolver：显式配置 > `CODEX_PATH` > PATH > 平台常见位置 |

## DeepTutor（HKUDS/DeepTutor）

- 官方仓库：`https://github.com/HKUDS/DeepTutor`（agent-native 学习工作区，本地曾以
  pip 方式安装 v1.6.3，现环境已无该安装包；如需按版本精读可拉对应 tag）
- DeskMate 旧留档：`docs/MEMORY-COMPARISON.md`（仅记忆模块，非执行器部分）
- 跨平台策略：几乎不碰“本地 CLI 可执行路径检测”——模型/后端走 Docker + Python
  服务 + 云端 API/OAuth；Windows 仅零星分支（事件循环、fcntl/msvcrt、SQLite WAL），
  定位是 POSIX 为生产目标、Windows 仅开发可用。

### 对接机制（源码证据，基于 main 分支）

- Provider 注册表单一事实源：`deeptutor/services/provider_registry.py`
  - 每个 Provider 一条 `ProviderSpec`，含 `backend` 实现类型、`env_key`、
    默认 base_url、key 前缀/base 关键词自动识别、模型家族映射
  - 新增 provider = 加一条 spec；环境变量、配置匹配、状态、下拉全部自动推导
- 设置 API 动态生成选项：`deeptutor/api/routers/settings.py`
  - `_provider_choices()` 生成各服务类型的 provider 下拉选项；
    `_connection_targets()` 返回预填值（api_base/key 前缀判断等），前端不写死 vendor
- Codex 走 OAuth 连接：`deeptutor/services/codex_auth/oauth.py`
  - PKCE + loopback 回调；`compose.codex-oauth.yaml` 临时映射回调端口
  - 凭证由后端管理，浏览器端不接触
- 模型/凭证以“服务类型 × provider 表格”为中心，UI 据此渲染表单与警告

### 可借鉴点（映射 DeskMate）

| 借鉴点 | DeskMate 落点 |
|:---|:---|
| 目录（注册表）= 单一事实源 | `config/agents.yaml` 继续作为执行器目录事实源 |
| 配置表单由后端目录动态下发 | 新增 `/api/agents/config` 返回“可编辑字段”，前端不硬编码字段 |
| 自动识别/预填 | 执行器卡片展示自动检测结果；手动路径留空即恢复自动 |
| OAuth「连接」按钮形态 | codex 卡片预留「连接 OpenAI 账号」入口位（本轮不做） |
| 状态可见、缺什么提示什么 | 卡片按 ready/pending/not_installed/error 显示缺的组件（本体 / ACP） |
| “难装就不装本地 CLI”的思路 | 非 codex 执行器可走容器/远程/OAuth 接入，绕开跨平台安装难题 |

> 注意：DeepTutor 的 backend 指“模型提供方”，Qwen Audio Agent 的 backend 指“本地
> CLI 执行器”。DeskMate 的 executor 更接近后者，故命令探测借鉴 Qwen，
> 表单/状态/OAuth 形态借鉴 DeepTutor。
