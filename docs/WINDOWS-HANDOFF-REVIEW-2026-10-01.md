# Windows 回传复验评估（2026-10-01 包）— mac 侧结论

> 来源：`deskmate-handoff-2026-10-01.zip`（WorkBuddy / Windows 只读复验，未改产品代码）
> 被测基线：`8a1e922` + 9/30 轮工作区改动
> 本文只记 mac 侧核对后的结论与处置，不复述回传全文（原文见包内 `README-HANDOFF.md`）。

## 1. 一句话

两条根因（VRM T-pose、P1 refusal）成立；三条复验（P3/P5/P6）判据客观、通过；
回传中「clip 不存在」是**打包剔除造成的误判**——配置无需改动。

## 2. 已处置

| 项 | 处置 | 位置 |
|---|---|---|
| VRM 闪现 T-pose | `play()` 补 `action.clampWhenFinished = true` | `apps/desktop/src/widget/VrmStage.tsx:234` |

根因链（mac 侧复核）：`completed`/`emotion=success` → `trigger="success"`
（`apps/desktop/src/widget/actions.ts:56,78`）→ `Widget.tsx:1714 activeTrigger`
→ `VrmStage.tsx:423` 调 `play()` → `success` 不在 `config/personas/k81.yaml` 的 `loop_triggers`
→ 走 `LoopOnce` → 旧 `play()` 未设 `clampWhenFinished`（而 `playOneShot()` 设了）
→ 播完动作权重归零 → 落回绑定姿态，闪 1 帧。

`clampWhenFinished` 对 `LoopPingPong` 是 no-op，故可无条件设置；这一处同时覆盖 `error`
等所有非循环 trigger（根因修复，非逐点打补丁）。

验证：`./scripts/check.sh` → 291 passed + web/desktop typecheck 通过。
最终判据仍是真机逐帧复现（拍手时不再出现 T-pose），测法见回传包 §6.1。

## 3. 更正：缺失 clip 是打包问题，不是配置问题

回传 §B.1 与待办 Q3/Q4 把 `idle_yawn` / `speak_alt` / `success_happy` 判为
「配置引用了不存在的 clip」——在 mac 仓库**不成立**：

- `data/motion-library/female/` 完好（20 个 vrma），这三个 clip 都在；`git ls-files data/motion-library` = 41 项。
- 404 的唯一成因是 9/30 源码包规则 `data/ 仅保留 data/persona-assets/` 剔除了 `motion-library/`。

处置：**不改配置、不补资源**。改 Windows 打包排除规则，让 `data/motion-library/` 随包即可。
`vrm.library: female`（指向共享库）+ persona 自带 vrma 是设计意图，勿动。

## 4. 仍然开放

| # | 事项 | 状态 |
|---|---|---|
| Q1 | WorkBuddy CLI 独立进程的登录态来源 | ✅ 已定位并处置，见 §4.1 |
| Q5 | `/api/health` ready 是否加真实 `session/prompt` 探针 | ✅ 已实现为**后台**探测（见 §4.4） |
| Q6 | `_spawn` 默认 cwd 与 CLI 自身日志文件名 | ✅ 定性为文档问题（见 §4.3），不改代码 |
| Q7 | 关闭「语音激活」后挂件仍自动派发对话 | mac 侧**未复现**且已实测证实麦克风关闭（见 §4.2）；待 Windows 复测 |
| F | 运行按钮 busy 时静默忽略 | ✅ 已加提示，见 §4.6 |
| 3 | `tasks/` 无过期回收 | ✅ 已加终态 + 过期回收，见 §4.6 |
| 4 | `voice/recognize` 422 持续重试 | ✅ 已加发声闸门，见 §4.6 |

### 4.1 Q1 定位：CLI 登录态来自 WorkBuddy 自身，DeskMate 不该替它猜环境

mac 侧复核（本机装了 WorkBuddy，实测确认）：

- CLI 的登录态由 WorkBuddy 自己持久化在 `~/.workbuddy/`（`storage/skeleton/account-snapshot.json`、
  `security/`、`local_storage/`），DeskMate **不需要注入任何凭据**——原判断成立。
- 真正可疑的是 DeskMate 自己塞的环境变量：`_child_env()` 把
  `CODEBUDDY_INTERNET_ENVIRONMENT` 硬编码成默认 `internal`。CLI 自带文档写明取值
  必须是 `internal`（中国版）/ `ioa`（iOA 企业版）/ `cloudhosted` / `selfhosted`，
  填错会 **401 endpoint mismatch** ——正好对应 Windows 侧看到的
  `fetch auth accounts error: AxiosError: 401` + `account list is empty`。

处置：`workbuddy.py` 改为**未显式配置就不注入**该变量，让 WorkBuddy 自身持久化状态决定；
`config/agents.yaml` 的 `internet_environment` 仍可显式覆盖。本机实测：设置与不设置
`internal` 都能完成 `initialize` + `session/new` 握手（不消耗积分）。

### 4.2 Q7 复核：mac 侧未复现

2026-10-01 真机（mac，`tauri dev`，挂件走 vite dev server）：关闭「启用语音激活」并保存后，

- 服务端 `GET /api/voice/status` → `activation.enabled=false`，设置已生效；
- 保存后挂件连接（端口 56772）主动 `GET /api/voice/status` → 说明 `settings-changed` 广播已送达；
- 整段日志 + 追加 60s 实时监视：`voice/recognize` / `voice/intent` / `chat/stream` **增量为 0**。

结论：mac 上 `Widget.tsx` 的激活闸门有效，麦克风被停掉。Windows 侧的现象需另找解释，
候选：(a) Windows 上 `listener.stop()` 未真正释放麦克风（平台差异）；(b) 统计窗口混入了保存前的调用。
用法：让挂件在关闭激活状态下对着麦克风说话，若日志仍无 `voice/recognize`，即可判定麦克风确已关闭。

### 4.3 Q6 定性：CLI 日志按 cwd 命名，属「怎么找」而非「没落盘」

mac 实测（本机 WorkBuddy）：

- WorkBuddy CLI 自身日志路径为 `~/.workbuddy/logs/<日期>/<workspace>__<hash>.log`，
  其中 `<workspace>`/`<hash>` 由 **CLI 进程的 cwd** 决定。

> **更正（2026-10-01 复核）**：回传原判「project 为 null 时 cwd 落 home」**不成立**。
> 真实任务链路上 `request.cwd` 永远非空——`runtime.py:_resolve_cwd()` 有项目就返回项目根，
> 否则返回 `data_dir.parent`（仓库根），`_spawn` 的 `cwd or Path.home()` 兜底根本走不到。
> 所以 Windows 侧看到的 `desktop-assistant__<hash>.log` 正是仓库根，日志是写了的，
> 只是文件名按目录名而不是按任务命名。真正会把 home 当工作区的是**探测路径**（见下）。

- DeskMate 另外把 CLI 的 stderr 抓在 `<logs_dir>/<task_id>/workbuddy-acp-stderr.log`；
  CLI 在 ACP 模式 stderr 常为空，所以那份通常是空的。
- 附带发现：CLI 只有在 WorkBuddy 桌面端/daemon 在跑时才写上述日志；本机单跑 CLI
  做 `initialize`+`session/new` 探测时，`~/.workbuddy/logs/` 当天没有新增文件。

处置：**任务路径不改代码**（改 cwd 会动到 CLI 工作目录语义，收益不抵风险），把定位规则记在这里。
但**探测路径**确实有问题，已修：见 §4.5。

### 4.4 Q5 落地：后台真实 prompt 探测（不能内联）

问题：`_probe()` 只做 `initialize` + `session/new`，而账号为空时 CLI 照样能建会话、
却在 `session/prompt` 回 `refusal`——所以旧的 `ready` 证明不了「能真执行」。

关键约束（决定了实现形态）：`/api/health` 被**三重超时**保护——Tauri 服务就绪探测 3s、
前端 `fetchJson` 5s、健康轮询 8s 一次。而本机实测：**一次极短真实 prompt 要 15.1s**。
内联进 health 会直接把健康检查打挂，所以只能放后台。

实现（`services/ai-service/app/agents/workbuddy.py`）：

- `detect()` 仍走原握手快路径，`/api/health` 延迟不变；
- 新增 `_run_exec_probe()`：后台跑 `initialize` + `session/new` + 极短 prompt
  （`只回复两个字：就绪`，不碰文件、不调工具），结果缓存 300s；
- 命中 `stopReason == "refusal"` → 状态从 `ready` 降级为 `auth_required`
  （前端已有现成文案：「已安装但账号未登录或登录已失效，登录后重新检测」）；
- `invalidate_probe()`（用户点「重新检测」）同时清掉真实探测缓存。

本机实测（真实 WorkBuddy CLI）：快路径 **3.8s** 返回 ready（与改动前一致，无回归），
后台探测 **13.2s** 完成后结论刷新为「CLI 可启动、账号可提交真实任务」。
`./scripts/check.sh` → 294 passed。

### 4.5 跨平台路径审计（macOS / Windows / 非系统盘）

起因：macOS 与 Windows 路径形态不同，且 Windows 常把软件装到 D 盘，联动 WorkBuddy CLI
必须吃得住这两种情况。

**已具备（无需改动，且有测试）**：

- 安装发现不猜盘符：`windows_install.py` 扫「添加或删除程序」注册表（HKLM 64/32 位 + HKCU）
  取 `InstallLocation` / `DisplayIcon`，再枚举 `GetLogicalDrives()` 里所有 `DRIVE_FIXED` 盘
  拼 `Program Files` 候选——`D:\Program Files\WorkBuddy` 这类换盘安装能命中（WI-05 真机已验证）。
- CLI / 桌面端 exe 的反推全部走**相对位置**（`<root>\resources\app.asar.unpacked\cli\bin\codebuddy`
  上溯到 `<root>\WorkBuddy.exe`），不含盘符硬编码；
- 路径拼接一律用 `pathlib`，没有手写分隔符。

**已修（本次）**：

- 两个探测（`_probe` / `_run_exec_probe`）原先用 `str(Path.home())` 当 CLI 工作目录，
  等于让 CLI 把整个用户主目录当 workspace 扫一遍（Windows 主目录尤其大），
  还顺带把探测日志写成主目录哈希名；
- 改为 `_probe_workdir()`：固定落在系统临时目录 `deskmate-workbuddy-probe`，
  `_spawn` 的兜底也从 `Path.home()` 改成同一个目录。跨平台行为一致，日志名可预期。
- 测试 `test_workbuddy_probe_uses_dedicated_workdir_not_home` 钉住「探测不碰主目录」。

**未做（有意）**：任务执行的 cwd 仍由 `_resolve_cwd()` 决定（项目根或 `data_dir.parent`），
那是执行语义，不能为了日志好看去动。

### 4.6 回传包 §7 剩余三条处置（2026-10-01）

**#4 `tasks/` 无过期回收** —— 根因是每条输入（含常开监听送来的随口一句）都会
`classify_task_input` 落一条任务，纯问答没有执行步骤，永远停在 `queued`，任务台只增不减。

- `api/chat.py`：`category == "answer"` 的纯问答在本轮答完后落 `completed`（它本来也没有可执行步骤）。
- `routing/store.py`：`TaskStore` 增加 `stale_hours`（默认 24h）过期回收，启动加载时与每次
  `put` 前各清一次**长期停在 `queued`** 的任务；`running` / `awaiting_approval` / 终态一律保留，
  不动执行中的链路。
- 测试：`test_chat_answer_task_reaches_terminal_state`、`test_task_store_reclaims_only_stale_queued_tasks`。

**#5 `voice/recognize` 422 持续重试** —— 422 有两个来源（非 RIFF 音频、STT 返回空文本），
客户端产出的一定是 RIFF，实际全是「空文本」：能量 VAD 被噪声误触后，把一段没人说话的音频
送去识别。这是调参 + 空提交兜底，不是崩溃。

- `apps/desktop/src/voiceCapture.ts` 与 `apps/web/src/alwaysListen.ts`（两端参数本就要求一致）：
  新增 `MIN_VOICED_MS = 300`，统计段内真正高于 `START_RMS` 的累计时长，不足则不发起识别请求
  （省一次网络往返和一条 422 日志）。阈值本身不动，避免安静说话被当静音丢掉。
- 客户端本来就对「未识别到有效语音内容」静默跳过，本次是把无效片段挡在上传之前。

**#6 运行按钮 busy 时静默忽略** —— `App.tsx` 的 `startRun` / `stopRun` / `decideAction`
三处 `if (!run || busyRun) return;` 拆开：忙时不再静默返回，改为写 `taskNotice`
（「有执行操作正在进行，请等它结束再试。」）。

验证：`./scripts/check.sh` → **297 passed** + web/desktop typecheck 通过；
`apps/web` 构建产物已更新（主界面加载 `dist`）。

### 4.7 `running` 无回收 + P3/P5/P6 测试落位（2026-10-01）

**`running` 怎么判定** —— 不看时长，看「进程还在不在」。长任务的耗时本来就不确定，
任何隐藏计时器都可能把正常跑着的长任务判死。同类项目的做法都是**租约/心跳**而非总时长：

- Celery / Sidekiq：worker 启动时按 visibility timeout 回收「active 但没人认领」的任务；
- Temporal：activity heartbeat + heartbeat timeout，心跳停才判死（总时长是另一个可选旋钮）；
- Kubernetes Job：靠 pod 生命周期，重启即换新进程，旧状态由控制器对账。

DeskMate 的编排器就在服务进程内，所以现成信号是 `AgentRunManager._tasks`（内存里的
asyncio 任务表）。**服务一重启，表必然是空的**，磁盘上还写着 `queued`/`running` 的 run
按定义就是孤儿——不需要猜时间。处置（`agents/runtime.py:_reconcile_orphaned_runs`）：

- 在 `AgentRunManager.__init__`（即 app 创建时）扫一遍 run store，把 `queued`/`running`
  的 run 与对应 task 一起落 `failed`，error 写「服务重启，任务已中断；可重新运行。」；
- 终态 run 一律不动；
- **不引入任何超时杀人**。现有的 900s stale sweeper 继续只做「无进展提醒」，不落终态。

测试：`test_restart_marks_interrupted_runs_failed`（跑着的 run 判失败、已完成的保持完成）。

**P3/P5/P6 的测试落位**（原状态：三条只有行为层验证）：

| 项 | 现有单元/集成覆盖 |
|---|---|
| P3 | 服务端热更新本就covered：`test_settings_api.py` 断言 `PUT /api/settings` 后 `GET /api/voice/status` 的 `auto_speak` 已翻转。客户端「广播→快照刷新」仍只能行为层验（挂件侧无轮询，钩子是 Tauri `settings-changed` 广播）。 |
| P5 | 新增：`test_chat.py` 的长/短回复用例追加断言 `conversation.completed.payload.expand_ui` 为 `true`/`false`。挂件两条自动展开路径里，事件那条此前从未被单独验证——正好补上。 |
| P6 | 新增 vitest：`apps/desktop/src/widget/motion.test.ts` 钉住 `triggerFor("completed") → "success"`（T-pose 闪现的动作入口）与 `pickAction` 的冷却/权重/loop 默认值，并跑通模块自带 `demo()` 自检。 |

**新增测试基建**：`apps/desktop` 引入 `vitest`（devDependency，无 jsdom / 无 testing-library，
只测纯函数），`npm run test` 已接进 `./scripts/check.sh`。

## 5. 关联

- 回传原文：`deskmate-handoff-2026-10-01.zip`（外部包，未入库）
- 主题入口：`docs/WINDOWS-MIGRATION-2026-09.md`
- 9/30 轮任务书：`WORKBUDDY-WINDOWS-RECHECK-2026-09-30.md`
