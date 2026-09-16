# DeskMate P1 & P2 任务卡（2026-09-16）

> 合并了 Voice-Companion-Bundle 调研建议，与原有 P1/P2 任务统一排期。

---

## P1：轻量主动性与语音优化

### P1-T1：TTS 增量分块播报

**来源**：Voice-Companion-Bundle 建议 3 + P1 短播报需求

**现状**：`services/ai-service/app/speech/base.py` 全量 `synthesize()`，整段合成后才播放。

**目标**：改为 `response.output_audio.delta` 式增量输出，600–1000ms 分块播放。

**改动范围**：
- `services/ai-service/app/speech/base.py`：拆 `synthesize()` 为增量生成器
- `services/ai-service/app/speech/`：播放端按块消费，保留 barge-in 打断能力
- 首响延迟从整段等待降到首块 <1s

**验收**：TTS 首响 <1s；分块播放期间 barge-in 仍可打断。

**实际落地**：⚠️ 部分完成 —— Web 端已走分块播放（`services/ai-service/app/speech/base.py:66` `synthesize_stream`、分句 `:84`；`services/ai-service/app/api/voice.py:319` SSE 端点；`apps/web/src/api.ts:934`；`apps/web/src/ChatPage.tsx:317`）；挂件仍是全量合成（`apps/desktop/src/components/Widget.tsx:330`、`:375`），且无自动化测试、无首响延迟度量。

### P1-T2：任务完成/失败主动短播报

**来源**：原 P1 范围

**目标**：任务状态变更时，通过挂件语音播报简短提示（非全量 TTS，走 P1-T1 分块链路）。

**改动范围**：
- `services/ai-service/app/`：AgentRun 完成/失败事件 → 触发短播报队列
- 播报模板：`"xx 任务完成了"` / `"xx 任务没成功，点我看详情"`
- 播报队列：合并短时间内多条播报，避免轰炸

**验收**：任务完成后 3 秒内挂件播报；多条播报自动合并。

**实际落地**：✅ 已完成 —— `services/ai-service/app/agents/runtime.py:467` 发 bubble + `speak_text`，`apps/web/src/ChatPage.tsx:469` 自动播报；遗留挂件侧无「多条播报合并队列」（`apps/desktop/src/components/Widget.tsx:328` 忙则丢弃），转 V2。

### P1-T3：记忆更新提示

**来源**：原 P1 范围

**目标**：记忆写入后挂件气泡提示，不语音播报。

**改动范围**：
- 记忆写入事件 → 挂件气泡 `"已记住：xxx"`
- 低频限制：5 分钟内最多 1 次

**验收**：记忆写入后挂件气泡出现，5 分钟内不重复。

**实际落地**：✅ 已完成（2026-09-16 修复）—— 原 `apps/web/src/ChatPage.tsx` 把 `memory.updated` 挡在 `TASK_EVENT_TYPES` 白名单外是死代码；已把 `env.source !== "task"` 与 `TASK_EVENT_TYPES` 过滤拆开，`memory.updated` 分支移到过滤之前（`ChatPage.tsx:428`、`:429`、`:443`），后端 `services/ai-service/app/agents/runtime.py:544` 发的事件现在能被消费；5 分钟限频 + 5 秒自动清除保留。已补回归测试 `services/ai-service/tests/test_agent_runtime.py::test_completed_task_publishes_memory_updated_event`（断言事件 `source="task"`、`task_id` 匹配、bubble 以「已记住：」开头）。

### P1-T4：工作模式自适应记忆深度

**来源**：原 P1 范围

**目标**：闲聊模式加载轻量上下文，工作模式加载完整项目记忆。

**改动范围**：
- 分流器增加 `mode: casual | work` 判断
- 记忆加载按 mode 选择 L1/L2/L3 检索深度
- 用户可手动切换模式，默认自动判断

**验收**：闲聊对话不加载项目 L3；工作对话自动加载完整上下文。

**实际落地**：✅ 已完成 —— `services/ai-service/app/api/chat.py:77` mode 字段、`:337` casual 压到 800 字/空 surfaces、work 全量；测试 `services/ai-service/tests/test_chat.py:231`；本轮补上手动切换 UI（`CHAT_MODES` 常量 `apps/web/src/ChatPage.tsx:63`，输入框上方三态分段控件 `:1179`，自动/闲聊/工作，带 `title`/`aria-label` 说明记忆深度）。遗留：`mode` 尚未进 `packages/contracts`，桌面端无法传，转 V2。

---

## P2：发布加固

### P2-T1：一键安装脚本

**来源**：原 P2 范围 + here 打包借鉴

**目标**：`scripts/setup.sh` 升级为完整安装脚本。

**改动范围**：
- 检测并安装 Python 3.11+、Node 20+、Rust/Tauri 依赖
- 创建 `.venv`、`npm ci`
- smoke test：启动 ai-service → 健康检查 → 关闭
- 按需安装 flag：`--with-voice` / `--with-browser`
- 失败时打印明确修复入口

**验收**：干净 macOS 环境跑一遍 `setup.sh` 后 `dev.sh` 全通。

**实际落地**：✅ 已完成 —— `scripts/setup.sh` 工具链检测 / `.venv` 复用 / `npm ci` / `--with-voice` / `--with-browser` / smoke test / 修复入口 / Windows 指向迁移文档；本轮修掉两处实测缺陷：`fetch_health` 超时 2s→8s（`scripts/setup.sh:83`，冷启动首次 health 实测 3.25~4.30s，2s 必失败）、语音 key 检测增加读取项目根 `.env`（`scripts/setup.sh:224`，因 `services/ai-service/app/config.py:243` 用 dotenv 自动加载 `.env`）。验收遗留：未在干净 macOS 上跑完整 `setup.sh`（会 `npm ci` 清 node_modules 并重建 dist，对正在运行的开发服务有副作用，需用户单独授权）。

### P2-T2：首次启动配置引导

**来源**：原 P2 范围

**目标**：首次启动弹出配置向导（LLM key → 角色选择 → 语音供应商 → 完成）。

**改动范围**：
- 前端新增 `SetupWizard` 页面/组件
- 后端 `GET /api/setup/status` 返回未配置项
- 引导完成后写入 `data/settings.local.json`（密钥不进仓库配置）

**验收**：无配置时自动进入向导；完成后进入主页。

**实际落地**：✅ 已完成 —— `services/ai-service/app/api/settings.py:288` `GET /api/setup/status`、`apps/web/src/App.tsx:1756` `SetupWizard`、测试 `services/ai-service/tests/test_settings_api.py:255`。范围偏差：只有 2 步（LLM 必填 → 语音可选可跳过），无「角色选择」步；完成标记写入 `data/settings.local.json`（`services/ai-service/app/config.py:163`）而非 `config/settings.yaml`，这是刻意的。

### P2-T3：能力汇总与故障诊断

**来源**：原 P2 范围

**目标**：主页仪表盘显示能力状态 + 一键诊断。

**改动范围**：
- `/api/health` 扩展：返回每项能力状态 + 修复建议
- 前端主页 Dashboard 卡片（LLM/STT/TTS/Codex/Browser/记忆）
- 失败项显示修复入口按钮

**验收**：Dashboard 显示所有能力状态；Codex 未安装时显示修复指引。

**实际落地**：✅ 已完成 —— `services/ai-service/app/api/health.py:103` `_diagnostics`（中文 detail + `fix_hint`/`fix_action`）、`apps/web/src/App.tsx:1569` 卡片与「去修复」跳转、测试 `services/ai-service/tests/test_health.py:46`。偏差：诊断项合并为 4 类（llm/voice/memory/agents），非本卡列的 6 项；仅在有诊断项时渲染。

### P2-T4：Persona 预设模板

**来源**：Voice-Companion-Bundle 建议 1

**目标**：`config/personas/default.yaml` 增加 `work / companion / service` 三套预设。

**改动范围**：
- persona schema 增加 `preset` 字段
- 预设只负责稳定底座，用户修改走覆盖层
- 三层：仓库默认 → 用户配置覆盖 → 运行时临时覆盖
- 预设切换 = 替换 system prompt 核心段，不动用户自定义

**验收**：切换预设后角色行为变化；用户自定义不被预设覆盖。

**实际落地**：✅ 已完成（2026-09-16 修复）—— 原 `services/ai-service/app/core/persona_prompt.py` 只在 `profile` 完全为空时才用预设，而 `config/personas/default.yaml:35` 有完整 profile → `preset: work` 是死字段；已改为「预设作底座 + profile 非空字段覆盖」（`services/ai-service/app/core/persona_prompt.py:105`），并新增 3 个测试（`services/ai-service/tests/test_persona_prompt.py:88` `test_preset_fills_missing_profile_sections`、`:99` `test_full_profile_overrides_preset`、`:106` `test_unknown_or_blank_preset_is_ignored`）。已实测默认角色提示词零变化（6 段全来自 profile，无预设文本泄漏）。遗留：无切换预设的 API/UI（`PersonaPayload` 无 preset 字段），转 V2。

### P2-T5：音色/形象后台任务状态机

**来源**：Voice-Companion-Bundle 建议 4

**目标**：`scripts/persona_asset_import.py` 补齐任务模型。

**改动范围**：
- 音色克隆：提交参考音频+逐字文本 → 后台处理 → 完成/失败 → 切换
- 形象导入：提交素材 → 后台规范化 → 完成/失败 → 切换
- 复用 AgentRun 任务状态模型（`pending → running → completed/failed`）

**验收**：音色克隆任务提交后可查进度，完成后可切换。

**实际落地**：⚠️ 部分完成 —— `scripts/persona_asset_import.py` 已有状态机 + 合法流转表（`:32`）、JSON 落盘 `data/persona-tasks/`、CLI（`:249`，含 `--self-test` 已实测通过）；未复用 AgentRun，未接 API/前端，进度只能在命令行看。

### P2-T6：AvatarDriver 字段预留

**来源**：Voice-Companion-Bundle 建议 2

**目标**：persona schema 增加 `avatar_driver: procedural_2d`，一行 YAML，零依赖。

**改动范围**：
- `packages/contracts/` persona schema 加字段
- `config/personas/default.yaml` 加默认值
- 当前唯一有效值 `procedural_2d`（即现有 ExpressionEvent + 挂件 CSS）
- 未来 V2 扩展 `video_stream` 时状态机不动

**验收**：persona 加载不报错，现有挂件表现不变。

**实际落地**：⚠️ 部分完成 —— 仅 `config/personas/default.yaml:13` 一行 `avatar_driver: procedural_2d`，contracts 双端都没有该字段（`packages/contracts/py/deskmate_contracts/character.py:13` 及 ts 对应文件），目前无读取方。符合「V1 零依赖预留」意图，但 contracts 那半句未做。

---

## 执行顺序

```
P1-T1（TTS 分块）→ P1-T2（短播报，依赖分块）
P1-T3（记忆提示）、P1-T4（模式自适应）并行
→ P1 验收

P2-T1（安装脚本）→ P2-T2（配置引导）
P2-T3（能力汇总）、P2-T4（预设模板）并行
P2-T5（后台任务）、P2-T6（字段预留）并行
→ P2 验收
```
