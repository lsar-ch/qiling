# 主动性系统设计（L0–L4）— 2026-10-26

> **状态：草案 · 待商议 · 未验证 · 未实施。**
> 本文只是提案，不代表已定方案，也未改动任何代码。第十一节的条目需要逐条验证后才能进入
> `V0.2-PLAN` 排期；在此之前不得据此实施。

> 一句话：把「到点必说」的定时器，升级为「先说该不该说」的仲裁器。
>
> 本文只谈机制，不涉角色美术。角色侧接口见 `WIDGET-STATE-MACHINE.md` 与
> `EXPRESSION-EVENT-SCHEMA.md`；记忆侧见 `V1-MEMORY.md`。

## 1. 为什么要重做这一层

现有主动性由三个互不相识的引擎承担，各自直接往事件总线 publish：

| 实现位置 | 触发条件 | 输出 | 局限 |
| --- | --- | --- | --- |
| `core/reminders.py` | 用户明说「提醒我 X 点」 | `reminder.triggered` | 只认显式委托，且到点必说 |
| `core/wellness.py` | idle ≥ 40min / 连续工作 ≥ 90min | `reminder.triggered` | 话术硬编码，只有 per-kind 冷却 |
| `agents/runtime.py::_sweep_stale_runs` | run 处于 queued/running 且 15min 无更新 | `task.stale` | 只管「正在跑的任务」，管不到「没开始的任务」 |
| `agents/runtime.py::_advance_project_nodes` | 节点完成/失败 | `project.milestone` / `project.blocked` | 同上 |

四个来源加起来，缺的不是触发器，是**判断**：

| 缺口 | 具体表现 | 后果 |
| --- | --- | --- |
| G1 无全局打扰预算 | 三个引擎各算各的冷却，可同时命中 | 连珠炮，用户第一反应是关权限 |
| G2 无场景感知 | 不知道用户是否在全屏、是否在说话、是否凌晨 | 半夜推「坐得有点久」是灾难 |
| G3 无反馈闭环 | 推完即结束，无视与照做无差别 | 无法学习，也无法评测 |
| G4 无升级/退场策略 | 同一件事要么反复说，要么说一次就消失 | 要么烦，要么废 |
| G5 无「承诺后停滞」检测 | 所有 stale 判定都基于 run，用户口头承诺的事项没有 run | **最大的价值缺口** |
| G6 话术无层次 | wellness 是写死的字符串，reminder 是 `⏰ 提醒：{text}` 拼接 | 角色表现力被浪费 |
| G7 无最小下一步 | 只有气泡 + TTS，用户要行动得自己找入口 | 主动性无法转化为完成率 |

G5 单独说明：`task.stale` 检测的是「Agent 正在跑但卡住了」，与「你说要做但三天没动静」
是两件事。后者没有 run、没有 task，当前架构里任何 sweeper 都扫不到它——而这恰是
Codex 一类工具永远不会覆盖的部分，也是差异化最集中的地方。

## 2. 三条设计原则

**原则一：价值在「不说」，不在「说」。**
提醒类产品的失败几乎总是打扰过载，而非漏报。所以系统的核心组件是仲裁器，不是触发器。
每一次静默都要被记录并可解释，但不必让用户看见。

**原则二：被抑制的提醒不丢弃，合并后补说。**
否决不等于作废。进 defer 队列，等窗口打开时一次性说清。用户宁可听一次「有三件事」，
也不要被敲三次。

**原则三：同一件事最多说三次，第四次永久退场。**
第 3 次必须改变策略：不再重复内容，而是问「还做吗」，并给出「删掉」这个选项。
这是产品的品格边界，也是唯一能防止自己变成骚扰源的结构性约束。

## 3. 五层架构

```
L0 触发  →  L1 仲裁（唯一决策点）  →  L2 表达  →  L3 闭环  →  L4 升级/退场
             ↑____________________反馈回流____________________|
```

### L0 触发器层：五种来源

| source | 语义 | 判据 | 现状 |
| --- | --- | --- | --- |
| `delegated` | 用户显式委托 | 已有 `parse_reminder_message` | ✅ 已实现 |
| `deadline` | 有明确截止时间 | `remind_at` 临近 | ✅ 部分 |
| `dormant` | 承诺了但无执行痕迹 | 意图抽取 + N 天无进展 | ❌ 新增 |
| `rhythm` | 周期性节律事项 | `repeat` 命中（缴费/体检/证件） | ✅ 部分 |
| `runtime` | 任务运行期停滞/阻塞 | run 无更新、节点失败 | ✅ 已实现 |

L0 只负责**产生候选**（candidate），不做任何播报决定。所有候选统一交给 L1。

`dormant` 的抽取策略（关键，也最容易做错）：

1. 从对话/记忆中识别意图信号：「我要做 X」「下周弄 X」「得抽空 X」
2. **必须经用户确认一次**（「这件事记一下？到月底提醒你」），确认后建 `DormantWatch`
3. 未确认的只留在记忆里，不进 watch——否则「随便说说」会变成骚扰素材
4. N 默认 3 天无关联活动即视为停滞，可配置

第 2 步不可省。误判的代价远大于漏判：漏判只是少提醒一次，误判会让用户不信任整个系统。

### L1 仲裁层：唯一决策点（核心）

新增 `services/ai-service/app/core/arbiter.py`。所有引擎不再直接 `hub.publish`，改为
`await arbiter.submit(candidate)`。

**第一步：硬门（一票否决，不可被分数覆盖）**

| 条件 | 结果 | 例外 |
| --- | --- | --- |
| 正在说话 / 聆听 / TTS 播放中 | 抑制 `busy_speaking` | 无 |
| 全屏应用占用（全屏窗口/演示/游戏） | 抑制 `fullscreen` | `importance=high` |
| 23:00–07:00 | 抑制 `night` | `importance=high` 且 deadline 在 12h 内 |
| 今日已说 ≥ 预算（默认 3，首周 5） | 抑制 `budget` | `importance=high` 且未过期 |
| 同一实体 24h 内已说过 | 抑制 `dedupe` | 无 |
| 该类别疲劳值 ≥ 0.7 | 抑制 `fatigue` | 无 |

**第二步：打分（仅用于排序与合并，不用于决定是否说）**

```
score = importance_w × urgency × timing_fit
```

`urgency` 是分段函数，不是线性——**过期越久越不该提**：

| 距截止 | urgency |
| --- | --- |
| > 7 天 | 0.3（太早，说了也不动） |
| 3–7 天 | 0.5 |
| 1–3 天 | 0.8 |
| < 24h | 1.0 |
| 已过期 1–3 天 | 0.9（还有救） |
| 已过期 > 7 天 | 0.2（应转而建议放弃，而非催促） |

多数提醒系统会对过期任务持续施压，这是最招人烦的行为模式。本设计明确反转：
**超过 7 天的过期项不再播报，改为在第 3 次升级时提供「删掉」选项。**

**第三步：合并与补说**

被 `budget` / `night` / `fullscreen` 抑制的候选进入 defer 队列。窗口打开时：

- 队列 ≥ 2 条 → 先一句总述（「有三件事想跟你说」），再逐条，间隔 ≥ 8s
- 队列 = 1 条 → 直接说
- 队列项超过 7 天未补说 → 自动降级为 `dormant` 重新评估，或直接退场

**第四步：记账**

每次仲裁（无论说或不说）都写一条 `Decision` 到 `InterruptionLedger`。
这是唯一的数据源，既服务预算计数，也服务第 8 节的评测。

### L2 表达层：三档语气

| tone | 触发条件 | 气泡 | 语音 | 角色表演 |
| --- | --- | --- | --- | --- |
| `hint` | importance=low 或 escalation=1 | 单行，8s 淡出 | 无 | 侧头一瞥，不靠近 |
| `suggest` | normal 且 score 中等 | 一行 + 一个动作入口 | 短句 | 走近半步 / 抬头 |
| `urge` | high 或 urgency≥0.9 或 escalation=2 | 说清后果 + 两个按钮 | 带情绪参数 | 站到视野中央挥手 |

表情与动作不复用 `state_mapper` 的状态机——提醒不进状态机（现有挂件已如此处理），
走 `motion_overrides`。这样提醒不会污染「执行中/聆听中」等主状态。

### L3 闭环层：四种结果

| 结果 | 记录 | 对系统的影响 |
| --- | --- | --- |
| `done` 做了 | outcome=done | 该类别 fatigue −0.5；importance 权重微升 |
| `snooze` 稍后 | outcome=snooze + 新时间 | 最多 3 次；第 3 次必须提议放弃 |
| `ignored` 无视（8s 无交互） | outcome=ignored | fatigue +0.3；escalation +1 |
| `muted` 明确关闭 | outcome=muted | 该类别静默 7 天，到期只问一次「要恢复吗」 |

`ignored` 的判定要宽容：8 秒内无交互才算，且不因一次忽略就降频——三次累积才生效。

### L4 升级与退场

同一提醒（同 `reminder_id` / 同 `watch_id`）的生命周期：

| 次数 | 行为 |
| --- | --- |
| 第 1 次 | 气泡，无语音 |
| 第 2 次 | 气泡 + 语音，间隔 ≥ 24h |
| 第 3 次 | 换策略：「这件事你一直没动，是不是不打算做了？」+ 按钮「继续放着 / 删掉」 |
| ≥ 4 次 | **永久退场**，除非用户主动问起 |

## 4. 数据模型

### 4.1 扩展 `Reminder`（`packages/contracts/py/qiling_contracts/reminder.py`）

新字段全部带默认值，保证旧 JSON 可反序列化（当前 `extra="forbid"` 不受影响）：

```python
ReminderSource = Literal["delegated", "deadline", "dormant", "rhythm", "runtime"]
ReminderImportance = Literal["low", "normal", "high"]
ReminderOutcome = Literal["done", "snooze", "ignored", "muted"]

# 追加到 Reminder
source: ReminderSource = "delegated"
importance: ReminderImportance = "normal"
escalation: int = 0                    # 已播报次数
last_spoken_at: str | None = None
outcomes: list[SnoozeRecord] = []      # 追加式，不覆盖
category: str = "general"              # 疲劳统计的粒度
```

### 4.2 新增 `proactive.py` 契约

```python
class Candidate(BaseModel):
    """L0 交给 L1 的候选，不含任何播报决定。"""
    candidate_id: str
    source: ReminderSource
    text: str
    importance: ReminderImportance
    urgency: float                     # 0–1
    deadline_at: str | None
    entity_key: str | None             # 去重键，如 "reminder:rem_xxx"
    category: str
    payload: dict[str, Any] = {}

class Decision(BaseModel):
    """L1 的每一次审判，无论说与不说。"""
    decided_at: str
    candidate_id: str
    verdict: Literal["spoken", "deferred", "dropped"]
    reason: str | None                 # busy_speaking / night / budget / fatigue / ...
    score: float
    tone: Literal["hint", "suggest", "urge"]

class InterruptionLedger(BaseModel):
    """按自然日一份，既是预算计数器也是评测数据源。"""
    date: str
    spoken: int
    deferred: int
    dropped: int
    limit: int = 3
    decisions: list[Decision] = []

class DormantWatch(BaseModel):
    """承诺后停滞：没有 run、没有 task 的「口头任务」。"""
    watch_id: str
    text: str
    promised_at: str
    due_hint: str | None
    entity_key: str
    evidence_ref: str | None           # 指向记忆条目 / 对话 id
    last_activity_at: str
    stale_days: int = 3
    confirmed: bool = False            # 必须用户确认过才参与触发
```

存储位置沿用现有风格：`data/interruption/<YYYY-MM-DD>.json`、`data/dormant/*.json`。

## 5. 事件契约扩展（`qiling_contracts/events.py`）

新增两类事件：

| event_type | 用途 | 挂件是否消费 |
| --- | --- | --- |
| `interruption.suppressed` | 被抑制的提醒（仅日志与后台可见） | 否 |
| `reminder.outcome` | 用户对提醒的反应 | 是（驱动表演） |

`reminder.triggered` 的 payload 增加字段（向后兼容，老挂件忽略即可）：

```jsonc
{
  "kind": "memo",
  "reminder_id": "rem_xxx",
  "text": "...",
  "bubble": "...",
  "speak_text": "...",
  "tone": "suggest",          // 新增
  "merge_count": 1,           // 新增：合并了几条
  "actions": [                // 新增：最小下一步
    { "id": "done", "label": "做了" },
    { "id": "snooze", "label": "晚点", "value": "60m" }
  ]
}
```

`KNOWN_EVENT_TYPES` 与 `packages/contracts/ts/src/events.ts` 需同步，并跑
`./scripts/check.sh` 的契约一致性测试。

## 6. 与角色耦合：闭嘴的表演

这一节是本设计与同类产品最不同的一点，也是最难被复制的部分。

提醒被忽略时，多数产品有两种反应：继续弹（烦），或冷冰冰消失（无感）。本设计要求
角色**表现出识趣**：

| 情境 | 角色行为 | 实现 |
| --- | --- | --- |
| 播报后 8s 无交互 | 低头半步、缩放至 90%、气泡淡出 | `motion_overrides` 播放 `withdraw` |
| 用户点击「做了」 | 轻微点头 | `motion_overrides` 播放 `nod` |
| 用户说「别烦我」 | 退到屏幕角落 + 静默 24h | `muted` + `withdraw_hold` |
| 合并补说 | 先靠近再开口，表示「我要说几件事」 | `approach` 前置 300ms |

这不是美术需求，是**产品语义**：它把「程序提醒」变成「有人分寸」。
功能可以被抄，分寸感不能——因为它要求产品在「少说」这件事上主动让利。

## 7. 落地顺序

### 第一周（最小闭环，不动前端）

1. 新增 `proactive.py` 契约 + `test_proactive.py`
2. 新增 `core/arbiter.py`：只实现硬门 + 每日预算 + Decision 记账
3. `reminders.py` / `wellness.py` 改为 `arbiter.submit()`，删除各自的直发逻辑
4. 新增 `interruption.suppressed` 事件与 `data/interruption/` 落盘
5. 三档语气用纯模板实现（不接 LLM）

验收：连开三个提醒，只有一条播出，另两条进 defer；`ledger` 里三条 Decision 齐全。

### 第二周

6. `core/dormant.py`：意图抽取 + 确认流 + N 天停滞判定
7. `reminder.outcome` 回写 + fatigue 计算
8. 合并播报（`merge_count` + 总述句）
9. 挂件侧：`tone` 样式、`actions` 按钮、`withdraw` / `nod` 表演

### 明确不做

| 不做 | 原因 |
| --- | --- |
| 读窗口标题做 context 触发 | 跨平台权限成本高、误判率高；先用全屏检测这一条粗粒度信号足够 |
| LLM 生成话术 | 先跑量拿数据，模板足够；LLM 会让延迟与成本不可控 |
| 复杂加权打分调参 | 参数全靠猜，前两周只用硬门 + 预算 |
| 把 runtime 的 stale/blocked 也接入 arbiter | 任务执行链改动风险大，等前两级稳定后再接 |

## 8. 评测：只看三个数

| 指标 | 定义 | 目标 |
| --- | --- | --- |
| 主动/照做率 | `outcome=done` / 总播报数 | ≥ 30% |
| 每日打扰数 | `ledger.spoken` 的日均值 | ≤ 3 |
| 静默正确率 | 被抑制项中，用户事后未主动问起的比例 | ≥ 80% |

第一个数对应《形象与任务的权重判断》第八节的自测 A：**主动发起且照做的次数**。
Ledger 让这个数字不再依赖问卷，直接从日志出。

第二个数一旦超 3，说明仲裁层失效，应回查硬门是否漏了条件——而不是去调话术。

第三个数最难测但最重要：它衡量的是「少说」是否说对了。近似做法是观察被抑制项
之后 7 天内是否被用户主动提起；被主动提起 = 抑制错了。

## 9. 风险

| 风险 | 表现 | 缓解 |
| --- | --- | --- |
| 仲裁层过度设计 | 一开始就想调权重，两周都在改参数 | 前两周只用硬门 + 预算，分数仅用于排序 |
| dormant 误判 | 把「随便说说」当承诺，骚扰源头 | 强制二次确认；未确认不进 watch |
| 预算过紧 | 一天 3 次不够，重要事项被压 | 首周默认 5，第二周降 3；`high` 可穿透预算 |
| 抑制逻辑不可解释 | 用户觉得「该说的不说」 | `interruption.suppressed` 落盘 + 设置页可查「今天静默了什么」 |
| 角色表演被当成卖萌 | 用户反感「装可爱」 | 所有动作只表达「收到 / 退让」，不做拟人化撒娇 |

## 10. 与既有文档的关系

- 《形象与任务的权重判断-2026-10-26》第八节：本文是该节「主动性社交许可」的工程落地，
  并为自测 A 提供数据源。
- `WIDGET-STATE-MACHINE.md`：提醒不进状态机，只走 `motion_overrides`，与现有实现一致。
- `V1-INTERFACES.md §7`：事件契约以此文为准做扩展，需同步 TS 镜像。
- `V0.2-PLAN-2026-10-26.md`：本文**暂不进入** v0.2 排期；须待第 11 节逐条验证后方可评估。

## 11. 待商议与待验证（未定项）

以下 12 条是本文最不确定的部分。每条都给出倾向、反方理由与验证方式——**未经验证不得
当作结论使用**。按「先验证 1–3，再验证 4–6，其余最后」的顺序推进。

### 11.1 打扰预算：一天说几次

- **命题**：每日播报上限默认 3 次，首周 5 次。
- **倾向**：3。
- **反方**：忙碌日 3 次不够，重要事项会被压进 defer 队列，反而错过窗口。
- **验证**：跑两周 ledger，统计 defer 队列中被压超过 24h 的项占比；> 30% 说明上限过低。

### 11.2 全屏即静默

- **命题**：检测到全屏应用占用时，非 high 优先级一律静默。
- **倾向**：做，作为唯一的粗粒度场景信号。
- **反方**：全屏写代码、看文档时，恰恰可能是需要提醒的时刻；误判会让用户觉得「该说时不说」。
- **验证**：统计自己在全屏状态下错过的事项比例。若 > 20%，改为「全屏只做 hint 不发声」。

### 11.3 夜间静默时段

- **命题**：23:00–07:00 一律静默（high 且 deadline 在 12h 内可穿透）。
- **倾向**：做。
- **反方**：若本人属夜猫子作息，23 点后才是高效时间，这条会砍掉最需要提醒的时段。
- **验证**：用 `wellness` 已采集的 idle 数据回看真实活跃时段，按数据而非假设定窗口。

### 11.4 dormant 是否必须二次确认

- **命题**：意图抽取后必须经用户确认一次，才建 `DormantWatch`。
- **倾向**：必须确认。
- **反方**：确认动作本身就是一次打扰，且多数人会懒得点，导致 dormant 形同虚设。
- **验证**：统计确认率。若 < 30%，说明流程过重，应改为一键「记一下」而非对话式确认。

### 11.5 dormant 停滞阈值

- **命题**：3 天无关联活动即视为停滞。
- **倾向**：3 天。
- **反方**：不同事项节奏差异极大（装修按月、填志愿按天），单一阈值必然错。
- **验证**：按类别分别统计从「承诺」到「首次行动」的真实间隔中位数，按类别设阈值。

### 11.6 过期 > 7 天转「建议放弃」

- **命题**：超过 7 天的过期项不再播报催促，改为建议删除。
- **倾向**：做，这是本文最反行业惯例的一条。
- **反方**：有些事确实一直拖着但必须做（报销、年检、体检）。退场太早会造成实质损失。
- **验证**：统计「过期 7 天后仍被完成」的比例。若 > 25%，说明退场过早，应放宽到 14 天或按类别区隔。

### 11.7 三次退场是否给 high 豁免

- **命题**：同一事项最多说三次，第 4 次永久退场。
- **倾向**：硬上限，但 `importance=high` 可放宽至 5 次。
- **反方**：一旦开了豁免口子，「三次」就失去约束力，逐渐退化回无限催促。
- **验证**：观察 high 类事项的照做率与忽略率。若 high 也大量被忽略，说明问题不在次数而在内容质量。

### 11.8 忽略判定窗口

- **命题**：播报后 8 秒无交互记为 `ignored`。
- **倾向**：8 秒。
- **反方**：专注状态下 8 秒没看见极为常见，会把「没看见」误判为「不想做」，进而错误降频。
- **验证**：8s 与 15s 两版对比 `done` 率与 `ignored` 率；若 15s 版 `done` 明显更高，说明 8s 太短。

### 11.9 疲劳模型

- **命题**：每忽略一次 fatigue +0.3，做过一次 −0.5，≥ 0.7 静默该类别。
- **倾向**：先用最简单的线性模型。
- **反方**：线性衰减可能过快进入静默，导致「该说的不说」——这比多说一句的代价更大。
- **验证**：观察 fatigue 触发的静默中，事后被用户主动问起的比例（即 8.3 的静默正确率）。

### 11.10 合并播报的节奏

- **命题**：defer 队列 ≥ 2 条时，先总述再逐条，条间隔 ≥ 8 秒。
- **倾向**：8 秒。
- **反方**：8 秒太长会让总述显得断裂；太短则像连珠炮，等于没合并。
- **验证**：真人测试 5 秒 / 8 秒 / 12 秒三档，看完成率与主观烦躁度。

### 11.11 是否把 runtime 的 stale / blocked 接入仲裁

- **命题**：先不接，等 reminders 与 wellness 两级稳定后再接。
- **倾向**：暂不接。
- **反方**：任务执行期的提醒恰恰是用户最关心的；不接入会导致「执行中卡住 15 分钟」和「备忘录到点」两套体验割裂。
- **验证**：观察接入前是否出现「两类提醒同时弹」的实际冲突案例；有案例再接。

### 11.12 「闭嘴的表演」是否会被读成卖萌

- **命题**：被忽略时角色低头退让，被称「识趣」。
- **倾向**：做，这是最难被复制的部分。
- **反方**：中文语境里，桌面角色做这类动作极易被读成「装可爱」「嗯嗯怪」，反而引发反感。
- **验证**：只能靠真人。找 5 个非二次元用户，只给动作不给解释，问「它在干什么」。答「识趣」为通过，答「撒娇」为失败。

> 这 12 条里，只有第 6、12 条是本文的核心主张（其余都是可调的参数）。若第 6 或第 12 条被
> 证伪，本文的整个取向需要重写，而不是调参。
