# DeskMate Windows 3D 挂件真机验收任务卡（2026-09-30 轮）

> **给 WorkBuddy 的读法**：本轮任务书就是本文。
> 总流程、交互节奏、禁止事项沿用 `WORKBUDDY-WINDOWS-MIGRATION.md`（下称总文档）第 5 / 12 / 13 节；
> 上一轮任务卡 `WORKBUDDY-WINDOWS-REGRESSION-2026-09-14.md` 只作格式参考，预期结果以本文为准。
>
> 项目目录：`D:\Projects\desktop-assistant`
> 源码获取：**网盘路线**，源码包 `DeskMate-Windows-src-2026-09-30.zip`（HEAD `2fdcb7f`）
> 用户角色：手动执行命令、回传原始输出；WorkBuddy 只做只读检查、解释、判断和记录，一次只推进一个阶段。
> 说明：Windows 侧无网络，本轮**不用 git**，源码走夸克网盘传包。

## 1. 本轮只做两件事

| 编号 | 目标 | 完成判据 |
|---|---|---|
| **T1** | 挂件 3D 形象在 Windows WebView2 上的真机验收（本轮重点） | 第 7 节 7 项全部「通过」，或失败项带原始现象回传 |
| **T2** | 18 项回归重跑：确认既有功能在 Windows 上没有退化 | 第 8 节 18 项全部「通过」，或失败项带原始输出回传 |

本轮**不做**：不升级依赖、不改产品代码、不修改或跳过任何测试、不动旧目录。
发现失败只记录并回传，不要自行修复。

## 2. 为什么要专门跑这一轮（背景）

- 挂件形象已从 2D 立绘切到 **VRM 3D + VRMA 动作**（three-vrm 路线），
  macOS 已实机验收 6/6 通过：透明背景、拖动、置顶、双击开对话、动作反馈、口型随播报变化。
- 唯一没验证过的风险是 **Windows 上 WebView2 的透明合成 + WebGL 渲染**
  （上游 Tauri #8020 / #4891 有已知问题）。代码里已用 `premultipliedAlpha: false`
  作为「Windows DComp 黑底」的已知修法，但**必须真机确认**。
- 这次必须验证的核心，就是「3D 模型能在 Windows 上正常显示、没有黑底/白底/空白」，以及各类动作与口型真的跑起来。

参考实现位置（WorkBuddy 只读查看，不改）：

- 透明渲染配置：`apps\desktop\src\widget\VrmStage.tsx`（`new THREE.WebGLRenderer({ alpha: true, premultipliedAlpha: false, ... })`）
- 挂件窗口配置：`apps\desktop\src-tauri\tauri.conf.json`（`widget` 窗口 `transparent: true` / `alwaysOnTop: true` / `decorations: false` / 430×480）
- 风险表：`docs\WIDGET-VRM-3D-PLAN.md` 第 5 节

## 3. 源码获取（网盘路线，本轮不用 git）

Windows 侧无网络，源码走夸克网盘传包，**不需要也不能 `git clone`**。

- 源码包：`DeskMate-Windows-src-2026-09-30.zip`（约 177MB，550 个文件）
- 内含 HEAD：`2fdcb7f`（打包时 `origin/main` 的提交，见包内 `SOURCE-VERSION.txt`）
- 已含全部 3D 资产：`data\persona-assets\`（含 k81 / vrm_demo / komano 的 `model.vrm` 与 `vrma\`）、
  `data\motion-library\{male,female}\`
- 不含：`.git`、`.venv`、两处 `node_modules`、`src-tauri\target`、两个 `dist`、`.env`、运行时数据

1. **先处理旧目录（只读检查，不改不删）**：确认 `D:\Projects\desktop-assistant` 是否已存在。
   - 若存在旧内容：由用户确认后，把它**改名**为 `D:\Projects\desktop-assistant-2026-09-14`（改名可回退，删除不可回退）。
   - 旧目录里的 `.env`、`data\settings.local.json` 要留着，第 3.4 步取回。
2. **解压**：把 `DeskMate-Windows-src-2026-09-30.zip` 解压到 `D:\Projects\`，
   得到 `D:\Projects\DeskMate-Windows-src-2026-09-30\`，再由用户确认后改名为
   `D:\Projects\desktop-assistant`（与本文约定路径一致）。
3. **确认落位**：打开包内 `SOURCE-VERSION.txt`，`HEAD commit` 必须是
   `2fdcb7fee3b33274001a8690247febcae42f209d`。不一致就停下报告。
4. **取回本地配置（不在包里，必须手工恢复）**：
   - `.env`（唯一无法重新生成的内容）
   - `data\settings.local.json`（含 API key、`active_persona_id`、`voice_enabled`、`setup_completed`）

   从旧目录 `D:\Projects\desktop-assistant-2026-09-14\` 复制这两个文件到新目录对应位置。
   若找不到：`.env` 参照根目录 `.env.example` 重填；`data\settings.local.json` 缺失会导致初始化向导重跑，
   也可以由用户改从设置页重新配置。**不要覆盖旧目录里的原件。**
5. **解压后必须先确认这些路径存在，再进入下一阶段**：

   ```text
   D:\Projects\desktop-assistant\apps
   D:\Projects\desktop-assistant\services
   D:\Projects\desktop-assistant\packages
   D:\Projects\desktop-assistant\data\persona-assets\k81\model.vrm
   D:\Projects\desktop-assistant\data\persona-assets\vrm_demo\model.vrm
   D:\Projects\desktop-assistant\data\motion-library\female\idle.vrma
   D:\Projects\desktop-assistant\config\personas\k81.yaml
   D:\Projects\desktop-assistant\SOURCE-VERSION.txt
   D:\Projects\desktop-assistant\WORKBUDDY-WINDOWS-3D-VERIFY-2026-09-30.md
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

预期：与 09-13/09-14 轮一致即可（Git 2.55 / Python 3.12.10 / Node v24.21.0 / npm 11.19.0 / rustc 1.98.1）。
缺命令就停下报告，不要自动安装。

## 5. 阶段 1：装依赖（逐区块执行，成功后再下一个）

**不要直接跑 `scripts\setup.sh`**（它按 POSIX 写死路径）。手动执行：

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
npm ci
npm run build
```

```powershell
cd D:\Projects\desktop-assistant\apps\desktop
npm ci
```

说明：`npm ci` 若因缺 `package-lock.json` 报错，退回 `npm install`；出现 npm 11 对 esbuild postinstall 的拦截警告可忽略（见第 10 节）。

## 6. 阶段 2：自动化检查（对应回归第 6 项）

**不要运行 `scripts\check.sh`** —— 它写死了 macOS 的 `.venv/bin/python`。用下面三条等价命令：

```powershell
cd D:\Projects\desktop-assistant\services\ai-service
..\..\.venv\Scripts\python.exe -m pytest -q
```

预期：**`289 passed, 1 skipped`**。
`skipped` 是 `test_readonly_vault_fails_quietly`（Windows 没有 POSIX 权限位，无法构造前提），正常。
（macOS 上同一条会跑成 `290 passed`；Windows 少的那 1 条就是它。）

```powershell
cd D:\Projects\desktop-assistant\apps\web
npm run typecheck
```

```powershell
cd D:\Projects\desktop-assistant\apps\desktop
npm run typecheck
```

预期：两条 typecheck 都没有输出（无错误即通过）。

## 7. 阶段 3：T1 — 3D 挂件真机验收（本轮重点）

### 7.0 准备

1. 确认当前角色是 3D 角色。最简单的方式：把 `data\settings.local.json` 里的
   `active_persona_id` 设为 `"k81"`（`k81` 的 `avatar_driver` 就是 `vrm_3d`，模型是 `model.vrm`）。
   备选角色：`vrm_demo`（体积小，适合先跑通）。**不要用 `komano`（约 64MB，先跳过）**。
2. 启动 DeskMate（**不要手动**起 uvicorn，让 Tauri 自管）：

   ```powershell
   cd D:\Projects\desktop-assistant\apps\desktop
   npm run tauri dev
   ```

   首次 Rust 编译预计 5–15 分钟，耐心等，不要中途打断。
3. 等挂件窗口出现（无边框、约 430×480、悬浮在桌面上）。

> 7.1–7.6 逐项做，**一次只做一项**，把现象原样回传。任何一项失败都先停下，带截图/原始报错回传，不要跳过错项继续。

### 7.1 透明背景（Windows 特有风险，最关键）

- 观察：挂件窗口的**四角与模型周围区域**是否透明 —— 能看见后面的桌面壁纸/其它窗口，**而不是黑底、白底或灰色方块**。
- 通过判据：模型正常显示，背景透出桌面，看不到矩形底。
- 失败特征（回传用）：出现黑色/白色/灰色矩形底、模型被裁进一个方块里。

### 7.2 拖动正常

- 操作：按住模型区域拖动，窗口应跟随鼠标移动。
- 通过判据：窗口跟手移动，松手后停在原位；不出现拖一下跳一下、拖不动、或拖出屏幕外收不回。

### 7.3 一直置顶

- 操作：点开任意其它窗口（浏览器、资源管理器）并置前。
- 通过判据：挂件仍显示在最上层，不被其它窗口盖住。

### 7.4 双击打开对话

- 操作：双击挂件主体。
- 通过判据：主界面窗口打开，并停在**对话页**（地址栏形如 `http://127.0.0.1:8736/#/chat`），不是只停在主页。

### 7.5 有动作反馈

- 操作：分别触发几种状态并观察模型动作是否切换：
  - 鼠标**悬停**挂件 → 应有 `hover` 类动作；
  - **单击**挂件 → 应有 `click` 类动作；
  - 发起一次**文字/语音对话** → 应有 `listening` / `thinking` / `speaking` 类动作；
  - 任务开始执行 / 成功 / 失败 → 对应 `executing` / `success` / `error` 动作。
- 通过判据：**每个状态下模型确实换动作**（不是一直僵在同一个姿势、也不是完全不动）。
- 说明：`listening / error / click / hover` 这几个 trigger 目前映射的是动作库里语义接近的片段，
  不要求逐帧符合字面语义；**只要「状态变化 → 动作变化」成立即算通过**。

### 7.6 口型随播报变化

- 操作：触发一次会**语音播报**的回复（需 `.env` 里配好 TTS）。
- 通过判据：播报过程中模型**嘴部随声音开合**，声音停嘴停。
- 失败特征（回传用）：播报时嘴不动、嘴一直张着不闭、或口型与声音明显不同步。

### 7.7 WebGL 上下文健康（补充检查，证明不是「假透明」）

- 目的：确认画面不是「整块透明但模型根本没渲染」。
- 操作：正常浏览器打开 `http://localhost:1420/?deskmate=widget`（dev server 在跑时可用），
  按 F12 打开控制台，查看是否出现 WebGL / THREE 相关报错。
- 通过判据：控制台**没有** `THREE.WebGLRenderer: Error creating WebGL context`、
  `CONTEXT_LOST_WEBGL`、`Failed to create WebGL context` 之类报错；画面里能看到模型本体。

## 8. 阶段 4：T2 — 18 项回归

逐项执行并回填结果，测法沿用上一轮。

| # | 项目 | 本轮预期 |
|---|---|---|
| 1 | 项目路径不含中文/特殊字符 | `D:\Projects\desktop-assistant` |
| 2 | Python 虚拟环境创建成功 | 无报错，`.venv` 生成 |
| 3 | Python 依赖安装成功 | 无冲突（可加跑 `pip check`） |
| 4 | Web 依赖安装 + `npm run build` | 构建成功；npm 11 的 esbuild postinstall 警告可忽略（WI-04） |
| 5 | Desktop 依赖安装成功 | 无报错 |
| 6 | 等价自动化检查通过 | 见第 6 节：`289 passed, 1 skipped` + 两个 typecheck |
| 7 | `/api/health` 正常 | `status: ok`，`stt/tts/vad` 为 true（语音未配置时按实际降级报告） |
| 8 | 浏览器主界面能打开 | `GET /` → 200，页面正常渲染，控制台无报错 |
| 9 | 文字对话一问一答 | 有回复且落库 |
| 10 | 语音输入可用 | 麦克风允许时能转写（无麦克风/未配置语音则如实标注「未执行」并说明原因） |
| 11 | 关闭「自动播报回复」后语音输入仍可用、回复不自动朗读 | 设置页出现该开关（WI 相关，含「任务待确认提醒的语音播报一并关闭」文案） |
| 12 | 关闭自动播报后，长回复仍打开网页并显示全文 | 打开后停在对话页，地址栏带 `#/chat` |
| 13 | 拒绝浏览器麦克风权限后页面不崩溃、文字对话仍可用 | 有可见降级提示 |
| 14 | 角色卡页面能读取角色 | 列表正常（应能看到 k81 / vrm_demo 等） |
| 15 | 角色形象显示正常，挂件显示同一形象 | 挂件显示与角色卡一致的 3D 形象 |
| 16 | 「我的智能体」显示 Codex 状态 | 有明确可用/不可用结论 |
| 17 | 没有 Codex 时任务保留在队列并显示不可用原因 | 有可读原因，不静默失败 |
| 18 | 关闭 DeskMate 后没有残留 `uvicorn` 与 `:8736` 监听 | 见第 9 节 |

## 9. 阶段 5：退出回收（第 18 项的测法）

测 **Tauri 自管**的服务，不要手动起 uvicorn：

1. 用 `npm run tauri dev` 启动，确认挂件出现、`/api/health` 正常。
2. 从挂件右键菜单退出 DeskMate。
3. 立刻检查：

```powershell
tasklist | findstr /i "deskmate uvicorn"
netstat -ano | findstr :8736
```

预期：两条命令都没有输出（进程 0、监听 0）。
若仍有残留，按 PID 回传对应进程名与命令行原文，先不要强杀未知进程。

## 10. 预期内的「看起来像问题」（不算失败）

- Windows 挂件**透明失败**（黑/白矩形底）**不算「已知可忽略」** —— 这是本轮 T1 要专门抓的问题，必须回传截图与现象。
- `npm audit` 仍报 2 条（vite high / esbuild moderate）—— 已挂 P2（`docs\DEPENDENCY-VULNERABILITIES.md`），本轮不修。
- npm 11 对 esbuild postinstall 的拦截警告 —— 忽略即可，`npm run build` 成功即通过。
- pytest `1 skipped` —— POSIX 专有用例在 Windows 无法构造前提，正常。
- 退出 DeskMate 后浏览器不会关闭，页面显示「DeskMate 已退出」—— 设计如此。
- `scripts\check.sh` 在 Windows 不可用 —— 用第 6 节等价命令代替。

## 11. 禁止事项（沿用总文档第 12 节）

- 不修改或跳过测试、不为了让 pytest 变绿改动产品逻辑。
- 不删除、不改名、不覆盖旧目录。
- 不升级依赖、不跑 `npm audit fix`。
- 不删除包内任何文件、不覆盖未提交修改。
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
阶段 0：<各命令版本输出>
阶段 1：venv/pip/web build/desktop install <结果>
阶段 2：pytest 289 passed, 1 skipped / web typecheck 通过 / desktop typecheck 通过
阶段 3：7.1–7.7 <逐项通过/失败 + 现象>
阶段 4：18 项中 <通过 x 项>，失败项：<编号 + 现象>
阶段 5：tasklist、netstat 原始输出
```

失败项必须带：执行目录、完整命令、完整原始输出、能否稳定复现；涉及画面的附截图。

## 13. 完成标准

- **T1**：7.1–7.7 全部「通过」（透明、拖动、置顶、双击、动作、口型、WebGL 健康）。
  若 7.1 透明在 Windows 上仍失败，即为**真实缺陷**，停下回传，由 macOS 侧定位 `VrmStage.tsx` 渲染配置。
- **T2**：18 项全部「通过」；或失败项已按第 12 节回传证据，由 macOS 侧判断。

两项都满足即为本轮通过，可关闭 `docs\WIDGET-VRM-3D-PLAN.md` 第 5 节「Windows WebView2 透明+WebGL」这条未验证风险。
