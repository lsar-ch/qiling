# DeskMate 语音供应商与音色方案

> 状态：2026-09-04 定稿，与 Step 4（语音闭环）一起落地。
> 原则：音色不是写死在代码里的字符串，而是「人设槽位 → 归一化参数 → 供应商映射」的可配置体系。

## 1. 结论（先看这里）

> 2026-09-04 实测修订：听感拍板——**MiniMax = 人声（对话人格主声）**；**DashScope = 助理声（任务/备选 + STT 通道）**。
> 2026-09-04 定稿：MiniMax 默认音色 = **`Chinese (Mandarin)_Soft_Girl`**（用户确认），模型 `speech-2.8-hd`；
> DashScope 保留「助理/任务声 + STT」职责，作为可切换备选。


- **V1 首选阿里云百炼（DashScope）**：STT 用 `paraformer-realtime-v2`，TTS 用 `cosyvoice-v2`。
  原因：只需一个 `DASHSCOPE_API_KEY`；SDK 开源可核实；支持音色/语速/音高/音量/风格指令五个旋钮；中文识别合成效果好，适合本项目的“中文为主”设定。
- **火山引擎豆包语音作为第二供应商（配置位预留，Step 6/8 实测后接入）**：
  音色拟真度与情感自然度是行业标杆，且提供「端到端实时语音大模型-全双工」通道，未来升级全双工有现成路径。
  接入面较大（火山引擎控制台 appid/token/cluster + 音色下单授权 + V4 签名/官方 SDK），先不阻塞 V1。
- 两家都**未配置 API Key 时系统优雅降级**：语音入口提示“未配置语音供应商”，文字对话完全不受影响。


> 语音风格与人格映射设计见 `docs/VOICE-STYLE-PROMPT.md`；行业生态见 `docs/VOICE-LANDSCAPE.md`。

## 2. 音色怎么调：三层模型

把“音色”拆成三个独立层次，任何一层改动都不影响其他层，也方便后续换角色：

| 层次 | 控制什么 | 供应商字段 | DeskMate 统一字段 | 调整手法 |
|---|---|---|---|---|
| L1 基础音色 | 声音长相（性别/年龄/气质） | DashScope `voice`；火山 `voice_type` | `voice` | 换人设时换整只音色，参数不动 |
| L2 韵律参数 | 语速/音高/音量 | DashScope `speech_rate/pitch_rate/volume`；火山 `speed_ratio/pitch_ratio/volume_ratio` | `speed / pitch / volume` | 日常微调，幅度 ±10% 内听感自然 |
| L3 风格与情绪 | 语气、情绪、口音 | DashScope `instruction`（如“用台湾腔、温柔地说话”）；火山 `emotion` | `emotion / instruction` | V1 留槽位不锁定，后续按角色启用 |

> 厂商参数范围（已核实官方文档/SDK）：
> DashScope CosyVoice：`speech_rate`/`pitch_rate` 0.5–2.0，`volume` 0–100（默认 50），`instruction` ≤128 字，`language_hints` 支持 zh/en。
> 火山语音合成：`speed_ratio`/`pitch_ratio`/`volume_ratio` 0.1–3.0，`emotion` 情感标签可选，`encoding` 支持 wav/pcm/mp3/ogg_opus。

## 3. 人设音色槽位（当前建议值）

当前默认人设：**温柔可靠的知性女助理**（后续换台北女秘书时只改 L1 + L3）。

| 槽位 | 建议值 | 说明 |
|---|---|---|
| TTS 供应商/模型 | minimax / `speech-2.8-hd`（主声）；dashscope / `cosyvoice-v2`（助理声/任务报备） | 见 §1 听感结论 |
| 默认音色 `voice` | `Chinese (Mandarin)_Soft_Girl` | 2026-09-04 用户确认；甜美清亮，偏陪伴型 |
| 助理音色（备选） | `longxiaochun_v2` 知性、`longxiaoxia_v2` 甜美、`longjing_v2` 播音、`longxiaobai_v2` 清爽男声 | DashScope CosyVoice 预置；设置界面按试听切换 |
| `speed` | 1.05 | 略快一点，符合助理干练感 |
| `pitch` | 1.0 | 保持自然；要更幼态可 1.05–1.1 |
| `volume` | 1.0 | 界面音量再单独控制 |
| `emotion` | MiniMax 自带参数，V1 默认 neutral | MiniMax 情绪枚举（happy/sad/angry/…）；克隆音是否支持待实测 |
| `instruction` | 空（V1 不启用） | DashScope 助理声专用；写人设后启用，如“用台湾腔、语气亲切” |

按情绪微调速查（同一音色下只动 L2/L3）：

| 情绪/风格 | speed | pitch | instruction 示例 |
|---|---|---|---|
| 默认知性 | 1.05 | 1.0 | — |
| 活泼俏皮 | 1.15 | 1.08 | 语气轻快、俏皮一点 |
| 撒娇卖萌 | 1.05 | 1.12 | 用撒娇的语气说话 |
| 冷静专业 | 0.95 | 1.0 | 用专业沉稳的语气 |
| 完成任务报喜 | 1.1 | 1.05 | 带一点兴奋感 |

## 4. 声音定制与「台湾腔」路线（2026-09-04 调研）

### 4.1 结论先行

- 音色是卖点，但「像不像台湾女秘书」= **口音（声音层）+ 语气用词（文本层）** 两部分。
  只调 TTS 音色不解决“台味”，必须同时做 persona 提示词 + 台味语气词表。
- 全行业可借鉴方案（不止火山/阿里）见 `docs/VOICE-LANDSCAPE.md`；台湾腔可先走「预置台湾国语音色」捷径，零成本试听样本已生成在 `data/voice_samples/edge-tts/`。
- 建议分三步走：V1 先用预置音色跑通并验收；随后用「云端少样本复刻」做 A/B 听感选型；
  若素材敏感/需离线再评估开源私有化。**先试听再选定，不预设唯一答案。**
- 当前链路（DashScope cosyvoice-v2）已内置少样本复刻能力，接入成本最低，优先实测。

### 4.2 方案对比

| 实现手段 | 代表 | 台湾腔还原 | 音色相似度 | 接入/成本 | 说明 |
|---|---|---|---|---|---|
| ① 预置音色直选 | DashScope cosyvoice-v2 预置音色 / 火山 BV 音色 | 无（需文本层补偿） | — | 最低、最快 | V1 主路径；先完成闭环验收 |
| ② 云端少样本复刻 | **DashScope VoiceEnrollment**（已核实 SDK） | 参考音带口音即可迁移 | 高 | 低；默认 ≤10s 参考音，URL 注册 | 与现链路同栈，推荐第一实测项 |
| ② 云端复刻 | 火山声音复刻 / 音色设计 | 参考音决定 | 高 | 需控制台开通+资源包 | 拟真度与情感上限高；素材时长/计费以控制台为准 |
| ② 云端定制/克隆 | MiniMax、ElevenLabs（Instant/Pro Clone、Voice Design） | 中（参考音/描述） | 高 | 中高；境外延迟 | 备选；国内访问与合规需评估 |
| ③ 开源本地 | CosyVoice 3.0（已核实 README：0-shot 克隆、18+ 方言、instruction 情感/口音）、GPT-SoVITS、IndexTTS2 | 参考音/方言指令 | 高（需微调） | 需 GPU 与工程成本 | 素材可控、可离线；质量依赖素材与调参 |
| ①b 台湾国语预置音色 | **Azure zh-TW**（HsiaoChen/HsiaoYu 女声，已核实）等 | 天然台腔、开箱即用 | 低（正式 API 需开通） | 最快验证卖点；edge-tts 可先免费试听 |
| ④ 文本层台味 | persona 提示词 + 语气词/用词表（啦/喔/蛤/超…的）+ 短句停顿 | 决定“像不像”的另一半 | — | 极低 | 必做；与任意音色叠加 |

### 4.3 推荐路线

1. **V1（当前）**：MiniMax `Chinese (Mandarin)_Soft_Girl` 跑通语音闭环 —— 卖点先证明“能听能说能打断”。
2. **V1.5 台湾腔选型**：准备一段**有授权**的台腔女声素材（20s–3min，清晰、安静、语气自然），
   用 `scripts/voice_probe.py` 对 DashScope 复刻 / 火山复刻 / 开源克隆做同一词表 A/B 试听打分，
   主观听感 + 相似度 + 稳定性决定默认“角色音”。注意素材版权：优先本人录制或已授权样本。
3. **V2 persona 固化**：选定音色后固化 `voice + speed/pitch + instruction + 台味语气词表`，
   在设置界面提供“角色音配置”；届时再评估火山全双工升级（适配层已有映射位）。
4. **角色克隆音（随 persona 追加）**：对已授权素材用 MiniMax 语音克隆生成专属 `voice_id`，
    绑定到角色卡（见 §4.5 与 `docs/MEMORY-SCHEME.md` §6.1），一个角色一套声音+形象+人格。

### 4.4 验收方式（真实账号）

配置 `DASHSCOPE_API_KEY` 后运行：

```bash
.venv/bin/python scripts/voice_probe.py --voices longxiaochun_v2,longxiaoxia_v2,longjing_v2
```

脚本会用固定词表（打招呼/撒娇卖萌/冷静专业/任务完成/台湾腔示例句）逐音色合成 wav，
输出到 `data/voice_samples/<音色>/*.wav` 供并排试听打分；克隆音色注册后再把 voice_id 加入 `--voices` 复测。

### 4.5 MiniMax 语音克隆（角色音绑定，2026-09-04）

> 用户思路：给角色（人物/动物）克隆专属音色并绑定在 persona 上，例如自定义《凡人修仙传》银月时
> 用其声线说话。接口已按 MiniMax 官方 MCP 源码 `voice_clone` 核实，合成模型为 `speech-2.8-hd`，与默认主声同栈。

克隆流程（两段式）：

1. 上传素材：`POST /v1/files/upload`（multipart，`purpose=voice_clone`）→ 返回 `file_id`；本地文件或 URL 均可。
2. 克隆：`POST /v1/voice_clone`，body `{file_id, voice_id, text?}` → 返回 `demo_audio` 试听链接。
3. 克隆音进入专属列表：`POST /v1/get_voice`，`voice_type=all|system|voice_cloning`。
4. 合成：`t2a_v2` 的 `voice_setting.voice_id` 传克隆 id 即可，链路与预置音色一致。

约束与提示：

- 计费：克隆本身 + 克隆音首次使用均计费（官方 cost warning），需实名。
- 素材质量决定相似度：需单说话人、干净无 BGM/噪音、语气自然的连续语音；动漫截取片段常带 BGM/音效，
  可能需要降噪/去背景预处理（具体时长与格式规范在接入实测时按官方文档校准）。
- 授权边界：克隆影视/动漫角色声线用于发布或商用需版权方与配音演员授权；本机自用调试可跑通，
  上架/分发前必须先解决授权。
- 绑定关系属 persona 体系，角色卡草案见 `docs/MEMORY-SCHEME.md` §6.1。

实测记录（2026-09-04，用户本人录音 91.5s / m4a / 48k 单声道）：

- 本地 m4a 直接上传成功，无需转码；克隆返回 `demo_audio` 试听链接。
- 克隆完成后**立即可用**：`t2a_v2` 直接传克隆 `voice_id` 即返回音频，无需等待列表刷新。
- 克隆音支持 `emotion` 参数（已用 happy 验证），适合后续情绪映射。
- `get_voice`（`voice_type=voice_cloning`）列表更新有延迟，可能数分钟后才出现；
  角色绑定应以配置里保存的 `voice_id` 为准，不依赖列表查询。
- 试听样本在 `data/voice_samples/cloned/`（demo + neutral + happy）。
- 结论（用户确认）：克隆音听感 OK，与主声可明显区分，作为角色绑定候选音色保留（`deskmate_voice_01`）。

## 5. 配置与降级行为

配置入口（三处，优先级 环境变量 > config/settings.yaml > 代码默认）：

- `config/settings.yaml` → `voice:` 段（供应商、模型、默认音色、参数）
- `.env` / 环境变量：`DASHSCOPE_API_KEY`（V1 必需）；火山相关变量预留
- 运行期可查看/调试：`GET /api/voice/status`

降级规则：

- `voice.provider` 配置为 dashscope 但缺少 `DASHSCOPE_API_KEY` → 状态 `disabled`，`/api/voice/status` 返回原因，前端给用户明确提示。
- 云供应商调用失败 → 返回错误事件与原因，文字链路不受影响。
- 测试环境使用 mock provider，不打真实网络。

## 6. 接口速览（Step 4 新增）

| 接口 | 说明 |
|---|---|
| `GET /api/voice/status` | 供应商/模型/默认音色/参数/是否可用 |
| `POST /api/voice/recognize` | 上传 WAV（16k 单声道）→ 返回转写文本 |
| `POST /api/voice/synthesize` | 文本 + 可选表现参数 → 返回音频字节 |
| `GET /api/voice/voices` | 供应商可用音色列表（`?profile_id=` 按指定模型档案取），只读不占语音租约 |
| `POST /api/voice/preview` | 试听：用指定音色合成一句样音，不占租约、不驱动挂件状态 |

## 7. 升级路径（全双工）

火山「端到端实时语音大模型-全双工版本」与阿里实时语音大模型都提供一条 WebSocket 全双工通道（输入输出同流）。
V1 采用“整句录音 → HTTP → 播报可打断”是为了先稳定闭环；
Step 8+ 再做流式升级时，接口层只换适配器，前端与契约基本不动。

## 8. 音色列表自动获取与角色绑定（2026-09-13）

音色不写死在配置里：用户配好语音合成模型后，系统自动向供应商拉取音色列表，设置页与角色卡都用下拉选择。

**统一入口**：`GET /api/voice/voices`（`profile_id` 可选）。返回 `{provider, model, current, available, voices[], reason}`；
`voices[]` 元素为 `{id, name, kind}`，`kind` 取 `system | cloned | preset`。

**各供应商的取法**：

| 供应商 | 音色来源 | 说明 |
|---|---|---|
| MiniMax | `POST /v1/get_voice`（`voice_type=all`） | 返回系统音色 + 账号克隆音色（`cloned`） |
| DashScope CosyVoice | 官方预置清单（按 model 分组）+ `VoiceEnrollmentService.list_voices` | 预置音色无列表接口，只能内置清单；克隆音色走接口 |
| OpenAI 兼容 / 自建 | `GET {base}/audio/voices`，失败退 `GET {base}/models` | 非官方规范，Kokoro-FastAPI / openedai-speech / LocalAI 等事实约定 |

**取不到怎么办**：返回空列表 + `reason`，前端回退为手填音色 ID，并说明原因，不阻塞保存。

**试听**：`POST /api/voice/preview`，可选传 `profile_id / provider / base_url / model / voice / api_key / text`，
缺省项按「指定档案 → 当前生效配置」兜底。设置页与角色卡都有「试听」按钮，按当前选中（含未保存）的音色合成。
自建 OpenAI 兼容服务通常无鉴权，不填 Key 也可试听；MiniMax / DashScope 缺 Key 时返回 400 而不是空跑网络。
试听会消耗供应商额度，所以只在用户点击时触发。

**角色绑定优先级**：角色卡里显式选了音色（`persona_voice` 非空）时，语音合成模型档案不再覆盖它；
未选（「跟随全局默认」）时用默认 TTS 档案的音色。因此不同角色可以绑定不同音色。

**已知边界**：

- DashScope 预置音色清单是官方文档里的常用子集（非全量），且每个 model 只支持自己那组音色，不能跨 model 混用。
- 新增 openai_compatible 供应商只要求填 Base URL；未填时语音合成降级为 `disabled` 并给出原因。
- 设置页里未保存的新档案会先按「当前生效配置」取列表，保存后回来再按该档案取。
