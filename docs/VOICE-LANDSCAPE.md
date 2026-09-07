# DeskMate 语音输出生态全景与借鉴清单（Voice Landscape）

> 日期：2026-09-04｜目的：不只盯火山/阿里，横向盘点可借鉴的 TTS / 声音克隆方案，
> 为「回复音色 = 卖点」与「台北女秘书 / 台湾腔」选型提供全局视图。
> 标注：✅=本次已从官方 SDK/README/文档核实；⚠️=公开能力，参数/价格以官方控制台为准。

## 1. DeskMate 语音输出的需求定位

- 中文为主；语气亲切，后期可带情绪、角色音（台湾腔女声）。
- 桌面助理形态：回复多为短句，需要低延迟、可打断、可换行播放。
- 允许云 API，也考虑开源私有化（素材隐私、成本、离线）。
- 全双工是远期升级方向，选型时保留流式/同通道适配位。

## 2. 方案全景

### 2.1 商业托管 · 中文强（大厂）

| 方案 | 音色/克隆 | 特点 | 备注 |
|---|---|---|---|
| 阿里百炼 CosyVoice 云 | ✅ 预置多音色 + ✅ 少样本复刻（VoiceEnrollment ≤10s）| 纯 API Key、SSML/instruction、中文好 | 当前 V1 主链路 |
| 火山豆包语音 | 预置 + 声音复刻 + 音色设计（描述式）| 拟真与情感自然度标杆、有端到端全双工通道 | 需控制台 appid/token + 资源包 |
| MiniMax Speech | 预置 + 声音克隆/定制 | 中文质量第一梯队 | ⚠️ 需实测计费/口音 |
| 腾讯云智聆 / 百度 / 讯飞 | 预置丰富 + 复刻 | 中文老牌，方言/风格多 | ⚠️ 需实测与成本比较 |

### 2.2 商业托管 · 台湾腔捷径与国际方案

| 方案 | 亮点 | 备注 |
|---|---|---|
| **Azure Speech（微软）** | ✅ 预置 **zh-TW-HsiaoChenNeural / HsiaoYuNeural**（台湾国语女声）+ YunJhe 男声；SSML 精细控制 | 台湾腔可「零克隆」直接出效果；edge-tts 可立即免费试听（仅试听，商用走正式 API/合规） |
| Google Cloud TTS | ⚠️ cmn-TW（台湾国语）音色齐全 | 页面抓取受限，以官方控制台为准 |
| ElevenLabs | Instant/Professional 克隆、Voice Design（文字描述含口音）、多语言 | 中文音色覆盖一般、境外延迟，备选 |
| OpenAI TTS/Realtime | 预置高质量音色、实时语音对话原生 | 无公开克隆/自定义 API；适合 Realtime 全双工参考 |

### 2.3 开源 · 可本地 / 私有化（做专属角色音的下一个梯队）

| 项目 | 已核实能力 | 适合场景 | 注意事项 |
|---|---|---|---|
| **CosyVoice 3.0**（FunAudioLLM）| ✅ 9 语言 + 18+ 中文方言口音 + instruction（情感/口音/语速）+ 0-shot 克隆 | 中文方言路线、与云端同源可私有 | 需 GPU 部署 |
| **Spark-TTS 0.5B**（讯飞开源）| ✅ 中英 0-shot 克隆、跨语种/中英混说 | 轻量本地中文克隆 | 学术/合法用途约束 |
| **IndexTTS-2.5**（B 站）| ✅ 单段参考 0-shot 克隆、中英、工业级可控/高效 | 高质量中文专属音 | 需 GPU、素材要求 |
| **Fish-Speech / OpenAudio S1**| ✅ 80+ 语言、10–30s 参考克隆、TTFA≈100ms | 低延迟本地/自托管 API | 注意模型与代码 license |
| **GPT-SoVITS**| ✅ 5s 零样本 / 1min 微调、中文方言友好 | 少样本快速微调、方言 | 质量依赖素材与调参 |
| **OpenVoice V2**| ✅ 音色克隆 + 口音/情感风格参数控制 | 风格解耦实验 | 参考级，商用注意授权 |
| F5-TTS | ⚠️ 流匹配高质量克隆 | 英文为强项 | 中文支持有限 |
| ChatTTS | ✅ 对话中文自然，但模型 CC-BY-NC ❌ 不可商用 | 仅研究参考 | 不可用于产品 |

## 3. 台湾腔到底怎么出？三条路线对比

| 路线 | 做法 | 效果 | 成本/速度 |
|---|---|---|---|
| A. 预置台湾国语音色 | Azure zh-TW（Chen/Yu）等直接调用 | 口音自然纯正、开箱即用 | 最低、最快 |
| B. 台腔样本克隆/复刻 | 用授权的台腔女声素材做 DashScope/火山/MiniMax 克隆，或开源 GPT-SoVITS/IndexTTS 微调 | 独家人声 + 可带台味 | 中；需素材与 A/B |
| C. 方言/instruction | CosyVoice 方言能力 / 各家 instruction 描述 | 灵活但还原度待实测 | 中 |

> 关键结论：台湾腔 = 口音（路线 A/B/C）＋ 语气用词/句尾词（文本层，必做）。
> 想最快验证卖点 → 路线 A（现在就能用 edge-tts 试听）；想要“只有我有”的专属角色音 → 路线 B；
> 路线 A/B 不冲突，可作为「快速默认」与「升级角色音」两档并存。

## 4. 借鉴清单（哪些值得抄进 DeskMate）

- 音色选择器体验：ElevenLabs / MiniMax 的「试听 + 收藏 + 微调滑块」UI → 进设置界面「外观-语音」。
- SSML 控制：Azure 的语速/停顿/重音标签可参考；大模型音色普遍支持「情绪/风格标签」。
- 长文本处理：各家有单次字数限制（如火山 1024B、DashScope ~2000 字）→ 需分段合成 + 句间停顿，本项目的 `short_reply_chars` 已预留这类分工。
- 打断/全双工：火山端到端全双工、OpenAI Realtime、MiniMax Speech 是后续升级参照；适配层已抽象 provider，不被锁死。
- 授权红线：克隆/复刻必须用已授权素材（本人录制/正版授权）；ChatTTS 等 NC 模型不商用；开源模型各自 license 需记录在案。

## 5. 建议行动顺序（验证音色卖点）

1. ✅ **今天即可**：试听 `data/voice_samples/edge-tts/` 里的 Azure 台湾女声样本（HsiaoChen/HsiaoYu × 日常句/台味句）。
2. 配置 `DASHSCOPE_API_KEY` 后跑 `scripts/voice_probe.py`：预置音色（longxiaochun/longxiaoxia/longjing）先验收 V1 主音色。
3. 准备授权台腔素材（20s–3min）→ 分别试 DashScope VoiceEnrollment 与（可选）Azure/开源方案 → 同词表 A/B 打分。
4. 若「台湾腔 + 上线快」优先 → 评估把 Azure zh-TW 作为可选 provider 接入（适配器预留位）。
5. 若「独家角色音」优先且可上 GPU → 评估开源私有化（Spark-TTS 轻量起步，IndexTTS-2.5/CosyVoice 3.0 高质）。

## 6. 为什么免费音色“AI 味重”？—— 生成式语音与神经语音的分野（2026-09-04 补充）

- edge-tts / Azure 预置音色属于**传统参数化神经 TTS（统计声学 + 波形模型）**：每个字“念得准”，但节奏平、无语气、无呼吸与停顿变化，像播音稿。
- 目前听感接近真人对话的语音几乎都是**大模型生成式 / 端到端语音**：由 LLM 直接生成声学 token，韵律、语气、情绪、口型甚至笑声/口头语由模型按语义自由发挥（典型代表：火山 Seed 系、MiniMax Speech、ElevenLabs、Fish、OpenAI 语音、开源 CosyVoice3/Step-Audio/Kimi-Audio）。
- 结论：**选型主战场应放在“生成式/端到端”梯队**；预置 zh-TW 神经音色（上一轮样本）只作口音参考，不作为最终音色。台湾腔若在生成式引擎没有现成方言音色，就用真实台腔女声素材做“声音复刻/克隆”，让生成式引擎发声——自然度跟随引擎，口音跟随素材。

## 7. 自然度第一梯队与试听短名单（2026-09-04 补充）

### 第一梯队（云端旗舰，生成式，最像人）

| 方案 | 依据 | 特点与验证路径 |
|---|---|---|
| **火山豆包语音（Seed 系）** | ✅ 官方文档（大模型合成 emotion、声音复刻、音色设计、端到端实时语音-全双工版） | 自然与情绪上限最高、可打断全双工；控制台“语音技术→大模型语音合成”在线试听挑音色；有台腔素材可直接做声音复刻 |
| **MiniMax Speech 2.x**（现 2.8） | ✅ 官方产品页版本名 | 中文情感自然度第一梯队、支持声音克隆；开放平台注册通常送免费额度，控制台可在线合成试听 |
| 阿里 CosyVoice v2/v3 | ✅ 已接入 + SDK 已核实 | 与现链路同栈、instruction/复刻；配 key 跑 `scripts/voice_probe.py` 即可对比 |
| ElevenLabs（Multilingual v2 / v3 / Flash v2.5） | ✅ 官网中文页（支持中文等 29~70+ 语言；Voice Design 用提示词设计音色；声音库 1 万+；对话 Flash 延迟约 75ms） | 质感与情感控制好；境外延迟、付费不便，作对照/借鉴“提示词设计音色”交互 |
| OpenAI（gpt-4o-mini-tts / Realtime） | ⚠️ 公开 API | 预置音色 + Realtime 全双工架构参照 |
| Fish Audio（OpenAudio S1 系） | ✅ README（80+ 语言、10–30s 克隆、TTFA≈100ms） | 低延迟、克隆方便 |

### 第二梯队（开源本地，接近云端，适合专属音与离线）

| 方案 | 依据 | 备注 |
|---|---|---|
| CosyVoice 3.0 | ✅ README | 9 语 / 18+ 方言 / instruction（情感、口音） |
| Kimi-Audio（月之暗面） | ✅ 官方仓库 | 音频理解+生成一体，中文向 |
| Step-Audio 2（阶跃） | ✅ 官方仓库 | 端到端多模态语音，工业向 |
| IndexTTS-2.5 / Spark-TTS 0.5B / Fish-Speech | ✅ 前文核实 | 轻量到高质都有，按 GPU 取舍 |
| MiniCPM-o（面壁） | ✅ README | 端到端实时语音对话，开源研究参照 |
| Sesame CSM | ✅ README | 英文对话自然度研究标杆，中文弱 |
| GPT-SoVITS / OpenVoice | ✅ 前文核实 | 少样本/风格解耦，看素材与调参 |
| 腾讯混元 TTS | ⚠️ HF/ModelScope 发布 | 情感可控中文语音，需复核当前入口与授权 |

### 建议试听短名单（下一步动作）

1. **火山豆包**：控制台“大模型语音合成”在线试听大模型音色；如要台腔，另用真实台腔素材做声音复刻 A/B。
2. **MiniMax**：开放平台注册（送额度）→ Speech 2.x 用同一句台味文案在线合成试听。
3. **CosyVoice（现链路）**：配置 `DASHSCOPE_API_KEY` → `scripts/voice_probe.py` 出本地 wav，与上面两家同文案并排打分。

> 三家都听完后，再决定默认音色/是否引入新 provider；适配层预留位已按此设计。

## 8. 实测记录（2026-09-04，真实 Key）

- **DashScope 预置音色**：`cosyvoice-v2` 基础音色合成正常；但 `instruction`（风格指令）对预置音色返回引擎 428 不支持
  ——该能力当前只适用于声音复刻/克隆音色等受支持路径。适配层已加“428 自动去掉 instruction 重试”，
  目录中 instruction 文案保留待克隆音色接入后启用。
- **MiniMax**：充值后已跑通真实合成（`speech-2.8-hd`，`/v1/t2a_v2`）：
  - 支持 `emotion` 参数：happy / sad / calm / angry / fearful / disgusted / surprised / fluent 等；whisper 该模型不支持。
  - `vol`/`pitch` 需整数；音色命名形如 `Chinese (Mandarin)_Sweet_Lady`（甜美女声）、`Warm_Girl`（温暖少女）、`Soft_Girl`（软软女孩）；系统音色共 303 个、暂未发现台湾腔预置（台腔需克隆/自定义）。
  - 可听样本：`data/voice_samples/minimax/`（3 音色 × neutral/happy/sad/calm）。
- **可听产物**：`data/voice_samples/tones/`（9 情绪 × 载句+自然句，基于 longxiaochun_v2）、
  `data/voice_samples/<voice>/*.wav`（longxiaochun_v2 / longxiaoxia_v2 / longjing_v2 × 5 句）。

### 听感结论（用户拍板，2026-09-04）

- **MiniMax 更像人**（对话自然、情绪有真实感）→ 定位为「对话人格 / 回复主声」。
- **DashScope 像助理**（清晰、职业、礼貌感）→ 保留为「任务播报 / 备选」与 STT 识别通道。
- 下一步：确认默认 MiniMax 音色后接入 ai-service 为 TTS provider；DashScope 继续承担 STT 与可切换 TTS。

