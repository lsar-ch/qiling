# DeskMate 挂件状态机

## 1. 目标

挂件状态机负责把程序运行状态变成可见的角色反馈。

原则是：

- 状态由程序驱动
- 动画只是状态的视觉表现
- LLM 不直接控制动画

## 2. 状态列表

第一版建议包含以下状态：

- `idle`
- `listening`
- `thinking`
- `speaking`
- `executing`
- `awaiting_approval`
- `completed`
- `interrupted`

## 3. 状态来源

状态变化来自这些事件：

- 用户开始说话
- VAD 检测到输入
- STT 完成
- LLM 开始生成
- 后台 Agent 开始执行
- 任务需要确认
- 用户打断语音
- 任务成功或失败

## 4. 动画映射

### 4.1 `idle`

- 轻微呼吸
- 眼睛眨动
- 偶尔小动作

### 4.2 `listening`

- 身体朝向用户
- 轻微脉冲
- 倾听动画

### 4.3 `thinking`

- 轻微旋转或停顿
- 思考提示

### 4.4 `speaking`

- 口型或波纹
- 轻微节奏变化

### 4.5 `executing`

- 任务中提示
- 进度感动画

### 4.6 `awaiting_approval`

- 疑问或等待动作
- 明确提示用户确认

### 4.7 `completed`

- 成功反馈
- 短暂庆祝后回到空闲

### 4.8 `interrupted`

- 立即停播
- 切回 listening

## 4.9 任务主动播报（Step 9 新增）

任务执行过程中，挂件会主动显示进度气泡和结果摘要：

- `task.started`：显示"任务开始执行…"气泡（3 秒）
- `task.progress`：显示进度摘要气泡（2.4 秒，≤60 字截断）
- `task.approval_required`：显示"需要确认：xxx"气泡（8 秒），挂件状态切到 `awaiting_approval`
- `task.approval_reminder`：等待授权超过 30 秒未响应，显示提醒气泡（6 秒）并触发外发光脉冲动画
- `task.completed`：显示"✓ 结果摘要"气泡（4 秒）
- `task.failed`：显示"✗ 错误信息"气泡（4 秒）
- `task.cancelled`：显示"已取消"气泡（3 秒）

所有气泡内容由后端 `runtime.py` 生成 `bubble` 字段，前端挂件直接展示。
`task.approval_reminder` 由 30 秒计时器自动触发，授权或取消后计时器自动清除。

## 5. 设计参考

可参考的模式包括：

- Qwen-Audio-Agent 的语音状态切换
- 桌宠类项目的情绪反馈
- DeepTutor 那种“运行态可视化”的工作方式

## 6. 第一版要求

第一版先做到：

- 状态切换清晰
- 动画简单但稳定
- 和语音链路、任务分流、后台 Agent 严格联动

