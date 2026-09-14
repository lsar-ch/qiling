# Windows 迁移问题归档 — 2026-09-13

> 记录时间：2026-09-13（2026-09-14 在 macOS 侧补记 WI-05 修复）
> 环境：Windows 10.0.19045.6464，Python 3.12.10，Node v24.21.0，npm 11.19.0
> 源码包：`DeskMate-Windows-src-2026-09-13.zip`（HEAD `76b6c6c`）
> 项目目录：`D:\Projects\desktop-assistant`
> 处置原则：**如实记录，不隐藏问题，不为通过测试而修改代码**

---

## 0. 结论速览

| 编号 | 问题 | 级别 | 状态 | 是否产品缺陷 |
|---|---|---|---|---|
| WI-01 | `test_resolve_codex_command_requires_executable_permission` 在 Windows 失败 | 中 | **已修复**（2026-09-14，改为平台分支断言） | 否，测试平台假设问题 |
| WI-02 | `test_unwritable_vault_fails_quietly` 在 Windows 失败 | 中 | **已修复**（2026-09-14，补跨平台用例） | 否，测试平台假设问题 |
| WI-03 | npm audit 报 2 个漏洞（vite high + esbuild moderate） | 中 | 未修复，见 `DEPENDENCY-VULNERABILITIES.md` | 否，依赖版本问题 |
| WI-04 | npm 11 拦截 esbuild postinstall 脚本 | 低 | 无需修复（实测无影响） | 否，环境噪音 |
| WI-05 | WorkBuddy 自动检测在非 C 盘安装时失效 | 中 | **已修复**（2026-09-14，待 Windows 真机复验） | **是，平台路径覆盖不全** |
| WP-01 | 页面无「关闭自动播报回复」开关，第 10 节第 11 项无法验证 | 中 | **已修复**（2026-09-14，设置页补开关） | 非迁移问题，缺 UI |
| WP-02 | 长回复自动打开浏览器只进主页，不进对话页 | 中 | **已修复**（2026-09-14，hash 路由 + 带片段打开） | 非迁移问题，缺 URL 路由 |
| WP-03 | 右键退出程序后已打开的浏览器不关闭 | 中 | **已缓解**（2026-09-14，前端降级提示；不真关浏览器） | 非迁移问题，浏览器未纳入进程管理 |

**第 8 节检查结论：153 passed / 2 failed，2 项失败均为 POSIX 权限语义缺失，无真实功能缺陷。**

> 2026-09-14 复核：WI-01 / WI-02 已收口为平台分支断言与跨平台用例（见各自「修复记录」），
> macOS 全量基线 **161 passed**（原 160 + WI-02 新增 1 个跨平台用例）。

---

## WI-01 — codex 可执行位测试在 Windows 失败

### 现象

```
FAILED tests/test_agent_config.py::test_resolve_codex_command_requires_executable_permission

    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o644)
>   assert resolve_codex_command(str(binary)) is None
E   AssertionError: assert 'D:\\...\\codex' is None
tests\test_agent_config.py:97: AssertionError
```

### 根因

测试用 `chmod(0o644)` 去掉 POSIX 可执行位，期望「不可执行的命令 → 返回 None」。
但 **Windows 没有 POSIX x 位**：`os.chmod` 在 Windows 上只影响只读标记，
文件依然可被 `CreateProcess` 执行。因此 `os.access(path, os.X_OK)` 恒为真。

而产品源码是**刻意**这样写的（`app/agents/codex.py::_is_file_binary`）：

```python
if sys.platform == "win32":
    return True          # 注释原文：Windows 以文件存在为准（能否运行交给探测）
return os.access(path, os.X_OK)
```

**产品代码行为正确且符合设计意图**，是测试用例的跨平台假设不成立。

### 影响评估

- 不影响 Windows 上任何实际功能。
- 在 macOS 上该测试应正常通过（POSIX 语义成立）。
- 潜在收益：该测试在 Windows 上**没有验证能力**，属"假绿"（若加 skip）或"假红"（现状）。

### 处置（Windows 本轮：按 B 方案如实记录，不改）

Windows 侧保持测试原样。根治方向有两条：

1. 按平台分支断言：Windows 上断言「文件存在即返回路径」，POSIX 上断言「无 x 位返回 None」；
2. 或加 `@pytest.mark.skipif(sys.platform == "win32", ...)` 并**在 CI 报告中显式标注为平台跳过**（不建议单独使用，会让问题从视野里消失）。

### 修复记录（2026-09-14，macOS 侧）

采用上面的**方案 1（平台分支断言）**，产品代码零改动：

```python
if sys.platform == "win32":
    assert resolve_codex_command(str(binary)) == str(binary)   # 文件存在即可执行
else:
    assert resolve_codex_command(str(binary)) is None          # 无 x 位不算可执行
```

这样测试在**两个平台上都真实断言**（Windows 走「存在即通过」分支、POSIX 走「x 位」分支），
不使用 skip，不存在"假绿"。文件：`services/ai-service/tests/test_agent_config.py`。

---

## WI-02 — 只读目录测试在 Windows 失败

### 现象

```
FAILED tests/test_vault_mirror.py::test_unwritable_vault_fails_quietly

    vault = tmp_path / "vault"
    vault.mkdir()
    vault.chmod(0o500)               # 期望：只读目录，写不进去
    ...
    assert body["mirror_dir_exists"] is False
E   assert True is False
tests\test_vault_mirror.py:150: AssertionError
```

### 根因

同样来自 POSIX 权限语义缺失。`chmod(0o500)` 在 Windows 上**不会阻止创建文件** ——
目录能否写入由 ACL 决定，`os.chmod` 对目录写权限几乎无效。
因此程序成功创建了镜像目录（`mirror_dir_exists = True`），这与产品的"不可写时静默跳过"设计并不冲突，
只是**测试无法在 Windows 上构造出"不可写目录"这个前提**。

### 影响评估

- 不影响实际功能。真实场景下的目录不可写（如 ACL 拒绝）仍会走静默跳过逻辑。
- 但**该失败路径在 Windows 上从未被真实验证过**，属覆盖盲区，值得记录。

### 处置（Windows 本轮：按 B 方案如实记录，不改）

Windows 侧保持测试原样。要在 Windows 上真正构造「不可写目录」，需改用 **Windows ACL**
（如 `icacls <dir> /deny <user>:(W)`），而不是 `chmod`——跨平台成本高，不值得。

### 修复记录（2026-09-14，macOS 侧）

产品代码零改动，把「镜像目录建不出来要静默降级」这条行为**改成跨平台可构造**：

1. 抽出共用断言体 `assert_mirror_write_is_skipped_quietly(vault)`
   （状态接口 200、`mirror_dir_exists` 为 False、写入请求仍 200，
   并读回 `GET /api/memories/docs/L3/progress` 证明**本地记忆仍真实写入**——
   否则「整个请求空操作也返回 200」同样能通过，等于没验证降级语义）；
2. 新增 `test_mirror_dir_creation_failure_fails_quietly`：用**同名文件占住镜像目录名**
   （把 `vault/DeskMate` 写成文件），`mkdir` 必然失败——POSIX 与 Windows 都成立，
   顺带证明原始文件未被覆盖；
3. 原 `test_unwritable_vault_fails_quietly` 更名为 `test_readonly_vault_fails_quietly`，
   在 win32 上 `pytest.skip`（理由写明：行为已由上面的跨平台用例覆盖），POSIX 仍跑 `chmod(0o500)`。

要点：Windows 上不再是「某项失败」或「某项假绿」，而是**新用例真实跑通**、
旧用例显式标注为平台跳过且有等价覆盖。文件：`services/ai-service/tests/test_vault_mirror.py`。

---

## WI-03 — npm audit 依赖漏洞

详见 **`docs/DEPENDENCY-VULNERABILITIES.md`**（含明细、不立即修复理由、三套后续方案）。

摘要：`vite` 5.4.21 → 修复需升 8.3.0（跨 3 个大版本）；影响面限于开发服务器，不影响构建产物与生产运行。

---

## WI-05 — WorkBuddy 自动检测在非 C 盘安装时失效

### 现象

「我的智能体」页面 WorkBuddy 卡片，**留空路径（自动检测）时显示未安装**：

```
状态徽标：未安装
available 否   版本 —   协议 acp
未检测到 WorkBuddy，请在下方填写 WorkBuddy 可执行文件完整路径
未检测到可执行文件
```

### 复现环境

- WorkBuddy 实际安装位置：`D:\Program Files\WorkBuddy\WorkBuddy.exe`
- 系统：Windows 10.0.19045

### 根因

`app/agents/workbuddy.py::_platform_install_candidates()` 在 Windows 上只拼接以下根目录：

```python
roots = [
    Path(os.environ.get("ProgramFiles", "C:\\Program Files")),
    Path(os.environ.get("LOCALAPPDATA", "")),
    Path(os.environ.get("ProgramW6432", "")),
]
hits.append(root / "WorkBuddy" / "WorkBuddy.exe")
hits.append(root / "Programs" / "WorkBuddy" / "WorkBuddy.exe")
```

`ProgramFiles` / `ProgramW6432` / `LOCALAPPDATA` **三者在标准 Windows 上都指向 C 盘**，
因此当用户把 WorkBuddy 安装到 D 盘（安装器允许选择安装盘，本机即为此情况），
所有候选路径全部落空，自动检测必然失败。

补充：WorkBuddy 未注册到系统 PATH，`shutil.which("workbuddy")` / `which("wb")` 同样返回空，
`CODEBUDDY_CODE_PATH` 环境变量也未设置 —— 三条兜底途径全部失效。

### 实测证据

| 探测途径 | 结果 |
|---|---|
| `C:\Program Files\WorkBuddy\WorkBuddy.exe` | MISS |
| `%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe` | MISS |
| PATH 中 `workbuddy` / `wb` | 未找到 |
| `CODEBUDDY_CODE_PATH` | 未设置 |
| `D:\Program Files\WorkBuddy\WorkBuddy.exe` | **存在，但不在候选列表内** |

### 现有可用绕过方式（已验证）

在页面「配置」中显式填入 `D:\Program Files\WorkBuddy\WorkBuddy.exe` 后**完全可用**：

```
状态徽标：可用
available 是   版本 2.137.1   协议 acp
WorkBuddy 已就绪：CLI 可启动、账号已登录，可提交真实任务。
```

并正确写入 `config/agents.local.yaml`：

```yaml
executors:
- name: workbuddy
  config:
    workbuddy_command: D:\Program Files\WorkBuddy\WorkBuddy.exe
```

### 处置

**Windows 本轮不改代码**（保持平台回归的纯净），2026-09-14 转回 macOS 后单独修复。

### 修复记录（2026-09-14，macOS 侧）

新增 `app/agents/windows_install.py`（标准库 `winreg` + `ctypes`，非 Windows 平台直接返回空）：

| 探测途径 | 覆盖场景 |
|---|---|
| 注册表 `Uninstall`（HKLM 64 位 / HKLM WOW6432Node / HKCU） | 安装器注册过的任意盘安装，取 `InstallLocation` 与 `DisplayIcon`；`DisplayName` 同时匹配 `WorkBuddy` / `CodeBuddy` |
| 固定磁盘根目录（`GetLogicalDrives` + `GetDriveTypeW`，只取 DRIVE_FIXED） | 安装器没注册时的兜底，扫 `<盘>:\Program Files\WorkBuddy\WorkBuddy.exe` |

接入点：`app/agents/workbuddy.py::_platform_install_candidates()`，
在原有环境变量候选后追加上述两类候选（原 `if not root` 死代码一并修正）。

优先级不变：页面显式配置 > `CODEBUDDY_CODE_PATH` > PATH > 平台常见位置。
注册表返回的路径仍要过 `_runtime_from_path` / `_is_file_binary` 的存在性校验。

测试（`tests/test_agent_config.py`，macOS 上即可跑）：非 Windows 返回空、
`InstallLocation` / `DisplayIcon` 解析、D 盘候选回归、以及用 winreg 替身跑完整扫描链路
（含三档注册表位置都确实被扫、无关程序不误报）。11 项测试全绿。

**未做的事**：`app/agents/codex.py` 的同类漏检**没有**顺带改。审查发现按 `DisplayName`
含 `codex` 匹配会命中 Codex 桌面端（安装目录里就是 `Codex.exe`），而 Windows 上
`_is_file_binary` 只看文件存在，会把桌面端 exe 当成 CLI 采用，反而制造误报。
要做需要更严格的判据（如探测 `codex --version`），留作独立议题。

**Windows 真机复验仍待下一轮**：在 Win10 机器上跑一次
`python -c "from app.agents.windows_install import registry_candidates as r; print(r(('WorkBuddy',),('WorkBuddy.exe',)))"`
确认能打印出 D 盘路径，再关 WI-05。

### 后续修复建议

不宜硬编码盘符列表，推荐**读注册表**拿到真实安装路径（安装器写入，跨盘通用）：

```
HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*
HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*
    → DisplayName 匹配 WorkBuddy → 取 InstallLocation / DisplayIcon
HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*
```

备选：读取 `App Paths`（`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WorkBuddy.exe`）。
此外可考虑扫描非系统盘根目录（`D:\Program Files\...`）作为弱兜底，
或引导安装器写入 PATH / 用户环境变量 `CODEBUDDY_CODE_PATH`。

### 同类风险

`app/agents/codex.py` 的 `_platform_candidates()` 存在同样模式（只基于 C 盘常见位置），
但 codex 有 `shutil.which("codex")` 兜底，若用户把 codex 装到非 PATH 且非 C 盘位置，也会同样漏检。
建议一并评估。

---

## WP-01 — 页面无「关闭自动播报回复」开关（第 10 节第 11 项无法验证）

### 现象

按 `WORKBUDDY-WINDOWS-MIGRATION.md` 第 10 节第 11 项要求，
「关闭『自动播报回复』后，语音输入仍可用，普通回复不自动播放」——
但在「对话」页面**找不到任何名为「自动播报回复」的开关或设置项**，无法执行该验证。

### 根因（代码核实）

`apps/web/src/ChatPage.tsx` 中语音相关状态只有一个 `voiceMode`：

```typescript
// 语音模式：off（未监听）/ listening（聆听中）/ sleeping（静默，仅唤醒词可打断）
type VoiceMode = "off" | "listening" | "sleeping";
```

**不存在独立的「是否自动播报回复」开关**。且播报硬编码在回复流程中、无条件触发：

```typescript
// ChatPage.tsx — 收到回复后无条件播报
stopSpeaking();
void speak(done.speak_text || done.message);
setNotice(done.short ? "" : "已自动播报摘要，点消息下方 🔊 可朗读全文");
```

### 影响评估

- **非 Windows 迁移问题**，属**需求尚未实现**：该开关在 macOS 上同样不存在。
- 第 10 节第 11 项在本轮**判定为"无法验证"**（不记为通过，也不记为失败）。
- 第 12 项中"关闭自动播报后"的前提条件同样不成立（见 WP-02）。

### 修复记录（2026-09-14，macOS 侧）

**先更正一条根因判断**：`apps/web/src/ChatPage.tsx:251` 与
`apps/desktop/src/components/Widget.tsx:346` 本来就把播报挂在 `voiceStatus.auto_speak` 上，
`config/settings.yaml` 也早有 `auto_speak: true`，`PUT /api/settings` 早就接受
`voice_auto_speak`。真正缺的只有 **UI** —— 设置页没把这个开关暴露出来，
用户无从关闭，所以第 10 节第 11 项无法验证。原判断「播报硬编码、无条件触发」不成立。

改动：

- `apps/web/src/App.tsx` 设置页「语音能力」卡片新增「自动播报回复」复选框，
  绑定 `settings.voice.auto_speak`（与 `voiceMode` 解耦；lite 模式随语音总开关一起禁用）；
- `saveSystem` 的提交体补上 `voice_auto_speak`（PUT 是部分更新，只提交显式字段）。

验证（本机真跑）：设置页取消勾选 → 「保存系统设置」→
`GET /api/settings` 与 `GET /api/voice/status` 均返回 `auto_speak = false`，
而 `enabled` 仍为 `true`（语音输入不受影响，第 10 节第 11 项的前提成立）；
重新勾选保存后恢复 `true`。消息下方的 🔊 手动播报不经 `auto_speak` 判断，关闭后仍可用。

---

## WP-02 — 长回复自动打开浏览器只进主页，不进对话页

### 现象

长回复触发自动打开浏览器时，浏览器确实被拉起，但**停在主页（home），没有进入对话页面**，
用户还需手动点击「对话」才能看到全文。

### 根因（代码核实）

**① Tauri 侧只打开根路径**

```rust
// apps/desktop/src-tauri/src/lib.rs :: open_main_ui
open_url_in_browser(&format!("http://127.0.0.1:{SERVICE_PORT}/"))
//                                        仅根路径，无路由片段
```

**② 前端没有 URL 路由机制**

```typescript
// apps/web/src/App.tsx
const [page, setPage] = useState<PageKey>("home");   // 纯 React state，初始恒为 "home"
```

页面切换完全依赖 `useState`，**不读也不写 URL**（无 hash、无 history API 调用）。
因此即使 Tauri 侧拼上 `#/chat` 之类的片段，前端也不会识别。

### 影响评估

- **非 Windows 迁移问题**，属**功能未实现**：macOS 上行为相同。
- 第 10 节第 12 项判定为**"部分通过"**：打开网页 ✅，落到对话页 ❌。

### 修复记录（2026-09-14，macOS 侧）

按建议的两步配合实现，未引入路由库：

1. **前端**（`apps/web/src/App.tsx`）：新增 `pageFromHash()` 与 `useHashPage()`，
   `page` 改为 URL 片段驱动（`#/chat` → 对话页，未知/缺失回落主页），
   既有的 `setPage(...)` 调用点语义不变（写 hash + 更新 state），并监听 `hashchange`，
   所以浏览器已经开着时再打开带片段的链接也会切页；
2. **Tauri 侧**（`apps/desktop/src-tauri/src/lib.rs`）：`open_main_ui` 增加可选
   `page` 参数，新增 `page_fragment()` 只放行小写字母且长度 ≤ 16（其余回落主页，避免拼接脏 URL）；
3. **挂件**（`apps/desktop/src/components/Widget.tsx`）：两条长回复入口都改为
   `openMainUi("chat")` —— `submitText` 的 `done.short` 分支，以及 WS
   `conversation.completed`（`expand_ui`）分支。后者原来打开的是根路径，
   若只改前者会出现「同一轮打开两个不同 URL、落到哪个标签不确定」；短回复路径不变。

验证：`apps/web` `npm run build`（含 tsc）通过、`apps/desktop` `npm run typecheck` 通过、
`cargo test --lib` 10 项通过（含新增的 `page_fragment` 用例，覆盖大写/超长/路径穿越拒绝）；
内置浏览器实测 `http://localhost:5173/#/chat` 直接渲染对话页（导航高亮=对话、输入框在位），
点击导航后地址栏同步变为 `#/memory`。

---

## WP-03 — 右键退出程序后，已打开的浏览器不会被关闭

### 现象

浏览器处于打开状态时，右键挂件选择「退出程序」：

- 挂件窗口正常退出 ✅
- **浏览器界面仍然保持打开** ❌（用户明确报告）

### 根因（代码核实）

`apps/desktop/src-tauri/src/lib.rs` 中浏览器是**交接给系统 shell** 打开的：

```rust
fn open_url_in_browser(url: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let result = Command::new("open").arg(url).spawn();
    #[cfg(target_os = "windows")]
    let result = Command::new("cmd").args(["/C", "start", "", url]).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let result = Command::new("xdg-open").arg(url).spawn();
    result.map(|_| ()).map_err(|e| format!("打开浏览器失败: {e}"))
}
```

三个关键事实：

1. `cmd /C start "" <url>` 把 URL 交给系统默认浏览器处理，**随即返回**；
2. `spawn()` 的进程句柄**未被保存**（`result.map(|_| ())` 直接丢弃），**没有记录浏览器 PID**；
3. 退出路径 `quit_app` → `kill_child` **只管理 AI 服务子进程**，
   完全不涉及浏览器进程。

因此「退出程序时一并关闭浏览器」**从未被实现**。

### 影响评估

- **非 Windows 迁移问题**：macOS 上 `open` 同样交接给 LaunchServices，行为一致。
- 属**功能未实现**，非缺陷回归。
- 副作用：退出后浏览器残留一个指向 `127.0.0.1:8736` 的页面，
  此时服务已停，页面处于不可用状态，容易造成困惑。

### 修复记录（2026-09-14，macOS 侧）

采用上面列的第 1 条（前端友好降级），**不做真关闭浏览器**——第 2/3 条那套 PID
管理在 Windows（`cmd /C start` 不返回浏览器 PID）和 macOS（`open` 同样不回传）
都要另找壳层定位，成本远高于收益，留作将来单独评估。

改动（只动 `apps/web/src/App.tsx`）：

- 轮询里区分「health/session 是否拿到」与「挂件状态、事件流是否成功」：
  后者失败不再算服务没了（第一版把两者混在一个 try 里，服务恢复后横幅不消失）；
- 曾连上过服务、之后探活失败 → 顶部横幅「DeskMate 已退出：本地服务已停止，
  页面不会再更新，可以直接关闭」+「重新连接」按钮（立即重试，不用等 8 秒轮询）；
- 头部徽标补第三态：`服务已退出`（失联）/`服务正常`/`服务离线`（从未连上）。
  之前徽标读的是缓存下来的 health，服务停了仍显示「服务正常」，是这次困惑的另一半原因；
- `serviceOk` 一并接入失联判定，首页与「系统状态」卡片同步显示「离线」，
  不再出现「头部说已退出、卡片说运行中」的同屏矛盾；
- 连续 **2** 次探活失败才判定退出（单次 5 秒超时或瞬时拒绝不算），成功即清零，
  避免把「服务正忙」误报成「DeskMate 已退出」；
- 从未连上过的冷启动（直接打开 URL 但服务没起）仍只显示原有的「连接失败」+「服务离线」，
  不误报「已退出」。

验证（本机真跑四态）：冷启动无服务 → `连接失败`+`服务离线`；服务起来 → `服务正常`、无横幅；
杀掉服务（等价于右键退出 DeskMate）→ 两轮探活内出现「DeskMate 已退出」+`服务已退出`+卡片`离线`；
重启服务后点「重新连接」→ 横幅立即消失、恢复 `服务正常`。
`./scripts/check.sh` 160 passed + web/desktop 类型检查通过。

**仍未做**（如需再评估）：

1. **优先方案**：不真正关闭浏览器，改为**导航到提示页**或利用
   ✅ 已实现（即上面的修复记录）；
2. **若要真关闭**：需要在 `open_url_in_browser` 中记录 PID 并纳入
   `ChildState` 统一管理 —— 但 Windows 的 `cmd /C start` 不会返回
  浏览器自身 PID（返回的是 cmd 的），需改用 ShellExecute / 注册表关联
   程序定位，或改用专用浏览器实例（`--user-data-dir` 隔离），
   跨平台成本较高（未做）；
3. macOS 侧同样需要处理 `open` 不返回 PID 的问题。

---

### 根因

npm 11 默认拦截安装脚本（新增安全策略）。

### 实际影响

**无。** 已验证 `apps/web/node_modules/@esbuild/win32-x64/esbuild.exe` 正常落地
（平台二进制走 `optionalDependencies`），`npm run build` 实测 `✓ built in 7.25s`。

### 处置

无需处理。若将来构建真报缺二进制：`npm install-scripts approve esbuild`。

---

## 附：第 8 节完整检查结果

| 检查项 | 命令 | 结果 |
|---|---|---|
| Python 测试 | `.\.venv\Scripts\python.exe -m pytest -q` | 153 passed, 2 failed |
| Web 类型检查 | `npm run typecheck`（apps/web） | 通过（tsc --noEmit 无输出） |
| Desktop 类型检查 | `npm run typecheck`（apps/desktop） | 通过（tsc --noEmit 无输出） |
| 路径分隔符 / 编码异常 | — | 未发现 |
| 权限相关异常 | — | **2 项**，即 WI-01 / WI-02 |

> 注：`scripts/check.sh` 写死了 macOS 的 `.venv/bin/python`，Windows 上不可直接运行，
> 已按 `WORKBUDDY-WINDOWS-MIGRATION.md` 第 8 节改用上述 PowerShell 等价命令。
> 该脚本本身是否需要在 Windows 下适配，另行评估（本轮不改）。
