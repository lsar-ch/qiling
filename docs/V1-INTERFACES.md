# DeskMate V1 核心数据结构与模块接口

## 1. 设计目标

V1 接口要满足四个要求：

- 模块之间低耦合
- 语音、模型、TTS、Agent 可以替换
- 挂件和浏览器主界面共享同一套状态
- 后续可以扩展云端服务和多 Agent

## 2. 总体数据流

```text
语音/文字输入
  → Conversation Gateway
  → Task Router
  → Answer Service / Tool Executor / Agent Router
  → Event Bus
  → 挂件 + 浏览器主界面 + Memory
```

## 3. 统一事件结构

所有模块之间通过统一事件传递状态：

```json
{
  "event_id": "evt_01",
  "event_type": "task.status",
  "timestamp": "2026-09-03T12:00:00Z",
  "conversation_id": "conv_01",
  "task_id": "task_01",
  "source": "agent_router",
  "payload": {}
}
```

建议事件类型：

- `conversation.input`
- `conversation.transcript`
- `conversation.response`
- `speech.started`
- `speech.stopped`
- `speech.interrupted`
- `task.classified`
- `task.started`
- `task.progress`
- `task.approval_required`
- `task.completed`
- `task.failed`
- `memory.created`
- `memory.updated`

## 4. 语音接口

### 4.1 STT

```python
class SpeechRecognizer:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def transcribe(self, audio: bytes) -> str: ...
    def on_speech_start(self, callback) -> None: ...
    def on_speech_end(self, callback) -> None: ...
```

### 4.2 TTS

TTS 对供应商开放，但系统统一输出语音表现参数：

```python
class SpeechSynthesizer:
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        tone: str = "neutral",
        emotion: str | None = None,
        speed: float = 1.0,
        ssml: str | None = None,
    ) -> bytes: ...

    async def play(self, audio: bytes) -> None: ...
    async def stop(self) -> None: ...
```

第一版至少支持：

- `text`
- `voice`
- `speed`
- `stop`
- 播报中断

`tone / emotion / ssml` 先保留接口，不要求所有供应商实现。

### 4.3 实时语音扩展

后续可增加：

```python
class RealtimeSpeechProvider:
    async def connect(self) -> None: ...
    async def send_audio(self, chunk: bytes) -> None: ...
    async def receive_events(self): ...
    async def interrupt(self) -> None: ...
```

这样 V1 的接口不会绑定某一个 STT/TTS 供应商。

## 5. 对话与模型接口

```python
class LLMProvider:
    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        response_format: str = "text",
    ): ...
```

模型配置至少包括：

- 提供商
- API 地址
- API 密钥
- 模型名称
- 温度
- 最大输出长度
- 是否流式

## 6. 任务结构

```json
{
  "task_id": "task_01",
  "conversation_id": "conv_01",
  "input": "帮我检查这个项目的代码结构",
  "category": "delegate_backend",
  "risk_level": "low",
  "complexity": "high",
  "estimated_duration": "long",
  "required_approval": false,
  "preferred_executor": "codex",
  "status": "queued"
}
```

分类值：

- `answer`
- `execute_frontend`
- `delegate_backend`
- `request_approval`

风险值：

- `low`
- `medium`
- `high`

## 7. 挂件状态接口

```python
class WidgetStateController:
    def set_state(
        self,
        state: str,
        task_id: str | None = None,
        message: str | None = None,
    ) -> None: ...
```

状态变化必须来自系统事件：

```text
speech.started      → listening
conversation.input  → thinking
conversation.answer → speaking
task.started        → executing
task.approval_required → awaiting_approval
speech.interrupted  → interrupted → listening
task.completed      → completed → idle
task.failed         → completed(error) → idle
```

## 8. 记忆接口

记忆采用「DeepTutor 档案层 + HanaAgent 注入层」的合流设计，
详细规格（数据模型、目录布局、内部模块、注入组装、HTTP/WS API）见 [V1 记忆模块](./V1-MEMORY.md)。

核心门面：

```python
class MemoryService:
    # L1 留痕
    async def record_event(self, surface: str, kind: str, payload: dict,
                           *, session_id: str | None = None,
                           turn_id: str | None = None) -> str: ...
    # 会话摘要
    async def write_session_summary(self, summary: dict) -> None: ...
    # L2/L3 文档与条目管理
    async def read_doc(self, layer: str, key: str) -> dict: ...
    async def overwrite_doc(self, layer: str, key: str, md: str) -> None: ...
    async def upsert_entry(self, layer: str, key: str, section: str,
                           text: str, refs: list[str]) -> str: ...
    async def delete_entry(self, entry_id: str) -> bool: ...
    async def overview(self) -> list[dict]: ...
    # 注入与检索
    async def recall_context(self, *, budget_chars: int = 4000) -> dict: ...
    async def search(self, query: str, limit: int = 10) -> list[dict]: ...
    # Persona（角色档案，与用户记忆分离）
    async def get_persona(self, name: str) -> dict | None: ...
    async def save_persona(self, name: str, md: str) -> None: ...
```

分层与存储：

- L1：`trace/<surface>/<date>.jsonl`，append-only，surface = conversation / task / kb / project / partner
- L2：每个 surface 一份 Markdown 场景事实（`L2/<surface>.md`）
- L3：四个画像 slot（`L3/<slot>.md`），slot = profile / preferences / progress / recent
- persona：`persona/<character>.md`，角色档案独立，不混入用户画像
- Markdown 为真相源，SQLite FTS 只做检索索引

记忆条目格式带溯源引用与编辑锚点：

```markdown
- 界面使用中文 [^1] <!--m_xxx-->

[^1]: conversation:evt_xxx
```

## 9. Agent Router 接口

```python
class AgentAdapter:
    name: str

    async def detect(self) -> dict: ...
    async def connect(self) -> None: ...
    async def run(self, task: dict): ...
    async def cancel(self, task_id: str) -> None: ...
    async def approve(self, task_id: str, approval: dict) -> None: ...
```

路由器负责：

- 选择执行器
- 启动任务
- 接收进度
- 处理确认
- 取消任务
- 统一结果格式

## 10. 浏览器主界面通信

浏览器页面和本地服务之间建议使用：

- HTTP：查询和提交命令
- WebSocket：实时状态
- SSE：只读事件流的备选方案

至少需要这些接口：

```text
GET  /api/health
GET  /api/session
POST /api/conversations
POST /api/tasks
GET  /api/tasks/:id
POST /api/tasks/:id/approval
POST /api/tasks/:id/cancel
GET    /api/memories/overview
GET    /api/memories/docs/{layer}/{key}
PUT    /api/memories/docs/{layer}/{key}
DELETE /api/memories/entries/{entry_id}
GET    /api/memories/search?q=xxx&limit=10
GET    /api/memories/sessions
GET    /api/memories/compiled
POST   /api/memories/consolidate
WS     /api/events
```

## 11. 授权接口

```json
{
  "approval_id": "approval_01",
  "task_id": "task_01",
  "action": "delete_files",
  "description": "删除项目中的临时文件",
  "risk_level": "high",
  "expires_at": "2026-09-03T12:05:00Z",
  "status": "pending"
}
```

授权结果：

- `approved`
- `rejected`
- `expired`

## 12. V1 实现优先级

1. 统一事件结构
2. 对话 Gateway
3. Task Router
4. Widget State Controller
5. LLM Provider
6. STT / TTS Provider
7. Memory Service
8. Codex Agent Adapter
9. 浏览器 API 和 WebSocket

