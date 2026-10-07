# 栖灵 语音激活方案（常开 / 静默 / 唤醒）

> 状态：2026-09-04 设计定稿，Step 4 语音闭环验收后落地。
> 需求来源（用户）：麦克风默认常开，系统自动判断主人说完并执行反馈；
> 主人说「暂时静默」后不做任何回应；说唤醒词（如「你好，千问」）后精灵主动回复。

## 1. 结论

- 常开监听 = 前端能量 VAD（自动断句）+ 每句 STT，先本地跑通；
  后续要「秒级唤醒」再接入本地唤醒引擎（openWakeWord / Porcupine），接口位预留。
- **唤醒词 = 你好/嗨 + 角色名**（如「你好，千问」），角色名来自角色卡（persona）且可自定义；
  角色卡实现前，先在 `config/settings.yaml voice.activation.persona_name` 配置默认值。
- 静默词为自然短语词表（「暂时静默 / 先别说话 / 安静一下…」），同样可自定义。
- 静默态下仅唤醒词能打断；其余语音一律不回应、不打扰。

## 2. 三层状态

| 状态 | 含义 | 行为 |
|---|---|---|
| `listening`（默认常开） | 随时可对话 | VAD 断句 → STT → 意图判断 → 正常对话/执行 |
| `sleeping` | 暂时静默 | VAD 仍监听，但识别文本只做唤醒匹配；非唤醒词零回应 |
| `wake` 事件 | 被唤醒 | 精灵主动回应一句并回到 `listening` |

判定链（识别文本 → 意图路由，不先进 LLM）：

```text
识别文本
  ├─ 匹配静默词 → 静默指令：回应一句，切 sleeping
  ├─ 匹配唤醒词（前缀 + 角色名）→ 唤醒：回应一句，切 listening
  └─ 其他 → listening 态正常对话 / sleeping 态忽略
```

## 3. 配置位

`config/settings.yaml voice.activation`（角色卡实现后由 persona 覆盖）：

- `persona_name`：默认「千问」（唤醒词的一部分，可自定义）
- `wake_prefixes`：["你好", "嗨"]（前缀列表，匹配其一即算唤醒词）
- `sleep_phrases`：静默指令词表
- `default_state`：`listening`

文本匹配前先归一化：去空格与标点、全角转半角、小写。

## 4. 接口

- `GET /api/voice/status`：追加 `activation` 段（角色名/默认状态/可用开关）。
- `POST /api/voice/intent {text}` → `{intent: chat|wake|sleep, reply?, persona_name}`。
  识别文本后先调本接口分流，命中才带状态，普通文本直接走 `/api/chat/stream`。

## 5. 前端常开监听（V1）

- 页面打开即请求麦克风（授权一次），常开监听开启后不随 push-to-talk 关闭。
- VAD 用能量阈值自动断句：speech_start（RMS 超过起音阈值持续 N 帧）、
  speech_end（低于静音阈值持续 ~600ms）、最长单句上限 ~12s 自动切段。
- 断句得到 WAV(16k mono) → `recognizeSpeech` → `voice/intent` 分流。
- 播报期间 VAD 继续工作：检测到新人声立即打断（barge-in）。
- 提供「监听开关」按钮：默认开；关闭后回到手动按键语音，麦克风释放。
- 静默态界面显示状态标签；麦克风常开时界面有指示灯提示。
- TTS 播放走与常开监听**共用的 AudioContext**（WebAudio bufferSource），
  规避浏览器自动播放限制并让 AEC 参考更完整（对齐 Qwen-Audio-Agent 实现）；
  播报期间不自动打断，抢话用「⏹ 停止」按钮（全双工前不引入自断风险）。

## 6. 隐私与体验

- 常开 = 麦克风持续占用，界面常显监听指示灯与关闭入口。
- 静默不是「关麦」，是「不回应」；真正关麦请用界面开关。
- VAD 阈值需真机校准：默认参数在 ChatPage 顶部常量，便于试听后调整。

## 7. 参考：Qwen-Audio-Agent 为什么「不重复」（2026-09-04 源码核实）

本地源码：`/Users/lxb/Desktop/qwen-audio-agent-main.zip`（web/src/useRealtimeVoice.js、
server/src/voice/realtime-gateway.mjs）。

- 客户端：麦克风常开、**播报时不关麦**、持续把 PCM 推上实时通道；
  采集约束与 栖灵 相同（echoCancellation + noiseSuppression + autoGainControl）。
- 客户端播放与采集**共用同一个 AudioContext**（`createBufferSource → context.destination`），
  比独立 `new Audio()` 更有利于浏览器 AEC 取参考信号。
- 服务端：回合/话语权状态机（voice.state idle/listening、ownership、interrupt）。
  模型播报期间，输入音频只用于「用户抢话打断」，**不会另起一轮把回声变成新指令**——
  这本质上是「说话期间输入不作为新对话」的门控，与 栖灵 已上线的
  「播报窗口丢弃回采段 + 800ms 打断阈值」同一思路，只是他们下沉到了服务端回合层。
- 他们的「休眠/唤醒」也在服务端（SleepController + sherpa-onnx 本地唤醒词，
  休眠提示文案见 realtime-gateway），印证 栖灵 静默/唤醒思路可后续下沉后端。
- 启示：V1 若 AEC 仍不理想，第一步改「播放走采集同一 AudioContext」对齐其实现；
  根治双工抢话要靠实时语音通道 + 服务端回合状态机（Step 8 全双工路线）。
