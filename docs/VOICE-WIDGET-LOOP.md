# 栖灵 语音与挂件联动方案

## 1. 目标

把语音链路和挂件状态机打通，让用户能直观看到系统当前在听、在想、在说、在执行、在等待确认。

这部分的核心不是动画本身，而是“语音事件必须驱动挂件状态”。

## 2. 联动原则

- 语音输入驱动 `listening`
- STT 完成驱动 `thinking`
- LLM 生成驱动 `speaking` 或 `executing`
- 复杂任务驱动 `executing`
- 需要授权驱动 `awaiting_approval`
- 用户插话驱动 `interrupted`
- 任务完成驱动 `completed`

## 3. 标准流程

```text
用户开口
  → 挂件进入 listening
  → VAD 检测持续输入
  → STT 转写完成
  → 挂件进入 thinking
  → 意图判断
      → 简单问答：直接生成回复
      → 复杂任务：交给后台 Agent
  → 挂件进入 speaking / executing
  → TTS 播报或任务执行
  → 结束后进入 completed
  → 回到 idle
```

## 4. Barge-in 联动

全双工基础要从 barge-in 开始做。

规则：

- 挂件处于 `speaking` 时仍保持麦克风监听
- 一旦 VAD 检测到有效新输入
- 立即中断当前播报
- 挂件切回 `listening`

这意味着挂件状态机不能和 TTS 播报绑定死，必须支持实时中断。

## 5. 简单问答路径

简单问答应尽量短路处理：

1. 用户输入
2. 挂件进入 `listening`
3. STT 完成后进入 `thinking`
4. LLM 直接生成短回复
5. 挂件进入 `speaking`
6. TTS 播报完成
7. 如果回复短，可只在气泡显示，不必展开主界面

## 6. 复杂任务路径

复杂任务要把状态显式拉长，让用户知道系统在做事：

1. 用户输入
2. 挂件进入 `listening`
3. STT 完成后进入 `thinking`
4. 任务被路由到后台 Agent
5. 挂件进入 `executing`
6. 如需确认，切到 `awaiting_approval`
7. 任务完成后进入 `completed`
8. 结果回到主界面和挂件

## 7. 状态与视觉反馈

状态切换时，挂件视觉反馈应尽量短促、明确。

建议：

- `listening`：更明显的倾听动作
- `thinking`：停顿感、轻微循环动画
- `speaking`：节奏感动画
- `executing`：任务中标识
- `awaiting_approval`：明显疑问提示
- `completed`：短反馈后回归 `idle`

## 8. 语音与界面的分工

- 语音负责快速交互
- 挂件负责即时状态反馈
- 主界面负责长文本、任务详情、确认和回放

## 9. 第一版要求

第一版语音与挂件联动至少要做到：

- 语音输入能让挂件进入正确状态
- TTS 播报期间能被打断
- 复杂任务执行时挂件有清晰反馈
- 任务结束后状态能回到空闲

