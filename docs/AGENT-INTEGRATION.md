# 栖灵 外部智能体接入方案

## 1. 目标

栖灵 的本地助理不必自己完成所有复杂任务。
它应该能把任务交给外部智能体执行，并把结果统一回传到挂件和主界面。

典型外部智能体包括 `config/agents.yaml` 中登记的执行器。注册目录以该配置为准，不写死三选项，2026-09-07 用户确认默认目录只保留 Codex、Claude Code、Qwen Code、Kimi CLI、Reasonix、WorkBuddy 6 个，并保留 `agents.local.yaml` 覆盖/追加入口。

Agent Registry 当前状态：

- `codex`：唯一真实可执行 adapter，已落地 codex-acp 的 initialize / session / prompt / cancel / close、进度回流、授权与结果归档
- `claude-code` 及其他非 Codex 条目：使用 `pending` adapter，只做登记/命令与环境探测；未实现真实协议前保持 `pending` / `not_installed`，不执行任务
- `workbuddy`：用户指定的预留执行器，同样只登记和探测，不执行任务

完整字段、分类与扩展方式见 `docs/EXECUTOR-CATALOG.md`。后续外部执行器按同一套 Agent Adapter / Registry 接入，路由层不依赖单一外部执行器。

## 2. 参考实现结论

Qwen-Audio-Agent 的做法不是把 Codex 直接写死在前端里，而是通过统一的后端协议层接入。

它的关键点是：

- 使用 ACP stdio 连接 coding agent
- 每个后端通过一个 adapter 适配
- Codex 有独立的 `codex-acp` 适配器
- Claude Code 也有自己的 `claude-code-acp`
- 后端安装、配置、权限探测、可用性检查都走统一入口

这意味着它的架构是“语音前端 + 后台编码代理”，而不是“某个前端特例”。

## 3. 对 栖灵 的启发

栖灵 应该复用同样的思想：

### 3.1 统一的 Agent Router

所有外部智能体都先进入统一路由层，再决定：

- 由谁执行
- 是否需要权限确认
- 是否要分拆成多个步骤
- 是否需要回传中间结果

### 3.2 统一的适配器接口

每个外部智能体最终都实现同一组边界：

- `detect`
- `connect`
- `run`
- `cancel`
- `approve`
- `report_status`

Codex 已具备运行能力；非 Codex 条目仍只注册与探测，不假装已具备运行能力。

### 3.3 统一的结果回流

外部智能体执行后，栖灵 负责把结果整理成三种输出：

- 挂件短反馈
- 主界面详细结果
- 记忆归档

## 4. 推荐接入模式

### 模式 A：本地直连

适合：

- Codex CLI
- Claude Code
- 本地可安装的 Agent

特点：

- 延迟低
- 调试简单
- 适合个人开发机

### 模式 B：云端平台代理

适合：

- 需要统一算力
- 需要隔离本机环境
- 需要多人共用后端能力

特点：

- 任务可以挂到云平台
- 本地只保留轻量前端和调度
- 更适合后期商业化

### 模式 C：混合模式

建议作为最终形态：

- 简单任务本地跑
- 重任务交给云端
- 敏感任务本地确认后再执行

## 5. 权限策略

外部智能体一定要有权限分级，否则会失控。

建议分成：

- `observe`：只观察，不执行
- `assist`：可执行低风险任务
- `confirm`：高风险动作前要确认
- `full`：完全授权，仅限信任场景

## 6. 和 Qwen-Audio-Agent 的关系

Qwen-Audio-Agent 证明了这条路是可行的。
它的重点是：

- 前台持续对话
- 后台持续执行
- 支持 Codex / Claude Code / OpenCode 等后端
- 后端通过适配器统一纳管

栖灵 可以借鉴这个骨架，但不照搬语音前端实现。

栖灵 的差异是：

- 它有桌面挂件
- 它有角色状态
- 它有主界面工作台
- 它要兼顾 Obsidian、桌面控制、知识库、记忆

## 7. 结论

如果你后面要接云平台，这是合理的。
从架构上看，最稳的路径不是直接在前端调用某个单点 Agent，而是建立统一的 Agent Router，再把 `config/agents.yaml` 中已实现 Adapter 的执行器和未来的云端后端都接进来。
