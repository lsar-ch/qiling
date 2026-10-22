# 栖灵 双系统测试与迁移

## 建议顺序

栖灵 目前先在 macOS 完成 V1 功能和整页视觉打磨，再做 macOS 最终验收；Windows 放到 macOS 全部定稿后再做一次完整环境安装和回归。

理由：

- macOS 与 Windows 需要各自的 `.venv`、`node_modules`、Rust 工具链，不能直接拷贝运行环境。
- Windows 还需要设置 Python、Node、Rust/MSVC 和浏览器麦克风权限，重复安装成本高。
- 如果 Windows 先跑，之后 macOS 又改 UI 或功能，Windows 验收必须重跑。

## macOS 真机启动测试

前置条件：

- 当前目录已有 `.venv`、`apps/web/node_modules`、`apps/desktop/node_modules`。
- 未初始化时运行：

```bash
./scripts/setup.sh
```

测试步骤：

1. 进入桌面工程：

```bash
cd "/Users/lxb/Documents/desktop assistant project/apps/desktop"
npm run tauri dev
```

2. 确认启动器窗口、挂件窗口都能出现。
3. 启动器应能自动拉起本地 AI 服务，状态变为“正常”。
4. 点击“在浏览器打开主界面”，确认 `http://127.0.0.1:8736/` 可用。
5. 关闭启动器后，确认 uvicorn 进程退出：

```bash
ps aux | rg "uvicorn app.main:app"
```

> 当前 `apps/desktop/src-tauri/tauri.conf.json` 的 `bundle.active` 仍为 `false`，所以这是开发模式启动测试。以后要发布 `.app` 或 Windows 安装包时，需要先补齐打包图标和打包配置。

## macOS 麦克风权限测试

关键点：当前主界面会通过系统默认浏览器打开，因此麦克风权限属于浏览器，不属于 Tauri 应用本身。

1. 先确认语音供应商已配置：

```bash
cp .env.example .env
# 编辑 .env，填写 DASHSCOPE_API_KEY、MINIMAX_API_KEY
```

2. 启动服务并打开主界面：

```bash
./scripts/dev.sh service
```

3. 进入“对话”，点击麦克风/语音入口。
4. macOS 弹出麦克风授权时选择允许。
5. 如没有弹出，去系统设置：

```text
系统设置 → 隐私与安全性 → 麦克风
```

找到当前默认浏览器，例如 Safari、Chrome、Edge，打开权限。

6. 说一句话，确认能转写并触发对话。
7. 负向测试：在“麦克风”里移除浏览器权限，刷新页面后再次开启语音。
   - 页面不应崩溃；
   - 应显示麦克风不可用/拒绝授权；
   - 文字对话仍应正常。

   自动化等价做法（2026-09-13 复验通过）：用 CDP 把该来源的麦克风权限置为 `denied` 再刷新，
   页面侧拿到与系统摘除权限相同的 `NotAllowedError`：

   ```js
   const cdp = await page.context().newCDPSession(page);
   await cdp.send("Browser.setPermission", {
     permission: { name: "microphone" },
     setting: "denied",
     origin: "http://127.0.0.1:8736",
   });
   ```

   实测结果：页面正常、常开监听提示「无法访问麦克风（常开监听需要授权）」、
   按键说话提示「无法访问麦克风，请在浏览器 / 系统设置中授权后重试」、文字对话仍可用；
   把 setting 改回 `granted` 刷新后回到「聆听中」。

> 如果系统提示“未配置语音供应商”，说明还没有配置 STT/TTS，麦克风测试会停在权限之后。

## 拷贝到 Windows

不要直接复制整个文件夹，尤其不要复制：

- `.venv`
- `node_modules`
- `data`
- `.env`
- `apps/desktop/src-tauri/target`
- `apps/web/dist`
- `apps/desktop/dist`

在 macOS 生成干净源码包：

```bash
cd "/Users/lxb/Documents"
zip -r 栖灵-Windows-src.zip "desktop assistant project" \
  -x "*/.venv/*" \
  -x "*/node_modules/*" \
  -x "*/data/*" \
  -x "*/.env" \
  -x "*/apps/desktop/src-tauri/target/*" \
  -x "*/apps/web/dist/*" \
  -x "*/apps/desktop/dist/*"
```

把 `栖灵-Windows-src.zip` 放到共享分区、U 盘或网盘，再在 Windows 解压。

## Windows 环境安装

需要安装：

- Python 3.12
- Node.js LTS
- Rust（MSVC toolchain）
- Visual Studio Build Tools，包含 C++ 桌面开发
- WebView2（Windows 10/11 通常已内置）

在项目根目录打开 PowerShell：

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e packages\contracts\py -r services\ai-service\requirements.txt

cd apps\web
npm install
npm run build

cd ..\desktop
npm install
npm run tauri dev
```

如果只测试浏览器主界面，可以先跑服务：

```powershell
cd services\ai-service
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8736
```

Windows 的麦克风权限位置：

```text
设置 → 隐私和安全性 → 麦克风
```

允许浏览器访问麦克风；如果是 Edge，也要确认“允许桌面应用访问麦克风”没有被关闭。

## Windows 回归范围

到了 Windows 阶段至少测试：

1. `.venv/Scripts/python.exe` 能拉起 ai-service。
2. 启动器/挂件窗口正常，浏览器主界面能打开。
3. 文字对话可用。
4. 浏览器麦克风授权和语音对话可用。
5. 拒绝麦克风后仍能文字对话。
6. 关闭启动器后 uvicorn 退出。
7. 有真实 Codex 任务时，Codex CLI/ACP 配置按 Windows 本地安装路径再检查一遍。

## Windows v0.1 安装包实装验收（外部协作者任务卡）

> 2026-10-15 建卡。对应 `docs/RELEASE-PLAN-2026-10-10.md` §E「Windows x64 `.exe` 实装 + 真机截图」与 §F「全新环境走通安装 → 启动 → 核心闭环」。
> 执行方：WorkBuddy（Windows 真机）。发起方：mac（作者本机为 Intel macOS，无 Windows 环境）。

### 上下文

- 安装包：GitHub Actions → workflow `release-desktop`（手动触发）→ artifact `Qiling-0.1.0_windows_x64`（约 79MB，NSIS `.exe`）。
  **最终 run：`39736528601`（2026-10-22，artifact 80MB）** —— 构建自含 vault 路径修复的 `3318ccc`，已不含作者本机路径；取代此前冻结了硬编码路径的 `38662701917`。发卡前只需确认该 run 的 artifact 仍有效。
- 该包**未签名**，首次运行会出 SmartScreen 警告，属预期行为，不算缺陷；点「更多信息 → 仍要运行」继续。
- 环境要求：Windows 10 1809 (build 17763) 及以上，或 Windows 11，x64。ARM Windows 走 x64 模拟，如手头正好是 ARM 机型请顺带记录一句。
- WebView2 Runtime：Win11 自带；Win10 若缺失，NSIS 安装器会自动拉取 bootstrapper。
- 应用数据目录：`%APPDATA%\app.qiling.desktop`（首启时由安装包内的 home 模板播种，约 28M）。
- 服务日志：`%APPDATA%\app.qiling.desktop\data\run\ai-service.log`。

### 交付要求

**「全新用户目录」怎么造**：不需要新建 Windows 系统账户。只要 `%APPDATA%\app.qiling.desktop` 不存在即为全新。若该机此前装过或跑过：先完全退出应用（含托盘），把该目录改名为 `app.qiling.desktop.bak-<日期>`，再开始。

**执行步骤**（每一步截图，文件名按序号命名）：

1. 双击 `.exe`，SmartScreen 警告出现 → 截图 → 「更多信息 → 仍要运行」。
2. NSIS 安装向导首页（含版本号）→ 截图。
3. 安装进度中 → 截图。
4. 安装完成页 → 截图。
5. 首次启动，等待窗口出现 → 截图。
6. 首次配置向导第 1 步（LLM，必填）→ 截图。填一个可用的 OpenAI 兼容端点与 key。
7. 向导第 2 步（角色选择，读 `/api/personas`）→ 截图，确认三个角色可选。
8. 向导第 3 步（语音，可选）→ 截图。无 key 可直接跳过，记录跳过是否顺畅。
9. 主界面加载完成，服务状态为正常 → 截图。判据（2026-10-22 起）：`GET /api/health` 顶层 `status` 为 **`ok` 或 `degraded` 都算通过**——语音是可选项，没填 key 时语音诊断为 `degraded`，顶层随之 `degraded`，属预期；只有 **`error`** 才是失败（把 `diagnostics` 里 `status=error` 的项名记下来）。
10. 桌面挂件出现且可拖动 → 截图。
11. 文字对话发一条，收到回复 → 截图。
12. 语音对话一轮（麦克风授权 → 说话 → STT → 回复 → TTS 播报）→ 截图。若麦克风不可用，改为验证「拒绝麦克风后仍能文字对话」并说明。
13. 关闭主界面/退出应用，确认后台 ai-service 进程一并退出（任务管理器搜 `ai-service`）→ 截图。

**回传物**：

- 上述截图（打包成一个 zip）。
- 一段结论：逐条标注 1-13 通过/失败，失败项附现象一句话。
- 任一失败项：附 `%APPDATA%\app.qiling.desktop\data\run\ai-service.log` 的末尾 100 行。

### 质量预期与红线

- 验收标准：步骤 1-11、13 全部通过即视为 v0.1 Windows 端可发布；步骤 12 视麦克风条件，允许以降级验证替代但必须写明。
- 只读验收：**不要修改仓库任何代码或文档，不要提交、不要推送**。发现问题只回传报告，修复由作者侧处理。
- 不要在回传内容里包含真实 API key；截图若拍到 key 输入框请先打码。
