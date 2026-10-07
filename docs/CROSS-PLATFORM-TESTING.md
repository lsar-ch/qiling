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
