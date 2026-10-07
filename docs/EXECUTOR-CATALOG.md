# 栖灵 执行器目录

## 1. 定位

栖灵 的任务执行层不绑定单一执行器。外部 AI coding agent 通过统一 Registry / Adapter 接入，路由层只依赖执行器接口，不依赖某个固定产品名。

注册目录以 `config/agents.yaml` 为事实源。2026-09-07 用户确认默认只保留 6 个执行器：Codex、Claude Code、Qwen Code、Kimi CLI、Reasonix、WorkBuddy；其他执行器不进入默认目录。

> 能力边界：目录存在不等于真实执行。当前只有 `codex`、`workbuddy` 与内置 `browser` 可提交真实任务；其他执行器为 `pending` / `not_installed` 探测状态，不伪装成可以执行任务。

## 2. 当前注册状态

下表以 `config/agents.yaml` 为准：

| Registry name | Label | Adapter | 当前说明 |
| --- | --- | --- | --- |
| `codex` | Codex CLI | `codex` | 通过 codex-acp 支持提交、进度、取消与授权 |
| `claude-code` | Claude Code | `pending` | 只登记/探测，不执行任务；保留 ACP/stdio 接入位 |
| `qwen-code` | Qwen Code | `pending` | 阿里 Qwen 官方 CLI，只登记/探测 |
| `kimi-cli` | Kimi CLI | `pending` | Moonshot Kimi 官方 CLI，只登记/探测 |
| `reasonix` | Reasonix | `pending` | DeepSeek 原生 CLI，保留 ACP/多端接入位 |
| `workbuddy` | WorkBuddy | `workbuddy` | 通过 WorkBuddy 自带 CLI/ACP 提交真实任务 |

## 3. 扩展方式

以后需要新增执行器时，优先修改 `config/agents.yaml`；本地临时覆盖或追加则使用同目录 `config/agents.local.yaml`，不影响提交到仓库的默认目录。

推荐步骤：

1. 增加一个 `executors` 条目，先使用 `adapter: pending`。
2. 让 AgentCatalog 做登记和命令/环境探测，不直接执行任务。
3. 需要真实接入时，为该执行器实现 `AgentAdapter`，再把 `adapter` 从 `pending` 改为对应 adapter id。

前端不硬编码执行器名称，显示内容以后端 `/api/agents` 返回为准。

## 4. 配置加载优先级

1. 默认加载项目根目录的 `config/agents.yaml`。
2. 若设置 `QILING_AGENTS_CONFIG`，用它指向自定义执行器目录文件。
3. `config/agents.local.yaml` 可用于本地覆盖或追加。

配置变化只决定目录内容与探测候选；是否能真实执行仍取决于对应 Adapter / ACP / stdio 接入状态。

## 5. 在「我的智能体」页面切换

- 「设为默认」写 `agents.local.yaml` 顶层 `default_executor`，压过 `agents.yaml` 的默认值；后端就地重建注册表，无需重启服务。
  只有 `adapter.executable` 且 `default_eligible` 的条目可选：`browser` 是只读窄场景执行器，不允许当兜底默认。
- 「启用」开关写条目 `enabled`。停用后卡片仍保留并显示「已停用」，但 `AgentRunManager.execute` 会拒绝派任；
  当前默认执行器不允许直接停用，必须先切换默认。
- 两者都只落 `agents.local.yaml`（用户层），`agents.yaml` 继续作为仓库默认目录，便于回退与 diff。

详细实现目录与示例见 `docs/AGENT-INTEGRATION.md`；实际协议接入进度以 `services/ai-service` 的 Agent Adapter/Registry 与 `/api/agents` 返回状态为准。
