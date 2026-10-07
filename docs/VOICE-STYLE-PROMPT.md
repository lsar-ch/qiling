# 栖灵 语音风格提示词设计（Persona → 语气 → 音色）

> 目标：让 栖灵 的回复“像这个人说话”，而不是“像 TTS 念稿”。
> 手段：借鉴 AI 短视频配音的“语调提示词”做法，把**角色人设**翻译成**文案风格**与**语音表现参数**两层指令。

## 1. 核心思路：三段落差要同时解决

```text
人设（台北女秘书 / 兔子精灵 / 冷面助手 …）
  ├─ 文案层 reply_style   → 控制“说什么、怎么说”：口语化、语气词、句式（LLM system prompt）
  ├─ 语音层 voice_style   → 控制“声音怎么发”：音色 + speed/pitch + 语气指令/情绪标签（TTS 参数）
  └─ 表现层 emotion_map   → 控制“人偶怎么动”：情绪 → 挂件动画/表情（事件驱动）
```

只调音色（引擎）不够，只调文案也不够；三段落差对齐才有“像真人交流”。

## 2. 短视频配音圈的“语调提示词”套路（可借鉴做法）

| 技巧 | 做法 | 例子 | 栖灵 对应 |
|---|---|---|---|

> 关联文档：`docs/VOICE-PROVIDERS.md`（供应商与音色）、`docs/VOICE-LANDSCAPE.md`（生态全景）。
| A. 句内情绪旁白 | 文本里直接写情绪，模型读出语气 | “（开心地）终于搞定啦！” | LLM 生成时可带 `(开心)` `(轻声)` 标注，播报前剥离 |
| B. 独立情绪/语气参数 | 合成请求带 emotion / 风格标签 | 火山 `emotion=happy`（官方参数✅）；CosyVoice `instruction="语气轻快带笑意"`（SDK✅） | 复用 `VoiceParams.emotion/instruction` 槽位 |
| C. 角色语音提示模板 | 一段人设描述控制全程腔调 | “30岁台北职场女性，说话温柔亲切、语速中等，常用‘啦/喔’结尾” | `persona.voice.style_instruction` |
| D. SSML 精调 | 重音/停顿/语速局部控制 | `<break time="300ms"/>` 句间停顿 | 长文本分段时使用 |

> 结论：不需要发明新东西，把 A/B/C/D 四招组合进 persona 配置即可；我们的契约已为 B/C 预留字段。

## 3. Persona 语音配置规范（拟新增 `config/personas/<id>.yaml`）

```yaml
id: taipei-secretary          # 人设 id（后续在设置界面与形象图绑定）
name: 台北小秘书
image: assets/characters/secretary.svg   # 形象（后续）

# ── 文案层：注入 LLM system prompt ──
reply_style:
  role: "你是 栖灵，一个 27 岁、在台北工作的干练女秘书助理"
  traits: [亲切, 干练, 偶尔俏皮, 细心]
  habits:
    - 句子短、口语化
    - 句尾可带「啦/喔/哈」，感叹「超…的」
    - 汇报任务先说结果，再问“需要我帮你处理吗？”
  avoid: [书面语, 官腔, 冷冰冰, 长篇大论]
  emotion_tags: true          # 允许生成 (开心)(轻声)… 情绪旁白，播报前剥离展示

# ── 语音层：TTS 全程基调 ──
voice_style:
  voice: ""                   # 默认走全局音色；克隆台腔音色后填 voice_id
  speed_base: 1.05            # 语速基调
  pitch_base: 1.0
  style_instruction: "用温柔亲切的台湾腔女声说话，像台北办公室里的女秘书，自然口语、带一点笑意"
  style_instruction_fallback: "声音温柔亲切、口语自然"   # 未启用台腔/克隆时使用

# ── 情绪映射：LLM 判定情绪 → 语音表现微调 + 挂件动画 ──
emotion_map:
  neutral:  {speed: 1.0, pitch: 1.0,  instruction: null}
  happy:    {speed: 1.12, pitch: 1.06, instruction: "语气轻快、带着笑意"}
  gentle:   {speed: 1.0,  pitch: 1.02, instruction: "轻声细语、很温柔"}
  playful:  {speed: 1.1,  pitch: 1.1,  instruction: "俏皮一点、带点撒娇"}
  serious:  {speed: 0.94, pitch: 1.0,  instruction: "语气认真、沉稳专业"}
  sad:      {speed: 0.96, pitch: 0.98, instruction: "语气低落、轻声安慰"}
  excited:  {speed: 1.15, pitch: 1.08, instruction: "兴奋一点、语速明快"}
```

## 4. 最小改造点（保持 V1 稳定优先）

1. **固定人格先上、自动情绪后上**：V1 只把 `reply_style` 注入 LLM、把 `voice_style` 注入 TTS，
   不要求 LLM 实时判情绪——先保证“声音像这个人”。
2. `emotion_tags` 默认关：避免不稳定输出；开放后再做「生成旁白 → 剥离 → 映射 emotion」。
3. 语音请求透传：`POST /api/voice/synthesize` 已支持 `params`（含 emotion/instruction），
   前端 `speak()` 增加透传当前 persona 参数即可，服务端契约无需大改。
4. 试听验收：`voice_probe.py` 词表替换为“人设情绪测试句”（见下），配不同 persona 听语气差异。

## 5. 情绪测试句（供 A/B 试听，含台味版）

- 日常：你好呀，我是 栖灵，今天想让我帮你做点什么呢？
- 开心/卖萌：诶～这个任务有点意思，交给我你放心啦！
- 冷静/专业：收到，我先梳理一下步骤，稍等片刻，有结果马上告诉你。
- 完成报喜：搞定啦！已经把结果整理好放到主界面咯。
- 疑问/确认：这个操作会改动你的设置，确定要我继续吗？
- 安慰：别急啦，我们一起看看，问题一定能解决的。

## 6. 校准目录（Voice Tone Calibration Catalog，2026-09-04 定稿）

- 决定：先建「情绪 → 语音表现」的**确定性校准目录**；**暂不建**「情绪 → 文案表达」的全局提示词库
  （避免模板化 AI 味，且它依赖 LLM 情绪标签稳定，属于后置依赖）。
- 目录文件：`config/voice_tone/catalog.yaml`（v0.1 / draft，含 9 个情绪：neutral/happy/playful/gentle/
  calm/excited/sad/apologetic/confirming）。
- 每个情绪条目 = 参数偏移（speed/pitch/volume）＋ 供应商映射（dashscope `instruction`；volcengine
  `emotion` 占位待实测）＋ 载句/自然测试句（含台味版）。
- A/B 方法：先用固定“载句”只听声音差异，再听自然句的整体语气；逐条听校后把 `calibration_status`
  从 pending 改为 calibrated。
- 试听：配好 key 后运行 `.venv/bin/python scripts/voice_probe.py --tones`，输出到
  `data/voice_samples/tones/<情绪>-carrier|natural.wav`。
- 加载与校验已实现：`app/speech/tone_catalog.py`（含 `load_validated`），并有单测覆盖。

## 7. 落地顺序建议


1. `Step 4.5 语音人格化`：`config/personas/default.yaml`（固定人格）+ `reply_style` 注入 + `voice_style` 透传（小改动）；情绪表现引用 `config/voice_tone/catalog.yaml` 的条目做参数解析。
2. 设置界面「外观 → 语音」：人设说话风格试听（播放 5 句情绪测试句）。
3. 形象绑定：`persona.id` ↔ 挂件形象/动画（与挂件状态机联动，进 Step 7 persona）。
4. 自动情绪：LLM 输出情绪标签 + `emotion_map` 驱动 TTS 与挂件动画（Step 8 前评估稳定性再上）。
