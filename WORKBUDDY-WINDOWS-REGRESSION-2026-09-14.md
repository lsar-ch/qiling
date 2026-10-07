# 栖灵 Windows 回归任务卡（2026-09-14 轮）

> **给 WorkBuddy 的读法**：本轮任务书就是本文。
> 总流程、交互节奏、禁止事项沿用 `WORKBUDDY-WINDOWS-MIGRATION.md`（下称总文档）第 5 / 12 / 13 节；
> 磁盘方案（总文档第 4 节）本轮无需重读。总文档第 10 节的 18 项清单仍然有效，预期结果以本文为准。
>
> 项目目录：`D:\Projects\desktop-assistant`
> 源码包：`栖灵-Windows-src-2026-09-14.zip`（HEAD `6dd6b01`）
> 用户角色：手动执行命令、回传原始输出；WorkBuddy 只做只读检查、解释、判断和记录，一次只推进一个阶段。

## 1. 本轮只做两件事

| 编号 | 目标 | 完成判据 |
|---|---|---|
| **T1** | WI-05 真机复验：路径留空时，自动检测能找到装在 D 盘的 WorkBuddy | 第 6 节三条全部给出 D 盘路径且 UI 显示 `ready` + 已登录 |
| **T2** | 18 项回归重跑：确认 09-13 轮 8 项修复在 Windows 上没有退化 | 第 7 节 18 项全部「通过」，或失败项带原始输出回传 |

本轮**不做**：不升级依赖、不改产品代码、不修改或跳过任何测试、不动旧目录与旧压缩包。
发现失败只记录并回传，不要自行修复。

## 2. 要验的 8 项修复（09-13 轮 Windows 上发现的问题）

| 编号 | 09-13 现象 | 本轮预期 |
|---|---|---|
| WI-01 | `test_resolve_codex_command_requires_executable_permission` 失败 | 不再失败：按平台分支断言（Windows 按「文件存在即可执行」） |
| WI-02 | `test_unwritable_vault_fails_quietly` 失败 | 不再失败：新增跨平台用例；POSIX 只读用例在 Windows 跳过，**`1 skipped` 属正常** |
| WI-03 | `npm audit` 报 vite high + esbuild moderate | **仍会报，属预期**，本轮不修（已挂 P2，见 `docs/DEPENDENCY_VULNERABILITIES.md`） |
| WI-04 | npm 11 拦截 esbuild postinstall | 无需处理：忽略该警告即可，`npm run build` 成功即通过 |
| WI-05 | 自动检测找不到装在 D 盘的 WorkBuddy | 能被找到（T1 专项） |
| WP-01 | 页面没有「关闭自动播报回复」开关 | 设置页出现该开关，说明文字含「任务待确认提醒的语音播报一并关闭」 |
| WP-02 | 长回复自动打开浏览器只进主页 | 长回复打开后直接停在「对话」页，地址栏带 `#/chat` |
| WP-03 | 右键退出后浏览器不关闭 | 退出后页面出现「栖灵 已退出」横幅 + 「重新连接」按钮；**浏览器仍不关闭，这是设计** |

## 3. 包与落位

- 源码包：`栖灵-Windows-src-2026-09-14.zip`，HEAD `6dd6b01`
- 旧目录处理（**以本文为准，覆盖总文档 7.1 的包名**）：

  1. 09-13 轮用的解压目录就是当前的 `D:\Projects\desktop-assistant`。先由用户确认，把它**改名**为
     `D:\Projects\desktop-assistant-2026-09-13`（改名可回退，删除不可回退）。
  2. 从旧目录只取回 `.env` 一个文件（新包刻意不带，是唯一无法重新生成的内容），
     其余运行时数据（`.logs/`、`data/` 内的会话与任务）默认不带。
  3. 上轮留存的 `desktop-assistant-2026-09-12-old`、`栖灵-Windows-src-2026-09-12.zip`、
     `栖灵-Windows-src-2026-09-13.zip` **都不要删、不要动**。
  4. 新包解压到 `D:\Projects\desktop-assistant`。

- 解压后必须先确认这些路径存在，再进入下一阶段：

```text
D:\Projects\desktop-assistant\apps
D:\Projects\desktop-assistant\services
D:\Projects\desktop-assistant\packages
D:\Projects\desktop-assistant\data\persona-assets
D:\Projects\desktop-assistant\.git
D:\Projects\desktop-assistant\WORKBUDDY-WINDOWS-REGRESSION-2026-09-14.md
```

## 4. 阶段 0：环境只读检查（不安装任何东西）

```powershell
git --version
py --version
node --version
npm --version
rustc --version
cargo --version
```

预期：与 09-13 轮一致即可（Git 2.55 / Python 3.12.10 / Node v24.21.0 / npm 11.19.0 / rustc 1.98.1）。
缺命令就停下报告，不要自动安装。

## 5. 阶段 1：解压后装依赖

按区块执行，每个区块成功后再下一个（命令同总文档 7.2）：

```powershell
cd D:\Projects\desktop-assistant
py -3.12 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e packages\contracts\py -r services\ai-service\requirements.txt
```

```powershell
cd D:\Projects\desktop-assistant\apps\web
npm install
npm run build
```

```powershell
cd D:\Projects\desktop-assistant\apps\desktop
npm install
```

## 6. 阶段 2：自动化检查（对应回归第 6 项）

**不要运行 `scripts/check.sh`** —— 它写死了 macOS 的 `.venv/bin/python`。用下面三条等价命令：

```powershell
cd D:\Projects\desktop-assistant\services\ai-service
..\..\.venv\Scripts\python.exe -m pytest -q
```

预期：**`160 passed, 1 skipped`**。`skipped` 是 Windows 没有 POSIX 权限位那条，正常。
（09-13 轮是 `153 passed, 2 failed`；多出来的用例是 WI-01/02/05 的回归用例。）

```powershell
cd D:\Projects\desktop-assistant\apps\web
npm run typecheck
```

```powershell
cd D:\Projects\desktop-assistant\apps\desktop
npm run typecheck
```

预期：两条 typecheck 都没有输出（无错误即通过）。

## 7. 阶段 3：T1 专项 — WI-05 复验（本轮重点）

三条都要做，任何一条失败都停下回传证据。

### 7.1 注册表扫描（直接验新逻辑）

```powershell
cd D:\Projects\desktop-assistant\services\ai-service
..\..\.venv\Scripts\python.exe -c "from app.agents.windows_install import registry_candidates as r; print(r(('WorkBuddy',),('WorkBuddy.exe',)))"
```

预期：输出里出现类似 `WindowsPath('D:/Program Files/WorkBuddy/WorkBuddy.exe')`。
若输出是空元组 `()`，回传下面三条注册表查询的原始结果，供 macOS 侧定位：

```powershell
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f WorkBuddy
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" /s /f WorkBuddy
reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f WorkBuddy
```

### 7.2 整体探测（含固定磁盘根目录兜底）

```powershell
cd D:\Projects\desktop-assistant\services\ai-service
..\..\.venv\Scripts\python.exe -c "from app.agents.workbuddy import resolve_workbuddy_runtime as r; print(r(None))"
```

预期：**不是 `None`**，且打印出的 CLI / Electron 路径落在 `D:\Program Files\WorkBuddy\...`。

### 7.3 UI 端到端（用户真实路径）

1. 启动 栖灵（`npm run tauri dev`，或打包后的 exe）。
2. 打开浏览器主界面 → 「我的智能体」。
3. WorkBuddy 卡片路径**保持留空**（若上一轮填过路径，先清空）。
4. 点「刷新」。
5. 预期：显示 `ready`、版本 `2.137.1`、账号已登录 —— 全程不需要手填路径。

> 若 7.1/7.2 通过但 7.3 失败，回传卡片上的提示文字和 `/api/agents` 的返回内容。

## 8. 阶段 4：T2 — 18 项回归

逐项执行并回填结果。除注明外都按 09-13 轮的步骤做。

| # | 项目 | 本轮预期 |
|---|---|---|
| 1 | 项目路径不含中文/特殊字符 | `D:\Projects\desktop-assistant` |
| 2 | Python 虚拟环境创建成功 | 无报错，`.venv` 生成 |
| 3 | Python 依赖安装成功 | 无冲突 |
| 4 | Web 依赖安装 + `npm run build` | 构建成功；npm 11 的 esbuild postinstall 警告可忽略（WI-04） |
| 5 | Desktop 依赖安装成功 | 无报错 |
| 6 | 等价自动化检查通过 | 见第 6 节：`160 passed, 1 skipped` + 两个 typecheck |
| 7 | `/api/health` 正常 | `status: ok`，`stt/tts/vad` 为 true（语音未配置时按实际降级报告） |
| 8 | 浏览器主界面能打开 | `GET /` → 200，页面正常渲染，控制台无报错 |
| 9 | 文字对话一问一答 | 有回复且落库 |
| 10 | 语音输入可用 | 麦克风允许时能转写（无麦克风/未配置语音则如实标注「未执行」并说明原因） |
| 11 | 关闭「自动播报回复」后语音输入仍可用、回复不自动朗读 | **WP-01**：开关在设置页可找到 |
| 12 | 关闭自动播报后，长回复仍打开网页并显示全文 | **WP-02**：打开后停在对话页，地址栏带 `#/chat` |
| 13 | 拒绝浏览器麦克风权限后页面不崩溃、文字对话仍可用 | 有可见降级提示 |
| 14 | 角色卡页面能读取角色 | 列表正常 |
| 15 | 角色形象显示正常，挂件显示同一形象 | 与 `data\persona-assets\` 一致 |
| 16 | 「我的智能体」显示 Codex 状态 | 有明确可用/不可用结论 |
| 17 | 没有 Codex 时任务保留在队列并显示不可用原因 | 有可读原因，不静默失败 |
| 18 | 关闭 栖灵 后没有残留 `uvicorn` 与 `:8736` 监听 | 见第 9 节 |

## 9. 阶段 5：退出回收（第 18 项的测法，与上轮不同）

09-13 轮第 18 项没测准，因为当时 uvicorn 是**手动**启动的。本轮必须测 Tauri 自管的服务：

1. 用 `npm run tauri dev` 启动，**不要手动** `python -m uvicorn`。
2. 确认挂件出现、`/api/health` 正常。
3. 从挂件右键菜单退出 栖灵。
4. 立刻检查：

```powershell
tasklist | findstr /i "qiling uvicorn"
netstat -ano | findstr :8736
```

预期：两条命令都没有输出（进程 0、监听 0）。
若仍有残留，按 PID 回传对应进程名与命令行原文，先不要强杀未知进程。

## 10. 预期内的「看起来像问题」（不算失败）

- `npm audit` 仍报 2 条（vite high / esbuild moderate）—— WI-03，已挂 P2。
- npm 11 对 esbuild postinstall 的拦截警告 —— WI-04，构建成功即通过。
- pytest `1 skipped` —— WI-02 的 POSIX 专有用例，Windows 上本就无法构造前提。
- 退出 栖灵 后浏览器不会关闭，页面显示「栖灵 已退出」—— WP-03 的设计。
- `scripts/check.sh` 在 Windows 不可用 —— 用第 6 节等价命令代替。

## 11. 禁止事项（摘自总文档第 12 节，本轮同样生效）

- 不修改或跳过测试、不为了让 pytest 变绿改动产品逻辑。
- 不删除、不改名、不覆盖旧目录与旧压缩包。
- 不升级依赖、不跑 `npm audit fix`。
- 不删 `.git`、不 `git reset --hard`、不 `git clean -fd`、不覆盖未提交修改。
- 不覆盖 `.env`、API key、用户记忆、角色资产和任务数据。
- 不自动连续执行阶段；不把「建议执行」写成「已经执行」。
- 端口被占用先报告占用进程，不直接杀未知进程。

## 12. 回传格式

每阶段回复用这个格式：

```text
当前阶段：
已确认：
需要你手动执行：
预期结果：
请回传：
```

阶段结束时补一段结果表：

```text
阶段 2：pytest 160 passed, 1 skipped / web typecheck 通过 / desktop typecheck 通过
阶段 3：7.1 <原始输出> 7.2 <原始输出> 7.3 <卡片显示内容>
阶段 4：18 项中 <通过 x 项>，失败项：<编号 + 现象>
阶段 5：tasklist、netstat 原始输出
```

失败项必须带：执行目录、完整命令、完整原始输出、能否稳定复现。

## 13. 完成标准

- T1：7.1 / 7.2 / 7.3 三条全部给出 D 盘路径且 UI 显示 `ready` + 已登录。
- T2：18 项全部「通过」；或失败项已按第 12 节回传证据，由 macOS 侧判断。

两项都满足即为本轮通过，可判定 V1 收口（`docs/WINDOWS-MIGRATION-2026-09.md` 第 2 节遗留 1、3 项清零）。
