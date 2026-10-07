# Step 9 Spec: V1 UI Polish

Status: in progress 2026-09-07. The desktop widget interaction layer is complete for this pass and paused until character-card testing; the page-level beautification steps below remain open.

## Goal

Turn the current functional V1 interface into a coherent, polished workbench for a role-based local AI assistant. UI polish should improve readability, hierarchy, status clarity, responsive behavior, and character expression without adding V2 features such as Live2D, 3D, or a marketing landing page.

## Timing

Run Step 9 after Step 8 automated regression and real Codex acceptance, and before the final macOS/Windows manual release pass. Desktop launch, microphone permission, and Windows checks should be repeated after visual changes.

## Design Direction

Recommended visual direction:

- Qiling is a desktop workbench with character, not a toy desktop pet dashboard.
- Default content should feel calm, dense enough for repeated work, and clearly organized.
- Primary pages are functional surfaces; avoid oversized hero text, decorative card grids, or tutorial copy.
- Character/status can appear on Home and in widget states, but should not interrupt long-form content.
- Use local-first signals: local service status, executor availability, memory mode, permissions, and run state should be visible where relevant.

## Scope

### A. Design Foundation

- Consolidate visual variables in CSS: colors, type scale, spacing, borders, focus states, status colors.
- Align sidebar, content bands, cards, buttons, inputs, tables/lists, notices, and empty states.
- Keep card usage meaningful: repeated items and framed tools only; avoid page sections rendered as nested floating cards.
- Ensure buttons use clear commands or icons where appropriate; keep stable hit areas and disabled states.

### B. Page-by-Page Polish

1. Home: current role/state, service health, active task, recent memory, quick entry points.
2. Chat: conversation focus, streamed content readability, voice state, input and stop controls.
3. Memory: overview, search, document editing/delete paths, Obsidian mode visibility.
4. Knowledge Base: search status, available/configured vault state, empty results.
5. My Agents: executor status, unavailable explanations, task queue, real run/progress/approval/cancel controls.
6. Settings: model, voice, persona, memory, permission, and visual settings with clear grouping.

### C. Desktop Shell and Widget

- Share the same status color/state language with the web UI.
- Improve launcher status and error states.
- Keep widget transparent, small, draggable, and readable on both light and dark desktop backgrounds.
- Keep the 2D state animation as V1-appropriate; do not convert to Live2D/3D in this step.

## Non-goals

- Live2D / 3D character rendering
- Full voice real-time duplex UI
- Theme market or user asset market
- Marketing landing page
- Backend architecture changes

## Acceptance

1. All current pages remain usable and reachable.
2. Desktop and 390px mobile viewports have no horizontal overflow or incoherent overlap.
3. Long task/error/memory text wraps cleanly inside its container.
4. Disabled, running, awaiting approval, completed, failed, and unavailable states are visually distinct.
5. Text and controls remain readable under the current font stack and default theme.
6. Web/Desktop typecheck and `./scripts/check.sh` still pass.
7. After UI work, rerun Step 8 macOS manual checks and browser smoke test.

## Suggested Execution Order

1. Visual audit and fixed design tokens.
2. Shared layout/sidebar and Home.
3. Chat and long-form content.
4. Memory/Knowledge Base.
5. My Agents and task states.
6. Settings.
7. Desktop launcher/widget consistency.
8. Regression and manual smoke.

## 2026-09-07 Progress

Completed (widget shell):

- Compact transparent Tauri widget: `280x304`, frameless, always-on-top, bottom-right placement, draggable character stage.
- Character-stage entry interactions: click activates, double-click opens main UI, Space opens the mini input bar.
- Short-reply bubble is driven only by the widget's own text/voice turn; conversation events from other UI sources no longer echo into the widget.
- Silent/listening mode drops invalid STT audio without visible “语音识别失败” spam.
- The activation ring only appears while the input bar is open; drag no longer leaves a permanent circle. Esc, clicking the character, or blur closes the input bar.

Still open:

- Page-level polish for Home / Chat / Memory / Knowledge Base / My Agents / Settings.
- Responsive/overflow verification at desktop and 390px mobile viewports.
- Character-card testing follow-up for widget asset, animation, movement, and character-specific visual tuning.
- Final Step 8 macOS manual items and Windows regression after visual work settles.

## 2026-09-09 Progress（六页视觉打磨）

Completed (page polish):

- Home / Chat / Memory / Knowledge Base / My Agents / Settings 六页视觉已全部收口：统一状态胶囊语义（ok/bad/warn/muted/品牌色）、卡片圆角与描边配方、空态与未配置提示、命中高亮、长文本 `.break-anywhere` 折行、滚动条 `.scroll-thin` 与焦点描边。
- 移动端布局修复：外层 `flex` 改 `flex-col md:flex-row`，移动顶栏 `w-full`，`main` 加 `w-full md:flex-1`，消除窄屏把内容挤出的 604px 横向溢出。
- 响应式验收：390px 与 1440px 两档逐页 DOM 审计，六页 `docScrollW ≤ viewport`、无页面级横向溢出、无越界未裁剪元素；移动端导航为可横向滚动的胶囊条（点选自动滚入视口），属预期设计。
- 语音噪音修复：`apps/web/src/alwaysListen.ts` 与 `apps/desktop/src/voiceCapture.ts` 增加共享 AudioContext 已关闭守卫，快速进出对话页不再产生 “not useful when context is closed” 告警；常开监听实际启用时仍会保留浏览器原生的 ScriptProcessorNode 弃用提示（待后续 AudioWorklet 化，非本轮范围）。
- 回归：`./scripts/check.sh` 全绿（78 passed + Web/Desktop typecheck）；逐页截图存档于 `step9-review/`。

Still open (unchanged):

- Character-card testing follow-up for widget asset, animation, movement, and character-specific visual tuning.
- Step 8 macOS 真机人工项（launcher 拉起、麦克风授权/拒绝降级、Codex 不可用 banner、退出进程回收）已完成，只剩 Windows 回归；清单见 `docs/STEP8-RELEASE-DEGRADATION.md` 与 `docs/WINDOWS-MIGRATION-2026-09.md`。

## 2026-09-13 Progress（角色卡调优 + 视觉回归）

Completed（角色卡调优）：

- 新增 `apps/web/src/VoiceSelect.tsx`：音色下拉按种类分组（系统 / 克隆 / 预置）并带关键词过滤，
  设置页模型档案编辑器与角色卡共用。此前 MiniMax 一个账号就是 300+ 项扁平下拉，克隆音色沉在最后。
- 角色库卡片音色徽标改为优先显示供应商音色表里的中文名（如「软软女孩」），与下拉框保持一致；
  拿不到名单时仍回退到 ID 尾段，tooltip 保留完整音色 ID。
- 角色卡切换走查（真机浏览器）：点「启用」后 `active_persona_id`、语速、唤醒角色名整套切换生效，
  再切回原角色可完整还原；未保存改动时启用其它角色会先确认。

Completed（视觉回归）：

- 八页（主页 / 对话 / 角色卡 / 记忆 / 知识库 / 我的智能体 / 设置 / 关于）在 1440×900 与 390×844 两档逐页审计：
  `documentElement.scrollWidth ≤ viewport`，排除可横向滚动祖先外无越界元素；移动端导航横向滚动属预期设计。
- 新标签页走查八页控制台 0 报错；仅保留已知的 ScriptProcessorNode 弃用提示。
- `./scripts/check.sh` 全绿（154 passed + Web/Desktop 类型检查）。

顺带修掉的回归噪音：

- `tests/test_activation.py` 的接口级用例此前读开发者本地角色配置，本机启用「蓝猫」后
  「你好，千问」被判成 chat，长期红。改为用临时 `QILING_HOME` 固定角色名，测试不再随环境漂移。

## 2026-09-13 晚（挂件角色化表现收口）

人工验收结论：情绪动效可分辨、角色切换正常、气泡正常。过程中修掉两个真问题：

- **情绪从未到达挂件（根因，非动效参数）**：`EventHub.publish()` 先 `to_ws_dict()` 序列化、
  后跑 `on_publish` 钩子，而 `expression` 正是钩子在发布时补上的，导致 WS 广播载荷里
  `expression` 恒为 `null`：HTTP 响应有情绪、挂件订阅拿不到，角色只剩基础呼吸。
  钩子前置到序列化之前修复；新增 `test_expression_broadcast_over_ws` 用例
  （回退修复即 `KeyError` 失败）。旧用例只断言 HTTP 响应体，因此漏掉了这个 bug。
- **播报无法打断**：挂件缺少「播报中点击 = 停止」路径。现在点击已播报的挂件即停播 +
  气泡「已打断」+ 上报 `speech.interrupted`，与主界面 `⏹ 停止` 等价。

动效按运动轴重排，不再互相混淆（呼吸 3.6s 纯缩放 2.4%；浮动 2s 纵向 12px；
摇摆 1.5s 横向 5px + 旋转 3.5°；弹跳 0.85s×2 纵向 18px + 8% 压缩；抖动 0.3s×4 横向 6.9px）。
一次性情绪（点头/弹跳/抖动）播完由前端回落 `neutral`，避免后端不复位情绪导致无限循环。

「听/静/无」语音提示改为锚定角色形象右上角（`calc()` 基于 `--mascot-size`），
随角色尺寸缩放，不再钉在舞台角落；角色尺寸收敛为单一来源（舞台注入 CSS 变量）。

频率（摇摆/浮动周期）保留为 CSS 实现参数，不对用户暴露——V2/V3 动效会持续增加，
一旦进设置 UI 就成了兼容负担；角色差异化的载体是角色卡与素材，不是节奏旋钮。
角色卡 `presentation.animations` 保持预留、暂不接线。

Still open:

- Windows 回归待真机执行（`WORKBUDDY-WINDOWS-MIGRATION.md` §10 清单 / §14 完成标准）。
  macOS 人工项已全部收口：麦克风降级两项按日常使用确认，不再单列。
