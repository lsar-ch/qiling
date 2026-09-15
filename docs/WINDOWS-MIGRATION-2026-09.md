# Windows 迁移与验收 — 结论与遗留（2026-09-13 轮，2026-09-15 收口）

> **本文是 Windows 迁移主题的唯一入口，读完这一份即可。**
> 原始过程记录（逐项证据、环境清单、执行流水）已移入
> `docs/archive/windows-migration-2026-09/`，仅在需要翻原始证据时再读。
> 依赖漏洞与升级影响面见 `docs/DEPENDENCY-VULNERABILITIES.md`。

## 1. 状态一句话

Windows 轮（2026-09-13）发现的 5 个 WI + 3 个 WP **全部处置完毕**。
Windows 侧的 WI-05 真机复验与 18 项回归已于 2026-09-14 回传全绿；
同日的第二轮修复（WI-06/07/08/09/10）已在 macOS 落地并完成真机复验（见第 7 节）。
`./scripts/check.sh` → **163 passed** + web/desktop 类型检查通过。

## 2. 遗留待办

| # | 事项 | 状态 | 完成判据 |
|---|---|---|---|
| 1 | **WI-05 真机复验**：Windows 上确认注册表扫描能发现非 C 盘安装的 WorkBuddy | ✅ 2026-09-14 通过（T1 3/3，卡片自动显示 D 盘路径，全程未手填） | 见第 5 节命令 |
| 2 | **vite 5.4.21 → 7/8.x 升级** | ⏳ 挂 P2 发布加固（见第 4 节） | `npm audit` 清零 + `check.sh` + Tauri dev 全过 |
| 3 | **Windows 侧 18 项回归重跑一遍**（确认 8 项修复在 Windows 上无退化） | ✅ 2026-09-14 通过（18/18，含第 18 项退出回收两次干净验证） | 清单见 `docs/archive/windows-migration-2026-09/WINDOWS-MIGRATION-RUNBOOK-2026-09-13.md` 第 7 节 |

> 2026-09-14 下发任务卡：`WORKBUDDY-WINDOWS-REGRESSION-2026-09-14.md`（遗留 1 与 3 的测法与预期结果都在里面），
> 随源码包 `DeskMate-Windows-src-2026-09-14.zip` 一起带回 Windows 交给 WorkBuddy。

## 3. 问题明细（均已修复）

| 编号 | 一句话问题 | 处置 |
|---|---|---|
| WI-01 | `test_..._requires_executable_permission` 在 Windows 失败 | 测试改平台分支断言：win32「文件存在即可执行」、POSIX「无 x 位不可执行」。产品代码不动 |
| WI-02 | `test_unwritable_vault_fails_quietly` 在 Windows 失败 | 新增跨平台用例（同名文件占住镜像目录名让 `mkdir` 必然失败）并读回本地记忆证明「只有镜像这一路降级」；原只读用例仅 win32 `skip` |
| WI-03 | `npm audit` 报 vite high + esbuild moderate | 未修，见 `DEPENDENCY-VULNERABILITIES.md`（影响面仅开发服务器） |
| WI-04 | npm 11 拦截 esbuild postinstall | 无需处理：实测平台二进制已正常落地，构建正常 |
| WI-05 | WorkBuddy 自动检测在非 C 盘安装时失效 | 新增 `app/agents/windows_install.py`：读 `Uninstall` 注册表（HKLM 64/32 位 + HKCU）+ 固定磁盘根目录兜底。**待真机复验** |
| WP-01 | 页面无「关闭自动播报回复」开关 | 设置页补开关（绑 `voice.auto_speak`），文案含「任务待确认提醒一并关闭」 |
| WP-02 | 长回复自动打开浏览器只进主页 | 前端 hash 路由 + `open_main_ui(page)` 带片段打开，两条长回复入口都传 `chat` |
| WP-03 | 右键退出后浏览器不关闭 | 前端降级：连续 2 次探活失败才判「DeskMate 已退出」+ 横幅 + 重新连接按钮。**不真关浏览器**（`cmd /C start` / `open` 都不回传浏览器 PID） |

改动落点：`services/ai-service/tests/{test_agent_config,test_vault_mirror}.py`、
`services/ai-service/app/agents/{workbuddy.py,windows_install.py}`、
`apps/web/src/App.tsx`、`apps/desktop/src/components/Widget.tsx`、
`apps/desktop/src-tauri/src/lib.rs`。

## 4. vite 升级：能推到 V2 / V3 吗

**能推，但要挂账 + 设触发条件，别靠记忆。**

事实：两处 `vite ^5.4.0`（`apps/web`、`apps/desktop`，实装 5.4.21）。
`npm audit` 的两个漏洞——`vite` high（受影响区间 `<= 6.4.2`）、`esbuild` moderate（`<= 0.24.2`）
——**全部只作用于开发服务器**（`server.fs.deny`、optimized deps、launch-editor），
不影响 `npm run build` 产物与生产运行；本项目是本地单机应用，dev server 只监听本机。

- **归口**：仓库目前没有 V2/V3 里程碑命名，路线图用的是
  `V1 → V1.1（P1）→ P2 发布加固 → P3`。建议挂到 **P2 发布加固**，
  作为一条独立的「依赖维护」条目（见 `docs/PROJECT-ROADMAP.md` 的 P2 小节）。
- **清零时点**：P2 开始时；或下列任一条件出现时提前：
  1. dev server 需要暴露到局域网/公网（远程调试、真机联调）；
  2. 新引入的依赖 peer 要求 vite ≥ 6/7；
  3. 发布门禁要求 `npm audit` 零 high。
- **推后不做的风险**：低（仅开发环境）。**推后要付的代价**：
  跨 3 个大版本，Tailwind / plugin-react 生态可能同期变更，间隔越久一次要验的面越大。
- **建议动作**：每季度重跑一次 `npm audit`，只记录不修；
  真到升级时按 `DEPENDENCY-VULNERABILITIES.md` 第 7 节逐项验（v5→6→7→8，v7 起 plugin-react 不用动，v8 需连带升）。

## 5. 回 Windows 时要用的东西

**环境版本（Windows 轮实测）**：Python 3.12.10 / Node v24.21.0 / npm 11.19.0 /
rustc 1.98.1 / MSVC VS 2022 生成工具 / Git 2.55。

**WI-05 复验命令**：

```powershell
cd D:\Projects\desktop-assistant\services\ai-service
..\..\.venv\Scripts\python.exe -c "from app.agents.windows_install import registry_candidates as r; print(r(('WorkBuddy',),('WorkBuddy.exe',)))"
```

**注意**：`scripts/check.sh` 写死了 macOS 的 `.venv/bin/python`，Windows 上不可直接运行，
改用等价的 PowerShell 命令（`pytest -q` + 两个 `npm run typecheck`）。

**从 Windows 带回 macOS 时不要复制**：`.venv/`、两处 `node_modules/`、
`src-tauri/target/`、两个 `dist/`、`__pycache__/`、`.pytest_cache/`、`.env`。

## 6. Tauri 自管服务退出回收（2026-09-14 复验）

原第 18 项没测到 Tauri 自管的 uvicorn（那轮 uvicorn 由人工启动）。
本轮补测，两种场景都通过：

- `npm run tauri dev`：uvicorn 由 Tauri 自动拉起，父进程 = `deskmate-desktop`；
- 打包后走真实退出路径（`tauri build --debug --bundles app` → `open` → `osascript quit`）：
  启动时 uvicorn PPID = DeskMate.app 自身，退出后 **DeskMate 进程 0 / uvicorn 进程 0 / `:8736` 监听 0**。

结论：**Tauri 自管模式下关闭 DeskMate，uvicorn 一并退出，无残留。**
附带观察：手动启动的 uvicorn 在该环境下**不吃 SIGTERM**，需 `kill -9`（与产品无关）。

## 7. 第二轮修复与 macOS 复验（2026-09-14 补丁 → 2026-09-15 复验）

2026-09-14 第二轮改由 Windows 侧直接改代码交付补丁
（`DeskMate-Windows-fixes-20260914.patch`，14 文件，逐条说明见随包的 `FIX-NOTES-2026-09-14.md`），
覆盖 WI-06 长回复重复开标签页、WI-07 提示配色、WI-08 执行器解绑、
WI-09 右键菜单被窗口裁切、WI-10 贴边保留量/点击穿透。补丁已落地（commit `1cad554`）。

### 7.1 FIX-NOTES §4.1 清单的 macOS 真机复验

| 项 | 结果 |
|---|---|
| 右键菜单三处（角色头部 / 身体中部 / 最下沿） | ✅ 三处「退出 DeskMate」都完整可见；最下沿那次菜单自动上移避让裁切 |
| WI-06 长回复只开一个标签页 | ✅ 自动路径只开 1 个，地址 `127.0.0.1:8736/#/chat`；双击挂件手动打开仍照常新开 |
| WI-08 复杂任务真实落到 WorkBuddy | ✅ 见 7.2 |

### 7.2 WI-08 端到端（真实执行，不是只看路由）

`preferred_executor` 已解绑（`classifier.py` 置 `None`）后，
提复杂任务 → `delegate_backend / complex` → 落到 `config/agents.yaml` 的 `default_executor: workbuddy`。

首跑（`run_706a989d36`）**失败**，但根因不在 WorkBuddy：`agents/acp.py` 用
`asyncio.create_subprocess_exec` 建子进程时没传 `limit`，`StreamReader` 默认只有 64 KiB；
ACP 端吐超长单行时 `readline()` 抛 `Separator is not found, and chunk exceed the limit`，
reader 停摆，整条会话被判「ACP process exited」（该 run 已真实执行 107 秒并留下工具调用记录）。
该报错已在隔离环境 100% 复现（同样 64 KiB 限制 + 200 KB 单行）。

修复：`acp.py` 新增 `ACP_STREAM_LIMIT = 16 MiB` 并在 spawn 时传入 ——
共享客户端对 codex / workbuddy 两条 ACP 通路同时生效；补回归测试
`tests/test_acp.py::test_acp_reader_survives_oversized_line`。

复验：`run_2db5180948`（`task_b297ce2553`，read-only）**completed**，
6 分 14 秒、98 次工具调用，产出真实的目录结构分析结果。

> WorkBuddy 桌面端**不需要**开着：适配器直接拉起其自带 CLI
> （`/Applications/WorkBuddy.app/Contents/resources/app.asar.unpacked/cli/bin/codebuddy`）。

### 7.3 macOS 上边缘隐藏（2026-09-15 修复）

原问题：macOS 上吸附到屏幕上边缘完全不隐藏。实测窗口顶边越不过工作区顶部
（AX 强行设成 `y=-200` 也被夹回 `y=25`），说明不是拖拽收尾造成的，是窗口服务器的硬限制；
Windows 没有这条限制。

修法：其它三边仍是「把窗口挪出屏幕、由系统裁掉」，上边缘改成「窗口留在工作区顶部、
角色在窗口内上移」。Rust 侧把位置收回工作区顶部并把 `hiddenEdge: "top"` 带进 preferences，
前端据此给 `.stage` 加 `bottom` 偏移（复用已有的 `transition`，隐藏/恢复带动画）。
窗口屏幕占位没变，所以不会比原来多出透明死区。

回归（macOS 真机、逐个边缘拖拽后读窗口位置）：上 `y=25` + 角色只留底部一条 ✓、
右 `1607` ✓、左 `-245` ✓、下 `836` ✓；拖离边缘后 `hiddenEdge` 复位为 `null`、角色落回原位 ✓。
