# 统一表现事件流 Schema

> 日期：2026-09-10 ｜ 状态：Schema 设计完成，待实现
> 关联：`docs/CHARACTER-STAGE-DESIGN-2026-09-10.md` §4 排期

## 1. 设计目标

把现有散落在各处的表现相关数据（状态、气泡、主题色、动画参数）收敛为统一载荷，使挂件渲染侧只需要消费单一事件流即可驱动全部视觉表现。

**原则**：
- 状态由程序事件驱动，不由 LLM 注入
- 情绪从事件上下文推导，不解析聊天内容
- 主题/动画参数来自角色卡 `presentation` 配置，角色切换时下发
- 向后兼容现有 `EventEnvelope` / `WsMessage` 结构

## 2. 两层载荷设计

### 2.1 ExpressionEvent（事件级，高频）

每个程序事件发生时广播。轻量，只含本次变化的动态字段。

```typescript
// ExpressionEvent — 由后端 state_mapper 从 EventEnvelope 派生
interface ExpressionEvent {
  // 继承自现有 WidgetStatusReport
  state: WidgetState;
  task_id: string | null;
  timestamp: string;

  // 新增：从事件上下文推导的情绪标签
  emotion: ExpressionEmotion;

  // 新增：可选气泡（由 runtime 生成）
  bubble?: {
    text: string;           // 气泡文字，≤120 字
    duration_ms: number;    // 显示时长 ms
    style: BubbleStyle;     // "info" | "success" | "warning" | "error"
  };
}
```

### 2.2 PersonaPresentation（角色级，低频）

角色切换或首次连接时下发。含主题色和动画参数，挂件缓存后跨事件复用。

```typescript
// PersonaPresentation — 来自角色卡 presentation 配置块
interface PersonaPresentation {
  persona_id: string;
  persona_name: string;

  // 主题色
  theme: {
    primary: string;   // 主色 #RRGGBB，角色卡/气泡边框/状态指示
    aura: string;      // 光环色 #RRGGBB，激活光圈
    accent: string;    // 强调色 #RRGGBB，按钮/高亮
  };

  // 动画参数（来自 presentation.motions）
  animations: {
    breath_rate: number;              // 呼吸速率倍率，默认 1.0
    blink_interval_ms: number;        // 眨眼间隔 ms，默认 4000
    idle_action_interval_ms: number;  // 空闲小动作间隔 ms，默认 8000
    transition_ms: number;            // 状态过渡时长 ms，默认 300
  };

  // 可选：特效开关（来自 presentation.fx）
  fx?: {
    thinking_bubble?: boolean;  // 思考气泡特效
    music_note?: boolean;       // 音符特效（speaking 态）
    success_sparkle?: boolean;  // 完成闪光特效
  };
}
```

## 3. 情绪推导规则

情绪由 `state_mapper` 从事件类型推导，**不由 LLM 注入**。

```typescript
type ExpressionEmotion =
  | "neutral"     // 空闲/默认
  | "attentive"   // 聆听中
  | "thinking"    // 思考中
  | "confused"    // 需要确认
  | "success"     // 任务成功/对话完成
  | "error";      // 任务失败/错误

// 推导映射表
const EVENT_TO_EMOTION: Record<string, ExpressionEmotion> = {
  "speech.started":            "attentive",
  "conversation.input":        "thinking",
  "conversation.transcript":   "thinking",
  "conversation.response":     "neutral",      // 说话态默认中性
  "conversation.completed":    "success",
  "task.started":              "neutral",
  "task.progress":             "neutral",
  "task.approval_required":    "confused",
  "task.completed":            "success",
  "task.failed":               "error",
  "task.cancelled":            "neutral",
  "task.timed_out":            "error",
  "speech.interrupted":        "neutral",
  "speech.stopped":            "neutral",
};
```

情绪到挂件视觉的映射：

| 情绪 | 眼睛 | 嘴 | 光环 | 附加 |
|---|---|---|---|---|
| neutral | 正常眨眼 | 闭合 | 无/弱 | — |
| attentive | 睁大/微亮 | 微张 | 柔和脉冲 | 耳朵/头朝向（动物） |
| thinking | 半闭 | 抿嘴 | 旋转/省略号 | 思考气泡 |
| confused | 一侧缩小 | ? 型微张 | 黄色抖动 | 问号 |
| success | 弯月笑眼 | 微笑 | 绿色闪 | 闪光粒子 |
| error | X 眼/垂眼 | 下垂 | 红色闪 | 简短红色脉冲 |

## 4. WebSocket 协议

### 4.1 现有协议（v0）

```json
// WS /api/events 消息
{
  "event_id": "evt_abc123",
  "event_type": "task.completed",
  "timestamp": "2026-09-10T...",
  "conversation_id": null,
  "task_id": "task_xyz",
  "source": "task",
  "payload": { "message": "任务完成" }
}
```

### 4.2 扩展协议（v1 本设计）

在现有消息基础上新增 `expression` 字段，并新增两种顶层消息类型：

```json
// 类型 1：表现事件（高频，随每个程序事件广播）
{
  "event_id": "evt_abc123",
  "event_type": "task.completed",
  "timestamp": "2026-09-10T...",
  "task_id": "task_xyz",
  "source": "task",
  "payload": {},
  "expression": {
    "state": "completed",
    "emotion": "success",
    "bubble": {
      "text": "✓ 代码审查完成，3 个文件通过",
      "duration_ms": 4000,
      "style": "success"
    }
  }
}

// 类型 2：角色呈现（低频，角色切换或首次连接时）
{
  "event_id": "evt_def456",
  "event_type": "persona.presentation",
  "timestamp": "2026-09-10T...",
  "source": "system",
  "payload": {},
  "presentation": {
    "persona_id": "assistant_lady",
    "persona_name": "小助手",
    "theme": {
      "primary": "#6366F1",
      "aura": "#818CF8",
      "accent": "#C4B5FD"
    },
    "animations": {
      "breath_rate": 1.0,
      "blink_interval_ms": 4000,
      "idle_action_interval_ms": 8000,
      "transition_ms": 300
    },
    "fx": {
      "thinking_bubble": true,
      "music_note": false,
      "success_sparkle": true
    }
  }
}
```

### 4.3 前端消费（Widget.tsx 适配）

```typescript
// 现有 connectEvents → onMessage 中新增处理
connectEvents(wsUrl, (msg) => {
  // 已有：状态更新
  if (msg.event_type) {
    const state = eventToState(msg.event_type);
    if (state) setState(state);
  }

  // 新增：从 expression 字段取情绪/气泡
  const expr = msg.expression as ExpressionEvent | undefined;
  if (expr) {
    if (expr.emotion) setEmotion(expr.emotion);    // → CSS 类切换
    if (expr.bubble) showBubble(expr.bubble);       // → 气泡渲染
  }

  // 新增：角色呈现
  if (msg.event_type === "persona.presentation" && msg.presentation) {
    applyPresentation(msg.presentation);  // → 更新 CSS 变量/动画参数
  }
}, onState);
```

## 5. 后端改动清单

### 5.1 contracts 包（`packages/contracts/py/deskmate_contracts/`）

- **`widget.py`**：新增 `ExpressionEmotion`、`BubbleStyle`、`ExpressionEvent`、`PersonaPresentation`
- **`events.py`**：`EventEnvelope` 新增可选字段 `expression`、`presentation`

### 5.2 ai-service（`services/ai-service/app/core/`）

- **`state_mapper.py`**：新增 `emotion_for()` 推导函数；`WidgetStateRegistry.update()` 输出 `ExpressionEvent` 而非仅 `WidgetStatusReport`
- **`bus.py`**：`EventHub.publish()` 自动附加 `expression`（调用 state_mapper）
- **新增 `presentation_bridge.py`**：角色切换时从 persona config 读取 `presentation` 块，生成 `PersonaPresentation` 事件广播

### 5.3 前端（`apps/desktop/src/`）

- **`api.ts`**：`WsMessage` 增加 `expression?`、`presentation?`字段
- **`Widget.tsx`**：新增 `emotion` 状态；`applyPresentation()` 更新 CSS 变量；气泡渲染接入 `expression.bubble`
- **`widget.css`**：新增 `.emotion-*` CSS 类（眼/嘴/光环变体）

## 6. 向后兼容

- 前端对 `expression` 字段做可选处理：不存在时回退到现有行为（仅状态切换）
- 后端 `expression` 字段在老客户端被忽略（JSON 多余字段容错）
- `eventToState()` 函数保持不变，expr.state 与现有 event_type→state 映射一致

## 7. 与 layers.json 的关系

`PersonaPresentation` 不包含资产引用（部件路径/锚点）。资产配置走 `layers.json`（或角色卡的 `presentation.parts`），由挂件在角色切换时单独加载，不走事件流。

分离原因：
- `PersonaPresentation`：轻量、高频下发（每次连接/切换）
- `layers.json`：重量、低频加载（资产路径/锚点/帧映射），挂件本地缓存
