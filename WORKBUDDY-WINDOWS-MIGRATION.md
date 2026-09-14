# DeskMate Windows 迁移与验收操作方案

> 版本：2026-09-13
> 用途：在进入 Windows 双系统后，交给 WorkBuddy 读取并分阶段指导 DeskMate 的源码迁移、环境安装、启动和回归测试。WorkBuddy 只负责检查、解释、给出下一步和记录结果；所有安装、启动、测试和修改动作由用户确认后手动执行。
> 项目目录：`D:\Projects\desktop-assistant`
> 文档文件名：`WORKBUDDY-WINDOWS-MIGRATION.md`

## 1. 给 WorkBuddy 的总任务

请协助在 Windows 上恢复并验证 DeskMate 项目，目标是：

1. 保留当前 macOS 工作区中的全部源码、文档和未提交修改。
2. 不复用 macOS 的 Python、Node.js 或 Rust 构建产物。
3. 在 Windows 重新安装依赖并启动 DeskMate。
4. 按本文档的顺序执行检查。
5. 每次只处理一个步骤。先检查当前条件，再给出一条或一组明确命令，等待用户手动执行并回报结果后再进入下一步。
6. 遇到错误先停止当前步骤，报告完整错误、执行目录和已完成步骤，不要擅自删除数据或修改项目架构。
7. 不要自动安装软件、执行命令、启动服务、关闭进程、修改文件、写入 API Key 或连续跑完整流程。

## 2. 迁移包要求

### 必须保留

- `apps/`
- `services/`
- `packages/`
- `config/`
- `docs/`
- `scripts/`
- `.git/`
- `.gitignore`
- `.env.example`
- `data/persona-assets/`（当前角色图片和 `asset-manifest.json`）
- 当前所有未提交的源码和文档修改

### 不要从 macOS 复制

- `.venv/`
- `apps/web/node_modules/`
- `apps/desktop/node_modules/`
- `apps/desktop/src-tauri/target/`
- `apps/web/dist/`
- `apps/desktop/dist/`
- `.pytest_cache/`
- `__pycache__/`
- `.env`
- `data/` 中除 `data/persona-assets/` 以外的运行时数据、日志、音频、会话和缓存
- `.research/`（调研阶段克隆的参考仓库，未被 git 跟踪，代码中零引用）
- `.firecrawl/`（网页抓取缓存，已进 `.gitignore`，代码中零引用）

Windows 上只恢复 `data/persona-assets/`。不要把 macOS 的整个 `data/` 目录覆盖到 Windows 新环境中。
上面前两项仅用于压缩包减重，不影响 `scripts/check.sh`、类型检查或任何运行时路径。

## 3. macOS 生成源码包

在 macOS 项目父目录执行。该流程保留 `.git`、未提交修改和当前角色图片，排除跨平台依赖与运行时数据：

```bash
cd "/Users/lxb/Documents"
rm -f DeskMate-Windows-src-2026-09-13.zip
cp "desktop assistant project/WORKBUDDY-WINDOWS-MIGRATION.md" \
  "WORKBUDDY-WINDOWS-MIGRATION.md"
ditto "desktop assistant project" "DeskMate-Windows-src-2026-09-13"
cd "DeskMate-Windows-src-2026-09-13"
rm -rf .venv .pytest_cache apps/web/node_modules apps/desktop/node_modules \
  apps/web/dist apps/desktop/dist apps/desktop/src-tauri/target data \
  .research .firecrawl
mkdir -p data
ditto "../desktop assistant project/data/persona-assets" "data/persona-assets"
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f -name .env -delete
git gc --prune=now --quiet   # 仅压缩副本的 .git；原仓库不受影响
cd ..
zip -r DeskMate-Windows-src-2026-09-13.zip "DeskMate-Windows-src-2026-09-13"
rm -rf "DeskMate-Windows-src-2026-09-13"
```

上传夸克网盘时上传两个文件：

```text
DeskMate-Windows-src-2026-09-13.zip
WORKBUDDY-WINDOWS-MIGRATION.md
```

切换到 Windows 后，先把单独的 `WORKBUDDY-WINDOWS-MIGRATION.md` 交给 WorkBuddy 读取，再下载和解压源码包。WorkBuddy 应先依据文档检查环境和迁移包，不要直接开始安装或连续执行命令。

源码包打包完成后，手动确认压缩包中包含：

```text
DeskMate-Windows-src-2026-09-13/data/persona-assets/default/avatar.png
DeskMate-Windows-src-2026-09-13/data/persona-assets/persona_2/avatar.png
DeskMate-Windows-src-2026-09-13/data/persona-assets/*/asset-manifest.json
```

如果还要保留 `data/` 中其他用户数据，不要把它们放进源码包；应先单独备份，并在 Windows 上逐项确认后再恢复。

## 4. 移动硬盘方案

### 推荐格式：exFAT

如果移动硬盘需要同时被 macOS 和 Windows 读写，建议使用 `exFAT`：

- macOS 原生读写
- Windows 原生读写
- 适合大文件
- 不受 FAT32 单文件 4GB 限制

不建议使用：

- `APFS`：macOS 读写正常，Windows 默认不能直接读写
- `NTFS`：Windows 读写正常，macOS 默认通常只能读取
- `FAT32`：兼容性高，但单文件不能超过 4GB

### 分区注意事项

“压缩一部分空间再格式化”可以实现，但会有数据风险。正确顺序是：

1. 先确认移动硬盘真实容量、分区表和现有数据。
2. 把硬盘中所有重要文件备份到其他位置。
3. 在磁盘工具中缩小原分区，腾出未分配空间。
4. 只把腾出的新分区格式化为 `exFAT`。
5. 在 macOS 和 Windows 分别新建、复制、删除一个测试文件。
6. 验证通过后再用于 DeskMate 迁移。

如果原分区是 NTFS，macOS 可能无法可靠地缩小或写入该分区。此时不要强行操作；优先在 Windows 的“磁盘管理”中调整分区，或者把移动硬盘整体备份后重新分区。

如果不需要保留移动硬盘现有数据，最简单且风险最低的方案是：

```text
完整备份移动硬盘
→ 整盘重新分区
→ 建立一个 exFAT 分区
```

在没有确认硬盘名称、容量、现有分区和备份完成前，WorkBuddy 不得执行格式化、删除分区或覆盖复制。

## 5. WorkBuddy 的分阶段协作规则

WorkBuddy 读取本文件后，必须遵循以下交互方式：

1. 先读取本文件，并报告当前阶段、目标目录和待确认事项。
2. 只做只读检查，确认 Windows 命令是否可用、项目是否解压完整、角色资产是否存在。
3. 检查完成后，只给出当前阶段需要用户手动执行的命令，不自动执行。
4. 用户执行后，把终端原始输出或结果发给 WorkBuddy。
5. WorkBuddy 根据结果标记“通过 / 失败 / 未执行”，解释错误，并决定是否可以进入下一阶段。
6. 只有用户明确说“已完成第 X 步”或提供了结果，WorkBuddy 才能继续指导下一步。
7. 安装、启动和测试阶段都必须逐阶段确认，不得一次性输出并要求用户连续执行全部命令。

WorkBuddy 每次回复使用以下简短格式：

```text
当前阶段：
已确认：
需要你手动执行：
预期结果：
请回传：
```

## 6. Windows 前置软件

请安装以下软件，并使用能被命令行找到的版本：

1. Git for Windows
2. Python 3.12 或更高版本
3. Node.js LTS
4. Rustup，并安装 MSVC 工具链
5. Visual Studio Build Tools
   - 勾选“使用 C++ 的桌面开发”
   - 勾选 Windows SDK
6. Microsoft Edge WebView2 Runtime

安装后在 PowerShell 或 Git Bash 检查：

```powershell
git --version
py --version
node --version
npm --version
rustc --version
cargo --version
```

如果缺少命令，WorkBuddy 只报告缺少的工具、安装建议和检查命令，等待用户安装完成后重新检查；不要自动安装，也不要继续安装项目依赖。

## 7. Windows 项目初始化

### 7.1 先处理上一轮遗留（2026-09-12 包）

上一轮 Windows 测试使用的源码包与解压目录很可能仍在磁盘上。WorkBuddy 必须先做只读检查，
把结果报给用户，**不要自动删除、移动或覆盖任何旧目录**。需要确认的位置：

```text
下载目录中的 DeskMate-Windows-src-2026-09-12.zip
D:\Projects\desktop-assistant（是否已存在上一轮内容）
其它形如 desktop-assistant-2026-09-12 的旧解压目录
```

处理原则：**新包独立解压，旧目录改名保留，不做原地覆盖，不做 Git 合并。**

1. 若 `D:\Projects\desktop-assistant` 已存在上一轮内容：先由用户确认，把它**改名**为
   `D:\Projects\desktop-assistant-2026-09-12`（改名可回退，删除不可回退），再把本轮新包解压到
   `D:\Projects\desktop-assistant`。
2. 解压前先从旧目录里取出**只有旧目录才有的东西**，逐项让用户确认后再复制进新目录：
   - `.env`：密钥文件，新包刻意不带，是唯一无法重新生成的内容；
   - `data/` 中需要延续的运行时数据（会话、任务、记忆）：确认后再恢复；
   - `data/persona-assets/`：以新包里的为准，不要从旧目录覆盖。
3. 先从旧目录执行并回传结果，由用户判断是否有需要迁移的手改源码：

   ```powershell
   cd D:\Projects\desktop-assistant-2026-09-12
   git status
   git diff --stat
   ```

   有本地修改时，逐条列出并交用户决定，不要自动搬运或 `git stash`/`reset`。
4. 明确禁止：直接删除旧目录；把旧 `node_modules`、`.venv`、`src-tauri\target` 复制进新目录
   （跨版本二进制依赖会直接坏掉）；把旧目录的 `.git` 合并进新目录的 `.git`
   （两个包是不同快照，合并只会产生无意义冲突）；覆盖用户在旧目录里的数据。
5. 旧压缩包先不删。确认本轮验收通过后，再由用户自行清理磁盘。

### 7.2 解压当前源码包

将源码包解压到：

```text
D:\Projects\desktop-assistant
```

WorkBuddy 先让用户确认项目已解压到目标目录、磁盘空间充足，并检查以下路径存在：

```text
D:\Projects\desktop-assistant\apps
D:\Projects\desktop-assistant\services
D:\Projects\desktop-assistant\packages
D:\Projects\desktop-assistant\data\persona-assets
D:\Projects\desktop-assistant\.git
```

确认后，WorkBuddy 一次只提示一个初始化阶段。推荐使用 PowerShell。下面的命令按区块执行，不要一次性连续执行：

```powershell
cd D:\Projects\desktop-assistant
py -3.12 -m venv .venv
```

虚拟环境创建成功后，再执行：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e packages\contracts\py -r services\ai-service\requirements.txt
```

Python 依赖安装成功后，再执行：

```powershell
cd apps\web
npm install
npm run build
```

Web 构建成功后，再执行：

```powershell
cd ..\desktop
npm install
```

用户每执行完一个区块，应把完整输出发回 WorkBuddy。WorkBuddy 确认该区块成功后，再提示下一个区块。当前项目已有 `scripts/setup.sh`，没有 `setup.ps1`，不要假设存在 PowerShell 初始化脚本。

## 8. 第一次检查

`scripts/check.sh` 当前写死了 macOS/Linux 的 `.venv/bin/python`，Windows 上不要直接运行。WorkBuddy 应让用户使用以下 PowerShell 等价检查，不要自动执行：

```powershell
cd D:\Projects\desktop-assistant\services\ai-service
..\..\.venv\Scripts\python.exe -m pytest -q
cd ..\..\apps\web
npm run typecheck
cd ..\desktop
npm run typecheck
```

验收标准：

- Python 测试全部通过
- Web typecheck 通过
- Desktop typecheck 通过
- 不因路径分隔符、编码或权限产生异常

## 9. 启动验证

### 只启动 AI 服务

启动服务会占用当前终端。WorkBuddy 先提示用户打开一个新的 PowerShell 窗口，再由用户手动执行。服务启动后，用户把启动输出发回 WorkBuddy。

Git Bash：

```bash
cd /d/Projects/desktop-assistant
./.venv/Scripts/python.exe -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8736
```

PowerShell：

```powershell
cd D:\Projects\desktop-assistant\services\ai-service
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8736
```

浏览器打开：

```text
http://127.0.0.1:8736/
```

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8736/api/health
```

预期：

- HTTP 200
- `status` 为 `ok`
- 主界面可以打开
- 文字对话可用

### 启动桌面挂件

另开一个终端：

```powershell
cd D:\Projects\desktop-assistant\apps\desktop
npm run tauri dev
```

预期：

- Tauri 能启动
- 桌面挂件出现
- 本地服务能自动拉起或连接
- 双击挂件可以打开浏览器主界面
- 关闭 Tauri 后 `uvicorn` 子进程退出

## 10. Windows 回归清单

按顺序执行，每项记录“通过 / 失败 / 未执行”：

1. 项目路径不含中文或特殊字符。
2. Python 虚拟环境创建成功。
3. Python 依赖安装成功。
4. Web 依赖安装和生产构建成功。
5. Desktop 依赖安装成功。
6. PowerShell 等价检查通过（Windows 不要直接运行 `scripts/check.sh`）。
7. `/api/health` 返回正常。
8. 浏览器主界面能打开。
9. 文字对话能完成一问一答。
10. 进入“对话”页面后，麦克风权限允许时语音输入可用。
11. 关闭“自动播报回复”后，语音输入仍可用，普通回复不自动播放。
12. 关闭自动播报后，长回复仍会打开网页并显示全文。
13. 拒绝浏览器麦克风权限后，页面不崩溃，文字对话仍可用。
14. 角色卡页面可以读取角色。
15. 当前角色形象可以显示；如导入了 `data/persona-assets`，验证挂件也显示同一形象。
16. “我的智能体”能显示 Codex 状态。
17. 没有 Codex 时任务保留在队列，并显示不可用原因。
18. 关闭 Tauri 后没有残留 `uvicorn` 进程和 `8736` 端口监听。

## 11. WorkBuddy 配置接口

DeskMate 当前已经在“我的智能体”页面为 WorkBuddy 留出配置入口：

1. 启动 DeskMate 并打开浏览器主界面。
2. 进入“我的智能体”。
3. 找到 `WorkBuddy` 卡片。
4. 点击“配置”。
5. 填写 WorkBuddy 的命令名或绝对路径，例如：

```text
workbuddy
```

或：

```text
C:\Users\<用户名>\AppData\Local\Programs\WorkBuddy\workbuddy.exe
```

6. 点击“保存”。
7. 点击“刷新”，确认 WorkBuddy 的探测结果。

该配置会写入：

```text
config\agents.local.yaml
```

当前接口保存的字段是：

```yaml
executors:
  - name: workbuddy
    config:
      workbuddy_command: workbuddy
```

WorkBuddy 适配器已完成 ACP/stdio 真实接入：

- 可以保存命令或路径，并自动复用 WorkBuddy 自带 Electron 作为 Node，无需用户另装 Node。
- 会先通过 `initialize + session/new` 探测安装状态和登录态；未登录会明确提示先登录，不会伪装成可用。
- 登录后可在 DeskMate 任务台提交真实任务、查看进度、取消和回收子进程。
- `read-only` 模式已在 macOS 完成真实只读任务、取消和错误路径复验；Windows 仍需按本文档执行平台回归。

WorkBuddy 使用前必须由用户在桌面端完成登录。DeskMate 不保存 WorkBuddy 账号，也不代替用户登录。

## 12. WorkBuddy / Codex 执行边界

WorkBuddy 协助指导安装和测试时必须遵守：

- 只读检查可以由 WorkBuddy 执行；任何会产生副作用的命令必须先展示给用户并等待用户手动执行。
- 不得自动连续执行多个阶段。
- 不得把“建议执行”描述成“已经执行”。
- 不得要求用户盲目粘贴未解释的长脚本；每个命令区块都要说明目的和预期结果。
- 不删除 `.git`。
- 不重置或覆盖用户未提交修改。
- 不运行 `git reset --hard`、`git clean -fd`。
- 不覆盖 `.env`、API key、用户记忆、角色资产或任务数据。
- 不把 Windows 依赖提交到 Git。
- 不为了通过测试修改产品逻辑。
- 发现 macOS 专用路径时，优先使用项目根目录相对路径。
- 发现端口被占用时，先报告占用进程，不直接结束未知进程。
- 需要格式化磁盘、删除分区、修改权限或上传文件时，必须暂停并等待用户确认。

## 13. WorkBuddy 首条指令模板

```text
你现在负责协助恢复 Windows 上的 DeskMate 项目。

项目目录：D:\Projects\desktop-assistant
权威操作文档：WORKBUDDY-WINDOWS-MIGRATION.md

请严格按文档第 5 节开始协助我：
1. 先只读检查 Git、Python、Node、npm、Rust、Cargo、项目路径和角色资产是否存在。
2. 报告当前环境检查结果，不要自动安装任何软件或依赖。
3. 每次只给我当前阶段需要手动执行的命令，并说明目的、预期结果和需要回传的内容。
4. 等我执行并回传结果后，再判断是否进入下一阶段。
5. 安装依赖、启动服务、运行测试和关闭服务都必须由我手动确认和执行。
6. 不要自动连续执行，不要擅自修改文件、删除数据、重置 Git、格式化磁盘或覆盖用户数据。
7. 遇到错误先停止当前阶段，解释原因和可选处理方式，不要猜测性修改。
```

## 14. 完成标准

Windows 迁移只有在以下条件全部满足后才算完成：

- Python、Web、Desktop 检查通过。
- AI 服务可以在 `127.0.0.1:8736` 启动。
- 桌面挂件可以启动并连接服务。
- 文字对话可用。
- 麦克风允许和拒绝两种结果都已验证。
- 自动播报开关行为符合预期。
- 长回复自动打开网页的行为保留。
- Codex 可用或不可用时都有清晰结果。
- 关闭 DeskMate 后没有残留服务进程。
