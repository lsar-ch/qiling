# DeskMate 记忆方案（合流版）

> 2026-09-04 更新：在 DeepTutor 档案式记忆基础上，合流 HanaAgent 的上下文注入思路。
> 对比依据见 [记忆模块对比留档](./MEMORY-COMPARISON.md)，V1 详细结构与接口见 [V1 记忆模块](./V1-MEMORY.md)。

## 1. 目标

记忆不是简单聊天记录，而是让 DeskMate 持续理解用户、项目与任务状态，做到「越用越懂你」。

记忆系统要支持：

- 记住用户偏好与稳定事实
- 记住项目进度与重要决定
- 记住人设（角色）相关稳定信息，且与用户记忆分离
- 保持可审计、可编辑、可回溯
- 控制注入模型的 token，长会话不膨胀

## 2. 设计判断：两个问题，两条借鉴路线

记忆实际上要解决两个不同问题，不能混成一个系统：

| 问题 | 对应需求 | 借鉴来源 | 交付物 |
|---|---|---|---|
| A. 长期档案：记什么、对不对、能不能改 | 「越用越懂你」、可查看修正 | DeepTutor 三层模型 | L1/L2/L3 Markdown 档案 |
| B. 运行上下文：每次喂多少、怎么滚动 | 语音长对话不跑偏、不超上下文 | HanaAgent 编译传送带 | 会话摘要 + 编译注入 |

结论：**合流，不是二选一**。

## 3. 存储分层（借鉴 DeepTutor）

### 3.1 L1：事件层（留痕）

记录原始交互事件：用户说了什么、系统做了什么、任务结果、用户确认、失败原因等。

- 存储：`trace/<surface>/<YYYY-MM-DD>.jsonl`，append-only。
- 目标：完整留痕，不做判断，写入失败不影响主流程。

DeskMate 的 surface 建议：

- `conversation`：对话（含语音）
- `task`：任务执行与桌面操作
- `kb`：知识库检索/读写（如 Obsidian）
- `project`：项目进度与工作区事件
- `partner`：人设/角色相关的记忆

### 3.2 L2：场景事实层（归纳）

从 L1 提炼相对稳定、按场景组织的事实，每个 surface 一个 Markdown 文件（`L2/<surface>.md`），例如：

- 用户偏好中文界面
- 语音中断后倾向复述关键结果
- 某项目处于需求定稿阶段
- 常用知识库来源

### 3.3 L3：画像层（综合）

跨场景的长期结论，四个固定 slot（`L3/<slot>.md`）：

- `profile`：用户是谁、性格节奏、沟通风格
- `preferences`：稳定偏好（语言、界面、语气）
- `progress`：各项目当前进度与关键里程碑
- `recent`：最近在做什么（近期主题窗口）

### 3.4 可审计格式

L2/L3 使用带引用的 Markdown：

```markdown
## 偏好
- 用户偏好中文界面 [^1][^2] <!--m_xxx-->

[^1]: conversation:evt_xxx
[^2]: conversation:evt_yyy
```

- 每条记忆有唯一 entry id（`m_xxx`），可定位、可删除。
- footnote 引用 L1 原始事件，能回答「这条记忆怎么来的」。
- 用户可直接在设置/记忆页编辑或删除，也可打开原始文件修改。
- 文件化后天然兼容 Git 与 Obsidian 类工具。

## 4. 会话与注入层（借鉴 HanaAgent）

档案层解决「存得住」，注入层解决「喂得进」。

### 4.1 会话摘要

- 每次对话结束，生成一段简短 session summary（说了什么、确认了什么、待办什么）。
- 落盘为 `session/<date>.md`，摘要本身也写入 L1 事件，保证可回溯。

### 4.2 滚动编译

- 参照 HanaAgent 的 today → daily → week → longterm 传送带，把零散记忆滚成层级摘要。
- 编译产物 `compiled/memory.md` 是**唯一默认注入模型**的记忆文本，带 token 预算边界。

### 4.3 组装顺序

注入时按固定顺序组装，超过预算截断低优先内容：

```text
1. 人设档案（固定，少）
2. L3：profile / preferences / progress / recent
3. L2：与本轮相关场景的事实
4. 今日会话纪要 / 最近 session summary
5. FTS 检索命中条目（相关性优先）
```

- 无相关记忆时整段跳过，不为凑内容浪费 token。
- 系统提示、任务上下文、对话历史与记忆分层管理，互不污染。

## 5. 检索

- V1 用关键词 + SQLite FTS5（中文 ngram），不引入向量库；记忆量小、可解释、易调试。
- 记忆量或场景数上来后，再接向量检索 / 复用 Obsidian RAG，检索结果仍只作为注入素材，不替代档案本身。

## 6. 角色记忆与用户记忆分离

- **用户记忆**：用户是谁、喜欢什么、在做什么。
- **角色记忆（persona）**：当前助手怎么说话、什么性格、行为边界。

规则：

- persona 是稳定配置，写成独立角色档案（`persona/<character>.md`），不混入 L3 用户画像。
- 同一套用户记忆可服务不同角色；角色不共享人设记忆。
- 未来多角色时，按 DeepTutor partner surface / HanaAgent 角色卡做隔离，一个角色一套身份+记忆空间。

DeepTutor 伙伴机制的启发：persona 应作为独立实体存在，便于做角色对比实验（台北女秘书、冷静执行官、轻松陪伴型等），而不是把角色临时拼进对话上下文。

### 6.1 角色卡草案（人设标签体系，2026-09-04）

> 用户思路：配置角色（人物/动物）时，除形象与音色外还要绑定人物背景、经历、说话习惯等「系列标签」，
> 让对话贴合角色（如自定义角色「银月」时使用其克隆音色 + 人设背景）。
> 结论：**可行**。与上述 persona 独立档案设计一致，本质是把「自由文本人设」结构化为可配置的角色卡。

角色卡 = 形象 + 声音 + 人格三层绑定，同一 `persona/<character>.md` 承载：

| 层 | 控制什么 | 生效位置 |
|---|---|---|
| 形象层 | 2D 形态/动画状态 | 前端挂件与主界面 |
| 声音层 | `voice_id`（系统预置或克隆） | TTS 供应商（MiniMax 克隆见 `docs/VOICE-PROVIDERS.md` §4.5） |
| 人格层 | 背景、性格、口音、行为规则 | LLM 注入（决定说什么、怎么说） |

结构化字段（草案，未固化到契约）：

- `identity`：名字/别名、类型（人物/动物/虚构角色）、设定来源。
- `voice`：provider、`voice_id`、来源（`system` | `clone`）、素材授权标记、是否支持 emotion。
- `personality`：3-5 个可操作性格标签；纯形容词不稳定，需配行为描述（例如不只写“活泼”，还要写“句子短、带语气词”）。
- `speech`：口音（如台湾腔）、语气词/用词表、对用户的称呼、句长偏好。
- `rules`：行为边界、授权要求、主动提问时机（对齐高风险操作授权规则）。
- `backstory`：背景与经历长文，按需检索注入，不常驻 prompt。

注入预算沿用 V1 设计（见 `docs/V1-MEMORY.md` 的 CompiledMemory budget）：人格核心块常驻 ≤500 字符，
`backstory`/示例按检索命中才注入；人设是稳定配置，动态状态（正在执行什么、等待什么）写 partner L1/L2，不进人设档。

## 7. 存储目录布局

```text
data/memory/
├── trace/<surface>/<date>.jsonl     # L1，append-only
├── L2/<surface>.md                  # L2，场景事实
├── L3/<slot>.md                     # L3，画像（profile/preferences/progress/recent）
├── persona/<character>.md           # 角色档案（人设独立，非用户记忆）
├── session/<date>.md                # 会话纪要（滚动摘要原料）
├── compiled/memory.md               # 编译产物（默认注入源）
├── meta/…                           # 增量游标、consolidator 状态
└── index.db                         # SQLite FTS 检索索引
```

## 8. 记忆更新规则

不是每句话都记，只沉淀：

- 明确偏好
- 稳定事实
- 项目进度变化
- 重要决定
- 用户显式要求记住的内容

触发时机：

- 会话结束 → 必写 session summary（V1 起）
- 关键节点 → 沉淀偏好/事实/进度到 L2/L3
- 定时/手动 → consolidator 增量整理与去重
- 用户修正 → 以用户编辑为准，覆盖系统沉淀

## 9. V1 边界

V1 记忆做到最小闭环：

1. 对话/任务事件写入 L1
2. 会话结束生成摘要（session）
3. 关键事实沉淀 L2/L3（用户偏好、项目进度）
4. 基础 FTS 检索 + 注入组装
5. 主界面可查看、编辑、删除

发布形态默认按三档：

- `standalone`：只用本地 `data/memory`，不依赖 Obsidian
- `obsidian_linked`：在本地记忆之外，额外读用户 vault 做只读检索
- `export_import`：本地记忆保留为档案源，后续补导出/导入迁移能力

V1 后增强：完整 consolidator（audit/dedup/dream 反思）、多角色记忆隔离、向量检索、跨设备同步。

## 10. 相关文档

- 对比依据：`MEMORY-COMPARISON.md`
- V1 数据结构与接口：`V1-MEMORY.md`、`V1-INTERFACES.md` §8
- 主界面记忆页：`MAIN-INTERFACE.md`
- 实施顺序：`V1-IMPLEMENTATION-PLAN.md` Step 5
