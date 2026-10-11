# agency-agents 可借鉴/可调用项

> 来源：`msitarzewski/agency-agents`（上游）/ `jnMetaCode/agency-agents-zh`（中文版）
> 调研日期：2026-10-06
> 状态：仅梳理与建议，未改动任何代码或配置；请酌情挑选后再排期
> 关联：`docs/EXTERNAL-INSIGHTS.md`（同类外部对比文档）、`AI-Memory` 中的 [[02-框架与工具/06-其他工具/agency-agents]]

## 1. 结论

它对 栖灵 的价值不在"多 279 个角色文件"，而在三样东西：

1. **一份现成的专家人格内容库** —— 可以变成 栖灵 的"专家包"内容源，喂给现有执行器或本地写作/分析能力。
2. **一套编排契约**（交接文档 + QA 通过/退回判定 + 机读 roster）—— 正好补 栖灵 多 Agent 任务链缺的"交接与验收"结构。
3. **一个目录元数据模式**（`divisions.json`：label + Lucide 图标名 + 品牌色）—— 与 `config/agents.yaml` 的目录设计同源，可低风险借鉴。

不建议把它的 Node/脚本安装链路搬进 栖灵：这个库最大的优点恰恰是"没有运行时"，栖灵 应只取**内容**和**契约**。

## 2. 栖灵 现状对照

| 栖灵 现有 | 位置 | 与 agency-agents 的关系 |
|---|---|---|
| 执行器目录（配置驱动、单一事实源） | `config/agents.yaml` + `services/ai-service/app/agents/catalog.py` | 对标 `divisions.json` + `install.sh` 的目录解析 |
| 角色卡（陪伴型人格） | `config/personas/*.yaml` + `app/core/persona_prompt.py` | 二者定位不同：角色卡是"伙伴人格"，agency 是"岗位人格" |
| 内置技能（SKILL.md + frontmatter） | `skills/builtin/*/SKILL.md` | 形态与 agency 的 agent 骨架高度同构，是最合适的落地容器 |
| 外部 Agent 执行 + 授权 | `app/agents/codex.py`、`acp.py`、`AgentRunManager` | 目前只发纯文本 prompt，无「选择子 Agent」参数 |
| 质量基线 | `scripts/check.sh`、`packages/contracts` | 可借鉴其 CI"清单与目录必须一致"的校验思路 |
| 外部对比沉淀 | `docs/EXTERNAL-INSIGHTS.md` | 本文档按同类格式新增 |

## 3. 可直接调用（不改协议）

### 3.1 专家人格作为 prompt 角色注入（现成能力即可实现）

`AgentTaskRequest.prompt` 是纯文本，`codex.py` 通过 ACP `session/prompt` 直接发送。因此**不需要改 ACP 协议**就能让外部执行器"扮演"某个专家：

```text
[专家人格 developer_instructions 全文]

---
以下是需要你完成的任务：
<用户任务 / 任务卡>
```

对应改动点（如采纳）：在 `app/agents/` 里加一个轻量的"专家提示词组装"，或在 `AgentTaskRequest.config` 里带 `expert_id`，由 `codex.py` 组装到 prompt 前缀。

### 3.2 在 prompt 中点名 Codex 子 Agent

本机已把 10 个中文版专家装进 `~/.codex/agents/`。Codex 支持在任务里直接派发子 Agent，所以 栖灵 只需在 prompt 里写清"用 `engineering-code-reviewer` 子 Agent 审查"，就能复用现成资产，零代码改动。前提是执行环境的多 Agent 能力可用（依赖模型支持 spawn）。

### 3.3 精选人格 → 栖灵 技能包

`skills/builtin/*/SKILL.md` 的 frontmatter（`name` / `description` / `triggers` / `tools` / `enabled`）与 agency 的 agent 骨架几乎一一对应，可写一个一次性转换脚本把选定的人格转成 栖灵 skill，纳入现有技能加载链路。

## 4. 值得借鉴的实现模式

### 4.1 目录元数据单一事实源（优先级最高，改动最小）

`divisions.json` 用一张表定义每个部门的 `label` / `icon`（Lucide PascalCase）/ `color`，并让 CI 校验"表 vs 磁盘目录 vs 脚本路径过滤"三者一致。

栖灵 对应物是 `config/agents.yaml` 的 `executors[]`。可借鉴的是**补上展示元数据 + 加一致性校验**：为每个 executor 增加 `icon` / `color` / `division`，并在 `scripts/check.sh` 里加一条"目录项与能力声明必须一致"的检查。

### 4.2 交接契约（补多 Agent 任务链的缺口）

`strategy/coordination/handoff-templates.md` 给了四段式交接（元数据 / 上下文 / 交付要求 / 质量预期）+ QA 通过/退回判定，明确把"交接丢上下文"列为多 Agent 协作失败的头号原因。

栖灵 的对应场景是 `AgentRunManager` 的任务转交与结果回流。可借鉴的是**给 AgentRun 结果增加结构化契约**：当前 `AgentTaskResult` 只有 `status/message/session_id/error`，可扩展验收清单与证据字段，让前台能展示"通过/退回 + 阻塞项"。

本机已落地一份精简中文模板：`~/.codex/templates/handoff-template.md`（全局 AGENTS.md 已引用），可直接复用为 栖灵 的对外契约字段设计参考。

### 4.3 机读 roster → 前端"一键组队"

`strategy/runbooks.json` 把"一支队伍"表达成 `{slug, mode, roster[{group, activation, agents[]}]}`，前端读它就能一键装配。

栖灵 对应物是「我的智能体」页的按需添加分组。可借鉴的是**把"任务组队预设"数据化**：用同样结构描述"代码评审组 / 文档组 / 调研组"，前端一键把多个 executor + 技能组合成一次任务链。

### 4.4 三级标注的审查输出

`engineering-code-reviewer` 用 🔴 阻塞 / 🟡 建议 / 💭 细节 三级，要求带行号、说清原因、附改法、"建议而不是命令"、"一次给全"。栖灵 的 `CODE-REVIEW-RULES.md` 已有类似约束，可把三级标注与"一次给全"显式写进审查类技能的输出模板，保证前端渲染结构稳定。

### 4.5 证据链与放行判定

`testing-evidence-collector`（每个结论必须有可复现证据）与 `testing-reality-checker`（默认"需要改进"，要求压倒性证据才认定生产就绪）是两条互补纪律。栖灵 的授权/审批链路可以借鉴这个分工：一个负责收证据，一个负责下放行结论，避免"自己验自己"。

## 5. 建议不采纳

- 不搬它的 `scripts/install.sh` / `convert.sh` 链路进 栖灵 —— 栖灵 是产品，不是 dotfiles 分发器；需要内容时用一次性转换脚本即可。
- 不照搬 18/20 部门分类法 —— 栖灵 的 `capabilities` 维度（code / project / task_execution）更贴合产品语义。
- 不整包引入 277 个角色 —— 内容体积与选择成本都不划算；按场景精选。
- 不把陪伴型 `config/personas` 和岗位型 expert 混在一个概念里 —— 前者是角色表现，后者是任务能力，建议在数据模型上分开。

## 6. 建议排期（按性价比）

| 优先级 | 事项 | 涉及文件/模块 | 备注 |
|---|---|---|---|
| P1 | executor 目录补展示元数据 + 一致性校验 | `config/agents.yaml`、`catalog.py`、`scripts/check.sh` | 改动小、纯增字段 |
| P1 | 精选专家人格转 栖灵 技能包 | `skills/builtin/`、一次性转换脚本 | 先做 5-10 个验证形态 |
| P2 | AgentRun 结果加交接/验收契约字段 | `packages/contracts`、`app/agents/base.py` | 需契约两侧同步改 |
| P2 | prompt 专家注入（`expert_id`） | `app/agents/codex.py`、`AgentTaskRequest.config` | 不改 ACP 协议 |
| P3 | 任务组队预设（roster） | 「我的智能体」页、`config/agents.yaml` 同目录 | 依赖 P1 元数据 |

## 7. 参考链接

- 上游仓库：https://github.com/msitarzewski/agency-agents
- 中文版仓库：https://github.com/jnMetaCode/agency-agents-zh
- 交接模板：https://github.com/jnMetaCode/agency-agents-zh/blob/main/strategy/coordination/handoff-templates.md
- 编排 runbook：https://github.com/jnMetaCode/agency-agents-zh/blob/main/strategy/runbooks.json
- Codex 子 Agent 文档：https://learn.chatgpt.com/codex/agent-configuration/subagents
