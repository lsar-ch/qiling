# Step 9 Spec: V1 UI Polish

Status: in progress 2026-09-07. The desktop widget interaction layer is complete for this pass and paused until character-card testing; the page-level beautification steps below remain open.

## Goal

Turn the current functional V1 interface into a coherent, polished workbench for a role-based local AI assistant. UI polish should improve readability, hierarchy, status clarity, responsive behavior, and character expression without adding V2 features such as Live2D, 3D, or a marketing landing page.

## Timing

Run Step 9 after Step 8 automated regression and real Codex acceptance, and before the final macOS/Windows manual release pass. Desktop launch, microphone permission, and Windows checks should be repeated after visual changes.

## Design Direction

Recommended visual direction:

- DeskMate is a desktop workbench with character, not a toy desktop pet dashboard.
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
- Step 8 macOS 真机人工项（launcher 拉起、麦克风授权/拒绝降级、Codex 不可用 banner、退出进程回收）与随后的 Windows 回归。清单见 `docs/HANDOVER-2026-09-09.md`。
