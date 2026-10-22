# 栖灵发布与版本实施计划（2026-10-10）

> 对照 `docs/GITHUB-PUBLISH-PREP-2026-10-02.md`（M1–M6 里程碑）制定。
> 原则：未达硬门槛不公开；删除 / 历史改写 / 推送等高危动作逐次授权，不擅自执行。
> 协议已于 2026-10-10 改为 **PolyForm Noncommercial 1.0.0 + 作者保留商业授权**。

---

## 一、版本节奏总览

| 版本 | 主题 | 状态 |
| --- | --- | --- |
| **v0.1** | 中英双语 + 现有核心闭环，首次公开 | 进行中（协议已落地，见下） |
| **v0.2** | 可自定义工作台（用户自行新增条目） | 目标，已调研 |
| **v0.3** | 电商 / 跨境 / 数据处理垂直模板 | 目标 |

每次发布配一篇更新说明，制造持续更新信号。

---

## 二、v0.1 发布实施步骤

### 已完成
- [x] M1 定名：栖灵 / Qiling，bundle id `app.qiling.desktop`（2026-10-07）
- [x] M2 UI 美化一轮（桌面 + 390px 截图验收 2026-10-09）
- [x] 中英双语：`react-i18next`，导航/服务状态双语；语言写回 `AppSettings.ui.language`
- [x] `apps/web` 构建通过（2026-10-10）
- [x] **M4 协议**：`LICENSE` 替换为 PolyForm Noncommercial 1.0.0（2026-10-10）

### 待办（按顺序）
1. **README 对齐协议**：补 License 段落（PolyForm Noncommercial + 商业授权联系方式）、双语开关说明；更新过时的「Step 9 进行中」进度表述。
2. **M3 全库审计（质量项）**：本地复跑 `.github/workflows/security-scan.yml` 里的 gitleaks / bandit / pip-audit / npm audit / cargo audit，整理成分级问题清单；补一次依赖 license 白名单核对（确认新引入 3 个 MIT 依赖无冲突）。
   - ✅ 已完成（2026-10-11）：见 `docs/SECURITY-AUDIT-2026-10-11.md`。无高危阻塞；cryptography 48.0.1 经复核保持现状（49+ 无 Intel Mac wheel 且 CVE 路径零暴露）；tailwind/source-map-js 告警仅构建链，不阻塞。
3. **硬阻塞 A — 移除禁止再分发 VRM（高危，需单独授权）**：
   - 当前工作区仍跟踪 `data/persona-assets/{komano,k81,vrm_demo}/model.vrm`（64M / 31M / 38M）。
   - 步骤：先用可再分发资产（`scripts/vrm/build_qiling_vrm.py` 产出的自制 VRM，`allow_redistribution=True`）替换默认引用 → 从工作区移除三个第三方 VRM → 验证应用默认形象可加载。
   - 删除前需用户确认这些模型已另行备份。
4. **硬阻塞 B — 清理 git 历史 + 大二进制（高危，需单独授权）**：
   - `.git` 当前 **956M**；历史含上述三个 VRM（合计 ~140M）及早期 9M 版本。
   - 用 `git filter-repo`（推荐）在公开前清历史；操作不可逆、会改变所有 commit hash，私有阶段做。
   - 清理后核对：历史无禁止 VRM、仓库体积可接受、gitleaks 复跑通过。
   - Mixamo 参考片派生的 `data/motion-library`（15 条修正后 VRMA）授权口径已核对（2026-10-11，`docs/MIXAMO-LICENSE-2026-10-11.md`）：随仓库和安装包分发，并在根目录 `NOTICE` 声明“由 Mixamo 参考片逐帧重定向派生、非原始文件”。
5. **M5 打包 + 真机**：定打包形态（是否内置 Python/ai-service sidecar）；`npm run tauri build` 出 `.dmg` / `.msi`，双平台实装验证；Windows 真机截图补齐。
   - **⚠️ 芯片架构 / 系统版本口径（2026-10-11 核实，打包时逐条照做）**：
     - **macOS 出一份 universal 包**：先 `rustup target add x86_64-apple-darwin aarch64-apple-darwin`，再 `npm run tauri build -- --target universal-apple-darwin`，一份 `.dmg` 通吃 Intel + M 系（体积约单架构两倍，可接受）。代码层已双架构就绪：Rust 依赖纯源码、Python 依赖均有双架构 wheel、`requirements.txt` 已锁 Intel 的 `cryptography<49`。
     - **macOS 系统下限定为 12.0 (Monterey)**，打包时显式 `export MACOSX_DEPLOYMENT_TARGET=12.0`：Tauri 2 自身要求 10.15+，但 Python 3.11+ 预编译 wheel（pillow/cryptography/playwright 等）普遍按 macOS 12 编译，定 10.15 会在 universal 构建期报 "minimum OS version does not match deployment target"，且 M 系 Mac 物理下限就是 11。当前项目**没有任何显式版本声明**（`bundle.active=false`），不设就由构建机 SDK 决定，不可控。
     - **Windows 只出 x64 一份**：Windows 11 on ARM 内置 x64 模拟，安装运行无感，社区主流做法即 ARM 走模拟；原生 `aarch64-pc-windows-msvc` 需要 VS "C++ ARM64 生成工具" 且 NSIS 安装器本体仍是 x86，收益低，暂不做。
     - **Windows 系统下限定 Windows 10 1809 (build 17763) / Windows 11**；NSIS 安装包开启 WebView2 bootstrapper（Win10 可能未装 WebView2 Runtime，Win11 自带；Tauri 2.9+ 用全局 `bundle.windows.minimumWebview2Version`）。
     - **签名公证是分发硬门槛**：macOS 不签名 + 公证，arm64 机器 Gatekeeper 拦截最严；Windows 不签名有 SmartScreen 首运警告（不影响运行）。需 Apple Developer 账号 / Windows 证书，发布前确认。
     - **CI / 真机补充**：现有 `cross-platform-regression.yml` 的 macos-15（arm64）只跑后端测试，未构建 Tauri；打包前加 arm64 mac 与 windows x64 的 `tauri build` 冒烟；M 系真机至少一次实装验收（当前桌面端只有 Intel 真机记录）。
     - 运行时外部二进制（Codex CLI、Playwright chromium）不进安装包，按用户机器架构各自安装，无打包负担；但需在 M 系真机确认 `scripts/launch-desktop-macos.sh` 的 PATH（已写死 `/opt/homebrew/bin`，Intel Homebrew 在 `/usr/local/bin`，目前靠 PATH 容错但未按架构区分）。
6. **公开前最终核对**：`.env` / API key / 运行数据确认不入库；CI 两个 workflow 跑通；Releases 文案与截图就位。
7. **M6 发布（需授权推送）**：公开仓库 + 挂 Release；随后启动宣传。

### 首次向导增强 + 启动自检（向导完成后紧接着做）
> 2026-10-10 决定：与首次配置向导合并推进，先把向导做完，再做启动自检。
> 事实源统一复用 `GET /api/health`（已返回整体 `status` + 逐项 `diagnostics`：`label`/`status`/`detail`/`fix_hint`/`fix_action`），不另写一套检查。
- [x] 向导增强：`SetupWizard` 已扩为 3 步（LLM 必填 → 角色选择 → 语音可选），角色步读 `/api/personas`、写 `active_persona_id`（2026-10-11）。
- [x] Web 启动自检呈现：health 顶层 `status` 按 diagnostics 聚合（error/degraded/ok）；`error` → 阻断式卡片，`degraded`（带 fix_action）→ 可关闭横幅，正常静默；`fix_action` 渲染「去设置 / 去智能体」按钮（2026-10-11）。
- [x] 挂件侧：`pollHealth` 保持只判通断；WS 本身 3s 自动重连，断连气泡可点击「打开主界面」，详细诊断不进挂件（2026-10-11）。
- [ ] 真实握手探测（第二阶段）：LLM 当前只判是否 echo、不验证 key 有效性；启动时对 LLM/TTS 做一次廉价探测（拉 models 或 1 token），覆盖错 key / 过期场景。

### 发布后宣传（v0.1）
- 渠道：LINUX DO、V2EX、即刻 / 少数派、知乎、相关 Telegram/QQ 群；GitHub 首屏 README + 截图。
- 素材：一句话定位 + 3 张以内截图/GIF + 安装步骤；突出「本地优先 + 角色化 + 语音/执行闭环」。
- 预埋 v0.2 话题（工作台即将上线），为二次更新蓄势。

---

## 三、v0.2 目标：可自定义工作台

**第一版（最小可用，纯本地、低风险）**
- `＋添加条目` 表单；类型三种：快捷链接（可分组）、内嵌网页 iframe、栖灵内置功能入口。
- 开箱模块：便签、待办清单、多时区时钟。
- 排序/显隐：`@dnd-kit/*`（MIT）。
- 数据源：在 `AppSettings` 增加 `workbench.items[]`（涉及后端 schema + contracts 同步，需单独评估）。

**第二版（联网可选）**
- 实时汇率、翻译卡片（复用栖灵 AI）、日历对接、自定义 API/KPI 数据卡、RSS、番茄钟。

参考：Dashy / Homarr / Heimdall（MIT/Apache，可借鉴）；Homepage(GPL) / Glance(AGPL) 仅看思路。

## 四、v0.3 目标：垂直行业模板

- **电商运营**：平台入口分组、营销日历、订单/库存/消息指标卡（多数需平台 API）。
- **跨境业务**：汇率卡、多时区时钟、翻译入口、海外平台 / 物流入口、合规待办。
- **数据处理**：数据源 / 报表入口、数据集卡片、SQL / Notebook 入口、KPI 卡。
- 形态：以「模板包」一键初始化工作台；实时数据类模块按需授权联网。

---

## 五、风险与红线
- 协议必须在**首次推送前**落地；MIT 已发出的授权无法事后收回（本次仓库尚未公开，可安全替换）。
- 删除 VRM、改写历史、推送 / 发布均为高危或外部副作用，每步单独授权。
- 历史改写会断所有 commit hash 并需强制推送，须在私有阶段、备份后进行。

---

## 六、v0.1 发布前检查表（每日核对用）

### A. 合规与协议
- [x] LICENSE 替换为 PolyForm Noncommercial 1.0.0
- [x] README 对齐协议、双语说明、版本路线
- [x] 依赖许可证白名单核对（无 GPL/AGPL 混入，含新增 3 个 MIT，2026-10-11）

### B. 安全审计（M3，只读）
- [x] gitleaks：90 commits 扫描，无泄露（2026-10-10）
- [x] gitleaks 复跑：历史改写后 95 commits，0 leaks（2026-10-11）
- [x] bandit（Python）：35 Low，0 中/高危
- [x] npm audit（web / desktop）：web 生产 0；devDeps 与 desktop 各有构建链告警，不阻塞
- [x] cargo audit（Rust）：0 漏洞，7 warnings（unmaintained/unsound）
- [x] pip-audit（Python 依赖）：cryptography 48.0.1 3 条 CVE，已评估接受（平台无 wheel + 零暴露面，见审计报告 P1）
- [x] 分级问题清单产出：`docs/SECURITY-AUDIT-2026-10-11.md`；无高危项

### C. VRM 资产授权（硬阻塞）
- [x] 自制可再分发 VRM 完成并验证（栖灵 qiling，VRoid 原创，`allowRedistribution=True`+可商用，三道闸+motion-lab 观感验收，2026-10-14）
- [x] 移除 komano / k81 / vrm_demo 三个第三方角色卡（`config/personas/`，2026-10-14）；`data/persona-assets/` 资料库物理文件保留本地（gitignore，不入库不入包）
- [x] 确认 motion-library（Mixamo 参考片派生 VRMA）授权链路：见 `docs/MIXAMO-LICENSE-2026-10-11.md`；**2026-10-21 随仓库和安装包分发，并由 NOTICE 声明派生来源**（用户决策，见 MIXAMO-LICENSE 行动项变更记录）

**C 段发布前剩余要点（2026-10-14 更新）：**
- [x] 代码层默认形象切 qiling（2026-10-14，374 passed + web build 验证）：
  `services/ai-service/app/config.py` 字段兜底改 `active_persona_id="qiling"`，角色卡缺失时回落 `default`（旧安装/精简部署不加载空角色）；
  首次向导 `apps/web/src/App.tsx` SetupWizard 显式默认 qiling，并移除 `personaId !== "default"` 写回特判（用户主动选千问时也正确写回）；
  `.gitignore` 加 `!data/persona-assets/qiling/model.vrm` 例外，自制默认 VRM（18M）随仓库/包分发。
- [x] 2D 立绘分发授权最终确认（2026-10-14 用户拍板）：原始参考图已找不到，千问（default）、蓝猫（persona_2）立绘按当前状态随包保留。
- [ ] 蓝猫走完整 2D 角色路线（用户稍后处理）：单图 `PUT /api/personas/persona_2/avatar`（`normalize_avatar_image` → procedural_2d）已在用；如需眨眼/口型/发飘器官级动效，走分层 PSD → `scripts/import_psd_layers.py` → `layers.json`；并补齐 `config/personas/persona_2.yaml` 字段（`avatar_driver: procedural_2d`、`preset`、`profile`、静默口令）。
- [x] 顺手项：`config/settings.yaml` 的 `voice.activation.persona_name` 与 `config.py` 字段兜底同步改「栖灵」（2026-10-14）。

### D. Git 历史与体积（硬阻塞，高危）
- [x] 备份仓库（`.git` + VRM/VRMA → `~/qiling-backup-20261010`）
- [x] `git filter-repo` 清除历史中的禁分发模型 / 大文件（2026-10-10）
- [x] 核对仓库体积（`.git` 956M → 21M）
- [x] 清理后构建确认功能正常（gitleaks 待 B 阶段统一复跑）
- [x] 清理后完整 check.sh 回归（369 passed + typecheck + vitest，2026-10-10）
- [x] 二次清理残留衍生图（2026-10-15）：`k81/komano/vrm_demo` 的 avatar/original/manifest，以及实验素材 `persona_3/qianwen_t4/realistic_proto`，共 36 个跟踪文件从当前树与全部历史清除；物理文件备份在 `~/qiling-assets-backup-20261015-084838.tar.gz`，本地恢复并 gitignore；清前 bundle 备份 `~/qiling-git-bundle-before-asset-purge-20261015-084838.bundle`；`.git` 29M，远端 main 强推后仅剩 default/persona_2/qiling 三个角色目录。

> 第三方角色 VRM 物理文件仍仅本地保留；`data/motion-library` 的 15 条修正后派生动作随仓库和安装包分发，并由 `NOTICE` 声明来源。
> filter-repo 已移除 origin，已重新配置（不推送）。

### E. 打包与真机（M5）
- [x] 定打包形态（2026-10-14）：**内置 Python sidecar**。PyInstaller onedir 冻结 ai-service（`services/ai-service/ai-service.spec` + `sidecar_entry.py`）；home 模板（config + web dist + 三角色资产，28M）由 Rust 首启拷到 `~/Library/Application Support/app.qiling.desktop`；Rust 按「Resources 里有 sidecar → 打包态，否则走 .venv 开发态」自动分流（`lib.rs`）。构建：`scripts/package/build-macos.sh` + `stage-home.sh`。
- [x] macOS x86_64 `.dmg` 本机构建 + 端到端验证（2026-10-14）：ad-hoc 签名（`codesign --verify --deep --strict` 通过），`Qiling_0.1.0_x64.dmg` 123MB；首启播种、/api/health、UI/角色/头像 200、挂件租约正常。
- [x] **架构口径变更（2026-10-14 决策）：改发 arm64 / intel 两份 DMG，放弃 universal。** 内置 Python sidecar 无法在 Intel 机交叉冻结 arm64（PyInstaller 只能用本机架构 Python/wheels），Reor 等同类产品也是双包。CI 用 macos-13（x64）+ macos-14（arm64）各跑 `scripts/package/build-macos.sh x86_64|aarch64`；`MACOSX_DEPLOYMENT_TARGET=12.0` 维持。→ 口径已落地：x64 本机（2026-10-14）+ arm64 CI（2026-10-15）两份包均已产出。
- [x] macOS arm64 `.dmg`：CI（macos-14）构建成功（2026-10-15，artifact 113MB）。**M 系真机实装验证移出 v0.1 发布清单，延后 v0.1.x 补丁**（2026-10-15 决策：CI 产物已出且与 x64 同一构建脚本，作者本机为 Intel 无 M 系真机，不为借机器阻塞发布）
- [ ] macOS x86_64：全新用户目录实装一次并截图。**做法纠正（2026-10-15）：不需要新建 macOS 系统用户** —— 应用的每用户数据只有 `~/Library/Application Support/app.qiling.desktop`（28M），改名备份即为全新目录，首启会重新播种。本机已有 2026-10-15 12:35 构建的 `Qiling_0.1.0_x64.dmg`（117M，路径 `apps/desktop/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/`），但正式验收取本节末尾「产物重建」后的新包
- [~] macOS x86_64 全新目录实装第一轮（2026-10-15 20:34，**部分通过**）：用修复后重建的 DMG（117M，20:33）装到 `/Applications`，`codesign --verify --deep --strict` valid；旧数据目录改名备份为 `app.qiling.desktop.bak-20261015-203420`；首启播种 28M 正常，`qiling-desktop` + 冻结 `ai-service` 双进程起，`/api/personas`（3 角色）、`/api/agents`（8 执行器）、`/api/health` 均 200。**vault 路径修复已在安装包内验证**：`/api/settings` 的 `obsidian_default_path` 与 `obsidian_vault_path` 均为空串（修复前会是作者 iCloud 路径）。两项未完成：① 截图 —— 终端未获「屏幕录制」权限；② 真实对话一轮 —— `.env` 里 `OPENAI_API_KEY` 与 `DASHSCOPE_API_KEY` 均返回 403 Free quota exhausted（账号额度问题，非打包问题；链路已通到供应商，并把 403 优雅降级成可读错误事件）。**10-16 复测**：屏幕录制权限已授予（系统设置勾选 ChatGPT 与 Codex，无需重启即生效），全屏与窗口级捕获均通过（窗口捕获含栖灵挂件真实内容，遮罩消失），① 解除；STT 端点实测 200（dashscope 逐字回传、约 1.3s），用户真机麦克风对话一轮 + TTS 播报通过（当前 dev 实例），② 全新安装实例待复测。
- [x] Windows x64 NSIS 链路配置完成（2026-10-14）并在 windows-latest runner 构建成功（2026-10-15，artifact 79MB）；真机实装验证仍待做。
- [ ] Windows x64 `.exe` 实装 + 真机截图（ARM Windows 走 x64 模拟，如有条件顺带验证）。**任务卡已建（2026-10-15）**：`docs/CROSS-PLATFORM-TESTING.md` §「Windows v0.1 安装包实装验收（外部协作者任务卡）」，交 WorkBuddy 在 Windows 真机执行，等回传截图与逐项结论
- [x] release CI 落地（2026-10-14）：`.github/workflows/release-desktop.yml` 手动触发，macos-13(x64)/macos-14(arm64)/windows-latest 三 runner，产物上传 artifacts（不公开发布）；构建脚本 `scripts/package/build-macos.sh`、`build-windows.ps1`、跨平台 `stage_home.py`。首次实跑（run 38662701917，2026-10-15）arm64 DMG + Windows EXE 成功；x64 macos-13 因 GitHub runner 容量长时间排队待调度（x64 DMG 已于 2026-10-14 本机 Intel 构建并端到端验证）。
- [x] macOS v0.1 不买 Apple Developer 账号（2026-10-14 拍板）：ad-hoc 签名 + README/Release Notes 写右键打开 / xattr 绕过说明；技术社区先行，后续有非技术用户再补 Developer ID 与公证。Windows 同样不签名，接受 SmartScreen 首运警告。
- [ ] M 系真机核对 `scripts/launch-desktop-macos.sh` PATH（`/opt/homebrew/bin` vs `/usr/local/bin`）→ 随 M 系实机延后 v0.1.x。已核实（2026-10-15）该脚本只在 docs 里被引用，打包链路（`build-macos.sh` / `lib.rs` sidecar 分流）不依赖它，**不影响安装用户**；它另含硬编码 `/Users/lxb/...`，属 F 段公开前清理项

- [x] **三平台产物重建（2026-10-22 完成，CI run `39736528601`）**，取代此前冻结了硬编码 vault 路径的 `38662701917`：
  - **x64**：本机 `build-macos.sh x86_64` 于 10-22 14:41 出包 124MB；挂载后 grep 整个 app（含 `Resources/runtime/ai-service`），作者 iCloud 路径 **0 命中**。
  - **arm64**：CI 成功，产物 120.9MB；同样挂载 grep **0 命中**。
  - **Windows x64**：CI 成功（17m10s），产物 80MB；原始字节 grep **0 命中**。局限：NSIS 安装包为压缩格式，macOS 上无法解包穷举，故以「构建自含 vault 修复的 `3318ccc` + 同链路 x64 挂载验证干净 + 原始 grep 0 命中」三重佐证。
  - 顺带修掉一个 **Windows CI 回归**：`stage_home.py` 在 cp1252 控制台 print 中文会 `UnicodeEncodeError` 崩溃（`3318ccc` 把 stdout/stderr 切 UTF-8）。
  - 已知非阻塞：`macos-13 x64` runner 排队满 24h 超时导致 run 整体显示 cancelled，但 arm64/Windows 产物已上传，x64 改由本机出包。

### F. 公开前最终核对
- [ ] `.env` / API key / 运行数据 / 缓存不入库（复查 `.gitignore`）。**2026-10-15 复查结果**：密钥侧干净（仅 `.env.example` 入库且全是注释占位；无 `.env`/key/pem/音频/db/`__pycache__`/`apps/web/dist` 被跟踪）。但发现两处**个人数据残留，公开前必须处理**：
  1. `data/project_nodes/*.json`（17 个，68K）：**当前树已处理（2026-10-22，`b5bfa07`）** —— `.gitignore` 已含该目录，`git rm --cached` 已补齐，`git ls-files data/project_nodes` 归零，本地文件保留。**未做**：这些文件仍存在于 git 历史中（含本机绝对路径），彻底清除需再跑一次 `filter-repo`，高危、改写历史，待单独授权。
  2. ~~`services/ai-service/app/config.py` 把作者 iCloud vault 路径写成 `DEFAULT_OBSIDIAN_VAULT_PATH`~~ → **已修（2026-10-15）**：默认值改空串，新增 `obsidian_vault_dir()` 统一判空（`Path("")` 会退化成 cwd 且 `is_dir()` 恒真，原逻辑会把进程当前目录误当成用户的库并触发镜像/全文搜索），health/settings/memories 四处调用点改为共用该 helper，补回归测试 `test_unset_vault_path_is_never_treated_as_linked`。作者本机路径存于已 gitignore 的 `data/settings.local.json`，不受影响。
  3. 其余 `/Users/lxb` 出现在 `AGENTS.md`、`WORKBUDDY-WINDOWS-MIGRATION.md`、`scripts/launch-desktop-macos.sh`、`assets/icon/candidates/*.html`、8 个 docs 文件：非密钥，属观感/隐私噪声，公开前决定是否一并参数化（`$HOME`）或保留。
- [x] CI 两个 workflow 跑通（2026-10-15，新历史 `0929f0f`）：cross-platform-regression macOS 干净环境 + Windows 双绿（修掉干净 runner 无 key 时 `test_health` 误断言 ok），security-scan success。release-desktop 见 E 段（x64 待 runner 调度）。
- [ ] Release Notes / 截图 / 安装步骤就位
- [x] **语音未配置不再判 error（2026-10-22 定案，`7d150f5`）**。采纳"语音降为 `degraded`（可关闭横幅，与向导第 3 步「语音可选」一致）"这一口径：`health.py` 语音项非就绪时由 `error` 改 `degraded`，`fix_hint` 标明语音为可选能力；`tests/test_health.py` 补回归断言（8 passed）。向导第 3 步保持可选，不改必填。
- [ ] 全新环境走通安装 → 启动 → 核心闭环（语音 / 对话 / 执行）：macOS x64 侧本机可做（见 E 段「做法纠正」，DMG 已就绪）；Windows 侧已发任务卡给 WorkBuddy（见 E 段与 `docs/CROSS-PLATFORM-TESTING.md`）

### G. 发布与宣传（需授权推送）
- [ ] 公开仓库 + 挂 Release
- [ ] 首波宣传（LINUX DO / V2EX / 即刻 / 少数派 / 知乎 + 社群）
- [ ] 预埋 v0.2 工作台话题
