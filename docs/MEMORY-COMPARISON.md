# HanaAgent 与 DeepTutor 记忆模块对比（留档）

> 日期：2026-09-04
> 用途：确定 DeskMate 记忆方案应借鉴哪个项目，结论留档，避免后续反复比较。

## 1. 对比依据

本次对比基于本地源码，不依赖网络资料：

- **DeepTutor v1.6.3**（本地安装包）
  `~/.pyenv/versions/3.12.9/lib/python3.12/site-packages/deeptutor/services/memory`
  三层记忆子系统，约 6700 行。
- **HanaAgent（openhanako）**（拉取的只读源码）
  `.research/openhanako/lib/memory` 及配套 `tests/`，记忆相关模块约十余个文件。
- 共同点：两套实现都**不依赖向量库**，都强调记忆可见、可读、可管理，方向上与 DeskMate 一致。

## 2. 一句话结论

> 两个项目解决的是记忆的**两个不同问题**，不存在谁全面更好：
> DeskMate 应「档案式长期记忆借鉴 DeepTutor + 运行时上下文注入借鉴 HanaAgent」，合流而不是二选一。

## 3. 本质定位差异

| | DeepTutor 记忆 | HanaAgent 记忆 |
|---|---|---|
| 服务对象 | 学习者画像 + 工作区活动 | 长期运行的私人 AI 助理 |
| 核心问题 | 「记住的东西对不对、能不能溯源、能不能改」 | 「每次对话喂多少、怎么滚动、怎么不超上下文」 |
| 结果形态 | 一份可读可编辑的档案 | 一份按预算编译出来的运行上下文 |
| 偏向 | 档案正确性 | 上下文连续性 |

## 4. 分维度对比

### 4.1 分层模型

- **DeepTutor**：L1 事件 trace → L2 按 surface 归纳 → L3 跨 surface 画像。层次语义清晰。
  - L1：`trace/<surface>/<date>.jsonl`，append-only 原始事件。
  - L2：每个 surface 一个 Markdown 文件（chat / notebook / quiz / kb / book / partner / cowriter）。
  - L3：四个固定 slot：`recent / profile / scope / preferences`，Markdown 文件。
- **HanaAgent**：模块更多但目标单一：facts + pinned + session-summary + deep-memory + dream（后台反思重写），最终由 `compile` 汇总成一份有限 token 的 memory.md。

### 4.2 存储形态

- **DeepTutor**：Markdown + JSONL。人类可直接读、直接改，可用 Git 管理，天然适合对接 Obsidian。
- **HanaAgent**：SQLite（better-sqlite3）+ FTS5 + 标签 + 中文 ngram。检索强，适合海量碎片。

### 4.3 可审计性

- **DeepTutor** 更强：
  - 每个 Markdown 条目有 entry id 锚点（`<!--m_xxx-->`）。
  - 条目通过 footnote 引用回 L1 原始事件，可溯源「这条记忆怎么来的」。
  - `audit` 模式按行展示并对着原始证据逐行核对修改。
- **HanaAgent** 居中：记忆可见，但 compile / dream 重写链条较长，来源追踪不如 DeepTutor 完整。

### 4.4 写入与更新机制

- **DeepTutor**：
  - `update`：增量提取，按 meta id 差集算出「上次刷新以来的新增」，chunk 提取新事实，原子落盘。
  - `dedup`：迭代合并/删除重复条目（只删不增，0 edits 提前停止）。
  - `merge`：免 LLM 的 footnote 整理。
  - run 可取消、带进度事件、带 undo 检查点。
- **HanaAgent**：
  - memory-ticker 定时触发，session-summary 会后汇总，dream 后台反思修订，全天候滚动。

### 4.5 上下文与 token 管理

- **DeepTutor**：弱项。读取基本是全量拼接（如 read_memory 返回 L3 全文），目的是档案准确而非省 token。
- **HanaAgent**：强项。today → daily → week → longterm 传送带 + token 预算边界 + 只注入编译产物，专门解决长会话上下文膨胀。

### 4.6 角色与画像隔离

- **DeepTutor**：记忆按 surface 分，其中 `partner` 是独立 surface；伙伴运行时可通过 contextvar 切换成读**主人的**记忆。
- **HanaAgent**：每个 Agent 身份记忆隔离 + 角色卡（character-card）体系。
- 两者都支持「角色记忆 ≠ 用户记忆」，方向与 DeskMate 人设需求一致。

### 4.7 工程形态与借鉴成本

- **DeepTutor**：约 6700 行，consolidator 依赖 LLM 且较重，绑定 Python + 自身架构；直接搬不现实，适合借鉴设计。
- **HanaAgent**：TypeScript 模块边界清楚（compile / session-summary / fact-store / ticker / dream / search），思路容易单点移植。

## 5. DeskMate 合流结论

1. **长期档案骨架用 DeepTutor 路线**：L1 JSONL 留痕 → L2 场景事实 → L3 画像（profile / preferences / progress / recent），全部 Markdown、带溯源引用与可编辑锚点。匹配「越用越懂你 + 可查看可修正」。
2. **Prompt 注入层用 HanaAgent 路线**：会话摘要 + 滚动编译 + token 预算，只把编译产物注入模型，避免挂件长对话撑爆上下文。
3. **检索先不做向量**：沿用 HanaAgent 验证过的 SQLite FTS5 + ngram（或小规模 Markdown 关键词检索），等数据量大再接向量/Obsidian RAG。
4. **人设记忆独立成档**：角色档案（如台北女秘书）作为稳定配置，与用户画像分离；后续可按 DeepTutor partner / HanaAgent 角色卡做多角色隔离。
5. **V1 做最小闭环**：会话摘要 + 关键事实沉淀 + 可查看/编辑/删除，完整 consolidator（audit / dedup / dream）放 V1 后。

## 6. 结论落地到哪些文档

- 总体方案：`MEMORY-SCHEME.md`（合流版）
- V1 结构与接口：`V1-MEMORY.md`、`V1-INTERFACES.md` §8
- 实施顺序：`V1-IMPLEMENTATION-PLAN.md` Step 5

## 7. 关键源码位置（后续对照用）

DeepTutor（`services/memory/`）：
- `paths.py`（目录/分层定义）、`trace.py`（L1）
- `document.py`（L2/L3 Markdown 格式与解析）
- `store.py`（MemoryStore 门面）、`recall.py`（近期回顾）
- `consolidator/modes/{update,audit,dedup,merge}.py`

HanaAgent（`lib/memory/`）：
- `fact-store.ts`、`session-summary.ts`
- `compile.ts`、`rolling-summary-format.ts`
- `memory-ticker.ts`、`dream/`、`memory-search.ts`
