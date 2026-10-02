# 执行器配置入口方案（DeskMate）

> 日期：2026-09-09
> 状态：方案定稿；2026-09-10 完成 codex 单卡片最小版与跨平台策略（回归 90 passed）。
> 外部项目借鉴点见 `docs/EXECUTOR-CONFIG-REFERENCE.md`。
>
> 阶段二已落地（2026-10-01）：执行器主线定为 **ACP**。新增通用 `adapter: acp-cli`
> （`app/agents/acp_cli.py`），claude-code / qwen-code / kimi-cli 由 pending 转为真实
> ACP 执行器；页面配置对这四类适配器（codex / workbuddy / acp-cli）统一开放，专属字段
> 由目录 config 下发（`acp_command` / `api_key_env` / `signup_url` / `login_hint`）。
> 详细决策与实证见 `docs/ACP-DECISION-PACK-2026-10-01.md`。

## 目标

让用户在「我的智能体」页能自行配置执行器，配置越简单越好：

- 能自动检测到的，一律不用填；
- 检测不到的，给出手动路径输入；
- 表单字段由后端目录动态下发，前端不写死。

## 现状与缺口

- `config/agents.yaml` 是执行器目录事实源（codex / workbuddy / acp-cli 真实接入，
  reasonix 仍为 adapter: pending）
- 后端已内置 `config/agents.local.yaml` 按 name 合并覆盖机制（`app/agents/catalog.py`）
- `/api/agents` 只读探测；`/api/agents/config` 已返回完整目录条目，但**没有写接口**
- 前端「执行器状态」卡只有刷新按钮，无编辑入口

## 配置模型

两层配置：

1. 默认层：`config/agents.yaml`（入库，随产品发布）
2. 用户覆盖层：`config/agents.local.yaml`（入库名单外，进 `.gitignore`；
   由页面写，内容 = 被覆盖执行器的部分字段）

覆盖优先级：`agents.local.yaml` > `agents.yaml`。探测与执行都读合并后的结果。

## 交互设计

每张执行器卡片显示：状态胶囊 + 当前生效命令/路径 + 「配置」入口。

配置面板内容（字段来自后端目录）：

- 启用/停用（预留，本轮不做）
- 执行命令/路径：**留空 = 自动检测**（PATH → 常见安装位置）；
  填了 = 手动覆盖（写 `agents.local.yaml`）
- 显示自动检测到的实际路径与缺少组件提示（本体 / ACP）

按钮：`保存` / `恢复自动` / `取消`。保存后立即重新探测并刷新卡片。

## 跨平台策略（macOS / Windows）

路径探测按「统一通道」设计，避免在代码里按系统反复猜路径：

1. 显式注入优先：页面保存的 `agents.local.yaml` 配置（`codex_command`）或环境变量
   `CODEX_PATH`（借鉴 Qwen Audio Agent 的注入通道）优先，值不可用时**不回退**，
   直接提示“该路径不可用”，避免悄悄换一个执行器造成困惑
2. `PATH` 探测：`shutil.which` 原生跨平台，Windows 下自动匹配 `PATHEXT`
   （`.exe/.cmd/.bat`），macOS/Windows 行为一致
3. 平台常见位置兜底：仅用于“没有任何注入”时的自动检测便利，按平台分支
   （win32 查 `%USERPROFILE%\.codex\bin\codex.exe|.cmd`；darwin 查
   Codex.app Resources / `~/.codex/bin` / `~/.local/bin`），不作为硬依赖

平台差异点：

- 可执行判断：POSIX 用 `os.access(X_OK)`；Windows 上该语义失效，以“文件存在”为准，
  是否真的能跑交给探测（`--version`），失败会落入 `error` 状态而不是误报未安装
- Windows 上 codex-acp 常是 `.cmd` wrapper，直接 spawn 有差异，留到 Windows 真机回归验证
- 手动路径以原样字符串存入覆盖层，不做跨系统改写；换机器后重新走一次自动检测即可

验证节奏：macOS 由当前回归与页面验收覆盖；Windows 行为随「Windows 源码迁移 +
同清单回归」阶段真机验证，不提前在 macOS 上模拟。

## 阶段拆分

- 阶段一（本轮，最小版）：codex 单卡片。
  - 自动检测增强：PATH 之外补扫 `/Applications/Codex.app/Contents/Resources/codex`、
    `~/.codex/bin/codex` 等常见位置，探测结果返回实际 command
  - 后端写接口：`PUT /api/agents/{name}/config`（先只放行 codex）
  - 前端：codex 卡片加「配置」，支持手动路径 + 恢复自动
- 阶段二（后续）：放行其余执行器；按 adapter 下发专属字段
  （如 codex 的 `acp_command`；pending 执行器先只配命令/启用）
- 阶段三（后续，未排期）：codex「连接 OpenAI 账号」OAuth 按钮位；
  非 codex 真实 ACP/stdio 接入后开放任务执行

## API 草案

```text
GET /api/agents                  # 已存在：探测状态列表
GET /api/agents/config           # 已存在：目录条目（含 config 字段）
PUT /api/agents/{name}/config    # 本轮新增
```

PUT body：

```json
{ "command": "/path/to/codex" }   // 手动覆盖；null / "" = 恢复自动
```

行为：校验 name → 写 `agents.local.yaml` 覆盖 `config.codex_command`
→ 重载 catalog → 就地重建 registry（避免旧引用失效）→ 返回该执行器最新探测结果。
仅放行 codex（其余返回 400，等阶段二）。

## 本轮改动范围

- 后端：`agents/codex.py`（常见位置探测）、`agents/catalog.py`（本地覆盖写与目录路径解析）、
  `agents/factory.py` + `agents/registry.py`（就地重载）、`api/agents.py`（写接口）、
  新增测试
- 前端：`apps/web/src/api.ts`（配置读写）、`apps/web/src/App.tsx`（codex 卡片配置面板）
- 工程：`.gitignore` 增加 `config/agents.local.yaml`

## 验收

1. codex 在 PATH 或常见位置 → 卡片显示就绪 + 实际命令路径，无需任何配置
2. 填写错误路径保存 → 卡片显示未安装/探测失败且提示该路径不可用；改回空值恢复自动
3. 手动路径写入后重启 ai-service 仍生效（落在 agents.local.yaml）
4. `./scripts/check.sh` 全绿（新增单测覆盖写文件/清除/探测解析）

## 非目标

- 不自动下载/安装执行器（只检测与引导）
- 不做任意环境变量/密钥编辑（沿用设置页本地密钥模式，阶段三再按执行器扩展）
- 不放行非 codex 执行器编辑（阶段二）
