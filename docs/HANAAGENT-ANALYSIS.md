# HanaAgent (openhanako) 调研与 DeskMate 路线结论

## 1. 调研对象

- 项目：`HanaAgent` / `liliMozi/openhanako`
- 定位：有记忆、有人格、能自己干活的私人 AI 桌面助理
- 技术栈：Electron + React 19 + Zustand + Vite + Hono，TypeScript，Apache-2.0
- 平台：macOS / Windows / Linux，另有移动端 PWA、LAN 前端、多平台 Bridge
- 调研方式：拉取仓库源码后对核心模块做只读分析（源码保留在本项目 `.research/openhanako`，不入库）

## 2. 已确认的能力

### 记忆

- v2 起不用向量检索，改用 SQLite `better-sqlite3` + FTS5 + 标签 + 中文 ngram
- 有 `fact-store`（重要事实）、`pinned-memory`、`session-summary`、`deep-memory`、`dream` 等模块
- 记忆编译器使用“today.md → daily → week → longterm”滚动传送带，最终 assemble 成有限 token 的 memory.md
- 记忆可见、可读、可编辑，和 DeskMate“可审计记忆”的方向一致

### 人格 / 角色卡

- 内置 Hanako、Ming、Butter、Kong 等 Agent 模板
- 有完整 `character-card` 导入/导出机制，支持 manifest + card + 记忆 + 文件包
- Agent 之间身份、记忆、工具集分离
- 可导入社区角色卡，可备份/复制文件夹迁移

### Agent / 工具 / 桌面操作

- 基于 `@earendil-works/pi-agent-core` / `pi-coding-agent`
- 支持 subagent、workflow、channel、自动化/定时任务、Agent 间 DM 和委派
- 有 Computer Use helper、浏览器管理、截图、桌面窗口/文件工具
- 有双层沙盒和 PathGuard 等安全设计

### 界面 / 扩展

- 主桌面应用是 Electron 主窗口 + 设置窗口 + Quick Chat 小窗 + 浏览器/文件查看器等
- 主界面有会话、右键工作区、Skills、Automation、Bridge、记忆、Agent 设置等
- 支持 MCP、插件体系、SKILLS 生态，国际化 5 种语言

## 3. 尚未覆盖或较弱的部分

以下能力在当前源码中基本缺失或很弱：

- 没有“桌面挂件人物/动物角色”作为常驻交互入口
- 没有聆听/思考/说话/执行/授权等挂件状态动画体系
- 2D 角色只是静态头像/启动图，不是分层可动画角色
- 语音识别只覆盖“发送语音条后转录”，依赖 OpenAI / DashScope / MiMo / 火山等云端 ASR
- TTS 在设置界面标注为 coming soon，尚未内置
- 没有完整“语音对话 + barge-in + 角色语气/情感映射”链路

## 4. 与 DeskMate V1 的差距分析

| V1 能力 | HanaAgent 现状 | 结论 |
|---|---|---|
| 桌面挂件 | 无 | DeskMate 自研核心 |
| 挂件状态动画 | 无 | DeskMate 自研核心 |
| 2D 角色资产 | 只有静态头像 | 需自建分层资产 |
| 浏览器主界面 | 桌面应用 + PWA/LAN | 可借鉴但路径不同 |
| 文字对话 | 强 | 参考实现 |
| 语音识别 | 部分（语音条转录） | 可借鉴 provider adapter |
| TTS / 语音输出 | 无 | DeskMate 自研 |
| 全双工 / 打断 | 无 | DeskMate 自研 |
| 记忆 | 很强 | 借鉴分层和文件化思路 |
| 人格 / 角色卡 | 很强 | 借鉴角色卡结构 |
| 任务分流 | 内置 | 借鉴判定逻辑 |
| Agent Router | 有 subagent/workflow | 参考统一路由思想 |
| Codex 接入 | 未直接看到 | 按 Qwen-Audio-Agent ACP 思路继续 |
| MCP / Skill | 强 | 不重复造轮子 |
| 桌面操作 | 有 Computer Use | 按自身授权模型约束 |
| 跨平台 | macOS/Win/Linux | 同为 Electron 思路可行 |

## 5. 路线建议

### 结论：不建议直接 fork 作为 DeskMate 基底，也不建议完全从零自研后端

理由：

1. HanaAgent 与 DeskMate 重叠的是 Agent/记忆/工具底座，这层很重；自己重写成本高
2. HanaAgent 缺的恰好是 DeskMate 的核心差异：桌面角色、状态反馈、语音输出与全双工
3. 直接 fork 大而全应用再改造，学习成本和后续维护成本高，且人格/记忆/沙盒实现会绑架我们的产品节奏
4. 但它的记忆、角色卡、subagent、沙盒等设计，是很好的“参照实现”，比纸面方案更可信

### 推荐路线：DeskMate 保持独立，分层借鉴

```text
DeskMate 独立产品层
  ├─ 桌面挂件 + 状态机 + 2D 角色（自研）
  ├─ 语音交互 + TTS + 语气规范（自研）
  ├─ 浏览器主界面（自研，参照 React 信息架构）
  └─ Agent Router / 授权模型（自研接口）

可借鉴实现
  ├─ 记忆：facts / compiled memory / 滚动摘要
  ├─ 角色卡：manifest + identity + memory 的导入导出
  ├─ 安全：沙盒分级、权限边界
  └─ 扩展：MCP / Skill / 插件注册
```

### 后续如果要把 Agent 底座做实

不急于第一版决定。等 DeskMate V1 主链路跑通后，再做一次取舍：

- 继续自己维护轻量 Agent 底座
- 通过 ACP / 协议接入成熟 Agent（Qwen-Audio-Agent 路线）
- 在成熟 Agent 底座上重建 DeskMate 的桌面角色层

## 6. 本轮行动建议

1. 保留 HanaAgent 源码在本地 `.research/` 供后续对照
2. 不修改我们的 V1 架构文档
3. 记忆方案可补充一条“参考 HanaAgent fact-store + FTS + 标签检索，暂不做向量库”
4. 角色卡方案后续可参考 HanaAgent 的 manifest / card / memory 打包结构
5. V1 先按既有接口把 DeskMate 挂件和语音主链路做出来，再回来对照 HanaAgent
