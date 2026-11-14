# 栖灵 社区 Agent / Skill / MCP 部署清单

这份清单只提供来源、配置和安全边界。栖灵不会自动下载、执行远程安装脚本，也不会代用户保存第三方密钥。

## 使用顺序

1. 先确认任务是否能由 `inline` 或栖灵托管的 `mcp` 完成。
2. 只有代码、终端、多文件或长任务才启用 `acp` Agent。
3. 先使用只读权限和空工作区验证，再按需扩大权限。

## ACP Agent

| Agent | 目录配置 | 来源 | 许可证 | 用户准备 | 凭据与风险 |
| --- | --- | --- | --- | --- | --- |
| Claude Code | `claude-code`，通用 `acp-cli` | `agentclientprotocol/claude-agent-acp`（见 `config/agents.yaml`） | 部署前核验来源仓库 LICENSE | 按来源安装 ACP 启动器，并确认命令可在终端运行 | `ANTHROPIC_API_KEY` 或厂商登录态；默认停用，首次运行前先做只读任务 |
| Qwen Code | `qwen-code`，通用 `acp-cli` | `QwenLM/qwen-code`（见 `config/agents.yaml`） | 部署前核验来源仓库 LICENSE | 安装 Qwen CLI，并使用 ACP 模式 | `OPENAI_API_KEY`，可配 `OPENAI_BASE_URL`；仅向可信端点发送数据 |
| Kimi CLI | `kimi-cli`，通用 `acp-cli` | `MoonshotAI/kimi-cli`（见 `config/agents.yaml`） | 部署前核验来源仓库 LICENSE | 安装 Kimi CLI，并确认 `kimi acp` 可运行 | `MOONSHOT_API_KEY` 或厂商登录态；按服务条款使用 |
| Codex CLI | `codex`，专用 ACP adapter | `openai/codex`（见 `config/agents.yaml`） | 部署前核验来源仓库 LICENSE | 保留现有 Codex 登录态或配置 Key | 默认执行器；读写权限仍受栖灵确认链路控制 |
| WorkBuddy | `workbuddy`，专用 adapter | 栖灵目录未声明公开仓库 | 以官方服务条款为准，部署前核验 | 依照桌面端/CLI 的官方要求完成登录 | 不复用桌面端登录态；启用前确认订阅和 Key 配置 |

来源地址以 `config/agents.yaml` 和扩展页的“项目与部署来源”为准。条目显示“就绪”只代表命令可解析；点击测试连接后才会验证 ACP 握手，不能把 `npx` 存在当成已安装或已认证。

## Skill

- 优先使用带来源、版本、许可证和 `supported_agents` 的 Skill。
- Skill 只提供指引和元数据，不授予文件、终端或网络权限。
- 上传 zip 或注册本地目录前，先检查 `SKILL.md`、脚本和依赖；未知脚本不要自动执行。
- Skill 与执行模式不兼容时，回退到 `inline` / `mcp` 或明确提示用户，不强行交给外部 Agent。

## MCP

- 默认使用 `read` 服务器；写操作必须走栖灵原有确认链路。
- ACP 任务指定 MCP profile 时，只会把已启用且 `access: read` 的服务器传给 `session/new`。
- 不要把 API Key 写进仓库、Skill、任务文本或日志；使用栖灵的本地凭据配置。
- 外部 Agent 自带的全局 MCP 不在栖灵白名单控制范围内，使用前应在 Agent 自身配置中关闭不需要的服务器。

## 安全检查

- 来源是否为官方仓库或可信发行渠道。
- 许可证是否允许当前用途，且版本可追溯。
- 凭据是否只保存在本机安全配置中。
- 工作目录是否为本次任务专用目录，是否包含不应上传的文件。
- 首次运行是否先用“只读 + 纯文本”任务验证结果、日志和取消链路。
