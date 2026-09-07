# V1 记忆模块结构与接口

> 版本：V1 · 2026-09-04
> 上层设计见 [记忆方案（合流版）](./MEMORY-SCHEME.md)，总体接口见 [V1 核心接口](./V1-INTERFACES.md) §8。
> 本文档是记忆模块的详细规格：数据模型、目录布局、内部结构、服务接口、注入组装、HTTP/WS API 与 V1 边界。

## 1. 范围与目标

V1 记忆模块完成最小闭环：

- L1：对话/任务事件完整留痕
- Session：会话结束自动生成摘要
- L2/L3：沉淀用户偏好、稳定事实、项目进度
- 检索：FTS 关键词检索
- 注入：按 token 预算组装 memory 文本供模型使用
- 管理：主界面可查看、编辑、删除记忆

## 2. 在系统中的位置

```text
语音/文字 → Conversation Gateway
              → Task Router / Agent Router
              → Event Bus ──────────────→ MemoryService（订阅写入）
                                          → Widget + Web UI（memory.* 事件）
LLM Provider  ← recall_context() 组装好的 memory 块
```

- 所有模块通过事件总线与 MemoryService 解耦。
- 模型侧不直接访问记忆库，只消费 `recall_context()` 的编译产物。
- 记忆写入失败不得影响对话主流程（写失败记日志降级）。

## 3. 数据模型

### 3.1 Surface

```python
Surface = Literal[
    "conversation",  # 对话（文字/语音）
    "task",          # 任务执行、桌面操作
    "kb",            # 知识库检索/读写
    "project",       # 项目进度与工作区
    "partner",       # 人设/角色记忆
]
```

### 3.2 TraceEvent（L1）

```json
{
  "id": "conversation:01HXXXX",
  "ts": "2026-09-04T10:00:00Z",
  "surface": "conversation",
  "kind": "user_stated_preference",
  "payload": { "text": "界面用中文", "source": "voice" },
  "session_id": "session_01",
  "turn_id": "turn_01"
}
```

常用 kind 示例：

- `conversation.*`：input / response / interrupted / stated_preference / confirm
- `task.*`：created / started / progress / completed / failed / approval_result
- `kb.*`：query / read / write / update
- `project.*`：milestone / status_change / decision

### 3.3 MemoryDoc 与 Entry（L2/L3）

```python
@dataclass
class Entry:
    id: str          # m_xxxx（唯一锚点）
    section: str     # 所在小节，如 "偏好"
    text: str        # 记忆内容
    refs: list[str]  # 引用的 L1 trace id
    created_at: str
    updated_at: str

@dataclass
class MemoryDoc:
    layer: Layer     # "L2" | "L3" | "persona"
    key: str         # L2: surface；L3: slot；persona: 角色名
    title: str
    sections: list[tuple[str, list[Entry]]]
```

磁盘格式（Markdown）：

```markdown
# 用户画像

## 偏好
- 界面使用中文 [^1] <!--m_01H...-->

[^1]: conversation:01H...
```

### 3.4 L3 Slot 与 persona

```python
L3Slot = Literal["profile", "preferences", "progress", "recent"]
```

- persona 文件单独放 `persona/<character>.md`，结构与 L3 相同但不属于用户记忆。
- 同一角色在任务中的关键状态（正在执行什么、等待用户什么）写入 partner surface 的 L1/L2，不写进人设档。

### 3.5 SessionSummary 与 CompiledMemory

```python
@dataclass
class SessionSummary:
    session_id: str
    date: str
    topic: str          # 本会话主题（一句）
    outcome: list[str]  # 结论/产出
    open_items: list[str]
    decisions: list[str]
    created_at: str

@dataclass
class CompiledMemory:
    built_at: str
    budget: int                 # token/字符预算
    blocks: list[MemoryBlock]   # 按注入顺序

@dataclass
class MemoryBlock:
    source: str   # persona | L3.profile | L3.preferences | L2.<surface> | session | search
    text: str
    chars: int
```

### 3.6 检索与概览

```python
@dataclass
class SearchHit:
    entry_id: str
    layer: str
    key: str
    section: str
    text: str
    refs: list[str]
    score: float

@dataclass
class DocOverview:
    layer: str
    key: str
    title: str
    entry_count: int
    updated_at: str | None
```

## 4. 存储目录布局

```text
data/memory/
├── trace/
│   ├── conversation/2026-09-04.jsonl
│   ├── task/2026-09-04.jsonl
│   ├── kb/2026-09-04.jsonl
│   ├── project/2026-09-04.jsonl
│   └── partner/2026-09-04.jsonl
├── L2/conversation.md
├── L2/task.md
├── L2/kb.md
├── L2/project.md
├── L2/partner.md
├── L3/profile.md
├── L3/preferences.md
├── L3/progress.md
├── L3/recent.md
├── persona/<character>.md
├── session/<YYYY-MM-DD>.md
├── compiled/memory.md
├── meta/<layer>/<key>.meta.json     # consolidator 增量游标
└── index.db                          # SQLite FTS5（中文 ngram）
```

- Markdown/JSONL 为真相源（source of truth），SQLite 只做检索索引。
- 索引可随时从 Markdown 重建，不承担存储职责。

## 5. 模块内部结构

AI 服务内记忆模块目录（对应实现顺序自下而上）：

```text
services/ai-service/memory/
├── schema.py         # 上述 dataclass / 类型
├── paths.py          # data/memory 路径解析
├── trace.py          # L1：append / iter / count
├── docstore.py       # L2/L3/persona Markdown 读写、entry 增删改、原子落盘
├── session.py        # 会话摘要写入与按日聚合
├── compile.py        # 滚动编译（session → compiled/memory.md，token 预算）
├── recall.py         # 近期回顾：最近 surface 活动、最近主题
├── search.py         # SQLite FTS5 索引维护与查询
├── consolidator.py   # 增量提取 update；dedup/audit 为 V1 后
├── persona.py        # 角色档案读写与默认角色
└── service.py        # MemoryService 门面（对外唯一入口）
```

职责边界：

- `trace.py`：只追加，永不修改历史；失败静默降级。
- `docstore.py`：纯读写 + 格式校验；不调用 LLM。
- `compile.py`：只做组装与预算裁剪；不判断该记什么。
- `consolidator.py`：调用 LLM 做「自上次以来新增」的增量提取，落盘前必须带 refs。
- `service.py`：对事件总线、对话链路、Web UI 暴露接口。

## 6. 服务接口

```python
class MemoryService:
    # ── L1 写入 ──────────────────────────────
    async def record_event(
        self, surface: Surface, kind: str, payload: dict,
        *, session_id: str | None = None, turn_id: str | None = None,
    ) -> str: ...  # 返回 trace id

    # ── 会话摘要 ─────────────────────────────
    async def write_session_summary(self, summary: SessionSummary) -> None: ...
    async def list_sessions(self, limit: int = 20) -> list[dict]: ...

    # ── L2/L3 沉淀与管理 ─────────────────────
    async def upsert_entry(
        self, layer: Layer, key: str, section: str, text: str,
        refs: list[str], *, replace_duplicate: bool = True,
    ) -> str: ...                       # 返回 entry id
    async def read_doc(self, layer: Layer, key: str) -> MemoryDoc: ...
    async def overwrite_doc(self, layer: Layer, key: str, md: str) -> None: ...
    async def delete_entry(self, layer: Layer, key: str, entry_id: str) -> bool: ...
    async def overview(self) -> list[DocOverview]: ...

    # ── 注入（给 LLM）───────────────────────
    async def recall_context(
        self, *, prompt_kind: str = "chat",
        budget_chars: int = 4000,
        surfaces: list[Surface] | None = None,
    ) -> CompiledMemory: ...

    # ── 检索 ────────────────────────────────
    async def search(self, query: str, limit: int = 10) -> list[SearchHit]: ...

    # ── 维护 ────────────────────────────────
    async def consolidate(self, mode: str = "update",
                          layer: Layer, key: str) -> str: ...  # run id
    async def rebuild_index(self) -> None: ...

    # ── Persona ─────────────────────────────
    async def get_persona(self, name: str) -> MemoryDoc | None: ...
    async def save_persona(self, name: str, md: str) -> None: ...
```

说明：

- 所有写操作是幂等或可重复的：upsert 按「文本 + section」去重，覆盖前保留 refs 并追加新引用。
- 事件总线写入口只有 `record_event`；L2/L3 的沉淀由 consolidator 或显式调用完成，不让每句话都直写。

## 7. 注入组装（recall_context）

组装算法：

```text
budget = 默认 4000 字符（可配置，按模型上下文调整）

blocks = []
1. persona：当前角色档案全文（通常 < 500 字符，超限截断为头部）
2. L3.profile / L3.preferences / L3.progress：各取全文，超限时按 section 优先级裁
3. L2：按本轮 prompt_kind 映射 surface 白名单，取相关场景文档（仅新近/高频 section）
4. session：今日纪要 + 最近 1–2 次 session summary
5. search：若 query 提取出关键词，FTS 命中并入（相关性排序，限 3–5 条）

按顺序累加；超预算时从后往前截断低优先 block；
若 1–5 全部为空 → 返回空 CompiledMemory（跳过注入，不占 token）。
```

- 记忆只作为只读上下文注入；写记忆永远走显式接口。
- `compiled/memory.md` 落盘用于调试和 UI 展示「本次注入了什么」。

## 8. HTTP / WS API（主界面记忆页）

```text
GET    /api/memories/overview                     # 各文档概览
GET    /api/memories/docs/{layer}/{key}           # 读取某文档（含 sections/entries）
PUT    /api/memories/docs/{layer}/{key}           # 整文档覆盖（编辑器保存）
DELETE /api/memories/entries/{entry_id}           # 删除单条记忆
GET    /api/memories/search?q=xxx&limit=10        # 检索
GET    /api/memories/sessions                     # 会话摘要列表
GET    /api/memories/compiled                     # 当前编译注入内容（调试用）
POST   /api/memories/consolidate                  # { mode, layer, key } 触发整理
WS     /api/events                                # memory.updated / created / deleted
```

事件：

- `memory.updated`：某文档被修改（刷新对应页）
- `memory.entry.deleted`：单条被删
- `memory.created`：新记忆沉淀（挂件可给「记下了」的轻反馈）

## 9. V1 边界

V1 必做：

- L1 trace（5 个 surface）
- 会话摘要（session）
- L2/L3 沉淀：用户偏好、项目进度、稳定事实
- persona 独立档案 + 与用户记忆隔离
- FTS 检索（ngram）
- 注入组装（recall_context + compiled 落盘）
- 记忆页查看 / 编辑 / 删除

V1 可选：

- 对话中「需要记住吗？」的显式确认沉淀
- 挂件「记忆成功」轻反馈动画

V1 后：

- consolidator 完整模式（audit / dedup / dream 反思）
- 多角色记忆隔离（partner 空间 per character）
- 向量检索 / Obsidian RAG
- 跨设备同步与云记忆

## 10. 与现有原型的关系

- `src/memory/store.py`、`src/memory/retriever.py` 是早期原型，用于验证思路。
- 正式实现以本文档为规格在 `services/ai-service/memory/` 落地，落地时替换原型，不复制原型接口。
- 对外统一入口为 `MemoryService` 门面，前端与对话链路只依赖它，不感知内部文件布局。
