# GitHub 发布前准备纪要（2026-10-02）

> 目的：把「从当前可运行状态」到「GitHub 公开 / 对外分发」之间要做的事、门槛和坑一次列清。
> 使用方式：按里程碑推进，每块独立可验收；未达成硬门槛前不公开仓库。
> 关联：`docs/VRM-ASSET-NOTES.md`（资产授权）、`docs/PROJECT-ROADMAP.md`、`.github/workflows/`。

---

## 0. 结论

- **打包 ≠ 可以公开**。打包解决「别人能装」，公开还要解决「能合法拿源码 / 再分发资产」。
- 目前 4 项未决：**定名、定图标、页面美化、全库合规与漏洞审计**。
- 另有 2 项硬门槛尚未处理：**缺 LICENSE**、**禁止再分发的 VRM 仍在仓库与历史里**。
- 已确认干净：`.env` 未入库、运行数据未入库、git 历史无真实密钥（仅测试串）。

---

## 1. 里程碑路线（建议顺序）

| 里程碑 | 目标 | 阻塞谁 | 验收信号 |
| --- | --- | --- | --- |
| **M1 定名 + 定图标** | 名字与图标冻结 | 阻塞一切外发（安装包、仓库名、发布页） | 改名清单全部落地 + 图标资源生成 |
| **M2 页面美化一轮** | 主界面 / 挂件 / 设置页视觉收口 | 阻塞截图与发布页 | 双平台截图人工验收通过 |
| **M3 全库审计** | 漏洞 + 合规扫一遍 | 阻塞合规清理范围确认 | 报告产出 + 问题清单 |
| **M4 合规清理** | LICENSE + 资产 + 历史和密钥 | 阻塞公开仓库 | 干净历史 + LICENSE 就位 |
| **M5 打包 + 真机** | 双平台安装包产出并验证 | 阻塞分发 | `.dmg` / `.msi` 实装通过 |
| **M6 发布** | Releases 或公开仓库 | — | 仓库可见 / Release 已挂 |

> 说明：M1 越早越好。**首个外发安装包之前必须定名**，否则后面改 bundle id 会断升级链（详见 §2.1）。

---

## 2. 工作块明细

### 2.1 项目 / 软件定名

**影响面（改名要一次改全，别漏）**

| 位置 | 现值 / 说明 |
| --- | --- |
| Tauri `productName` | `DeskMate`（`apps/desktop/src-tauri/tauri.conf.json`） |
| Bundle identifier | `com.deskmate.desktop` |
| 仓库名 | `my-desktop-project`（GitHub，当前 remote） |
| 包名 | `@deskmate/desktop` / `@deskmate/contracts`（`package.json`） |
| Python 包 / 服务名 | `services/ai-service`、`DeskMate` 出现在日志/健康检查/通知文案 |
| 安装包文件名、README 标题、关于页、默认人格叫法、图标资源名 | 需逐一替换 |

**特别注意**

- **`bundle identifier` 一旦随着安装包外发就不能改**：macOS 视为新 App（丢已授权目录、启动项）；Windows 升级路径断裂。所以定名要早于首个对外安装包。
- **商标撞名**：「DeskMate」在海外已有同名产品/公司在用，公开品牌前建议查一遍商标与域名可用性，避免撞车。
- 改名清单建议直接落成一张表，改完逐项打勾，避免遗漏（尤其是散落在文案里的中文名）。

---

### 2.2 图标选定

**要做**

- 定 1024×1024（或 512）源图，用 `tauri icon` 生成 `.icns` / `.ico` / 多尺寸 `.png`（写入 `src-tauri/icons/`）。
- 同步更新：Web favicon、README / 发布页 logo、Releases 缩略图。

**特别注意**

- 图标需满足最小尺寸，否则 Windows 任务栏 / macOS Dock 会糊。
- 若使用第三方图标素材，确认其授权（可商用、可再分发），别用来源不明的图。

---

### 2.3 页面美化一轮

**范围**

- `apps/web` 主界面（含扩展页 / 设置页 / 办公工具 tab）
- 桌面挂件（`apps/desktop`，VRM 舞台 / 气泡 / 控件）

**要做**

- 视觉收口一轮后，**Windows 与 macOS 各截一遍图**比对（同一页面两平台是否一致、有无溢出/错位）。
- 中文换行不溢出；深色/浅色对比度达标；按钮/文本在有 hover、加载、空状态时不塌陷。

**特别注意**

- 改 `apps/web` 后必须重建：`cd apps/web && npm run build`（主界面加载 `dist`）。
- 美化改动会重排布局，容易引入溢出回归，验收以截图为准，别只看测试绿。

---

### 2.4 全库合规与漏洞审计

**已有资产（先复用，别另起一套）**

`.github/workflows/security-scan.yml` 已接：Semgrep、Bandit、pip-audit、npm audit（web/desktop）、cargo audit、gitleaks。

**缺口**

- 现有扫描步骤全是 `continue-on-error: true`，**只出报告、不拦合入**；且只产出 artifact，不生成问题清单。
- 缺 **许可证合规** 扫描（依赖 license 白/黑名单）。
- 缺 **SBOM**（软件物料清单）与 CVE 跟踪。

**建议动作**

1. 本地复跑现有扫描器，把结果整理成**可跟踪的问题清单**（阈值 → 严重度 → 处置）。
2. 追加许可证合规扫描：Python `pip-licenses`、Node `license-checker`、Rust `cargo-deny`（按需，ladder：先看现有工具够不够）。
3. 决定是否把关键扫描从「报告」升级为「门槛」（PR 阻断）。

**特别注意**

- 这轮审计的产出是**清单**，不是「全绿」；要区分「必须修」「可接受风险（记录理由）」「误报」。

---

### 2.5 资产与许可合规清理（硬门槛）

**必须处理**

| 项 | 现状 | 动作 |
| --- | --- | --- |
| LICENSE | **缺失** | 定许可证（MIT / Apache-2.0 / AGPL，取决于是否允许别人闭源二次分发），补 `LICENSE` + 各包声明 |
| 第三方 VRM | `komano`(64M) / `k81`(30M) / `vrm_demo` 均 `allowRedistribution: false`，**已入库** | 从仓库**及 git 历史**移除，或换成可再分发的自制资产 |
| 历史大二进制 | VRM 等 64M+30M 压在历史里 | 与上一条一起，用 `git filter-repo` / BFG 清历史 |
| 密钥 | 已确认无真实密钥 | 公开前仍跑一次 gitleaks 确认 |

**特别注意**

- **「公开 = 再分发」**：`allowRedistribution:false` 的模型一公开就违约，必须先下架（含历史）或替换。
- 中文 PDF 字体（`office_writer.py`）**读取本机系统字体**（macOS Hiragino/PingFang、Windows msyh、Linux Noto CJK），**未随仓库分发**，无字体再分发问题；仅需确认所选字体的 PDF 嵌入权限（系统字体一般允许嵌入）。
- 动作库 `data/motion-library/`（若源自 Mixamo 等）需确认其授权链路。
- **历史改写是不可逆操作**，且会改变所有 commit hash；在私有仓库阶段做最省事，公开前完成。

---

### 2.6 打包与分发

**要做**

- macOS 本机：`cd apps/desktop && npm run tauri build` → `.app` + `.dmg`。
- Windows：`.msi` + `.exe`（NSIS）。
- **Tauri 不支持交叉编译**，各平台包必须在各自平台构建。
- 发布页：README 首屏 + 截图 + 安装步骤 + Release Notes。
- 启用 CI：`cross-platform-regression.yml`（干净安装回归）、`security-scan.yml`。

**特别注意**

- **先定打包形态**：安装包是否内置 Python 运行时 / ai-service（sidecar），还是要求用户先装环境。这决定包体大小和安装步骤，要早定。
- macOS 公证（notarization）需 Apple Developer 账号；Windows 代码签名需证书，否则 SmartScreen 拦截（可选，非硬门槛，但影响体验）。
- Windows 安装包可只挂 GitHub Releases，仓库继续私有——「发安装包」和「开源源码」是两件事。

---

### 2.7 下载量 / 使用量统计（暂不做登录，用户 2026-10-02 决定）

**结论**：不引入账号体系。统计走「下载量用现成计数 + 使用量用匿名打点」，不做登录。

**下载量（零代码）**

- GitHub Releases 自带每个 asset 的下载计数：`GET https://api.github.com/repos/{owner}/{repo}/releases` 里每个 asset 的 `download_count` 字段。
- 公开下载页挂上即自动计；也可用 shields.io 的 release 下载徽章展示。
- 局限：只统计 GitHub 渠道下载，「装没装、装完用没用」看不到。

**使用量（匿名、可关闭）**

- 不建议登录，改用**默认匿名、可关闭、首启弹一次同意**的轻量打点。
- 最小实现：客户端启动 / 关键动作时 `POST` 一个匿名 `/ping`（只带版本号 + 平台 + 随机设备 ID，不带任何身份信息）。
- 现成方案（免自建后端）：Aptabase / Umami / Plausible，都是隐私友好的轻量分析。
- 首启弹一次同意开关，写进 `data/settings.local.json`；关闭后不再上报。

**特别注意**

- **隐私优先**：面向本地优先的桌面助手，打点必须匿名、可关闭、有明示告知，否则与产品定位冲突。
- 仅统计 GitHub 下载数量时不需要任何后端；只有做「使用量」时才需要一个轻量接收端。
- 登录系统只在「云同步 / 多设备 / 付费订阅」这类功能出现时才值得做，不为统计单独立项。

---

## 3. 特别注意汇总（公开前逐条打勾）

- [ ] 项目名冻结，改名清单全部落地（bundle id 尤其）
- [ ] 商标 / 域名可用性已确认
- [ ] 图标选定并生成全平台资源
- [ ] UI 美化一轮完成，双平台截图验收通过
- [ ] 全库漏洞扫描跑完，问题清单产出并分级
- [ ] 许可证合规扫描通过（依赖 license 无冲突）
- [ ] `LICENSE` 已补，版权署名就位
- [ ] `allowRedistribution:false` 的 VRM 已从仓库**和历史**移除 / 替换
- [ ] 历史大二进制清理，仓库体积可接受
- [ ] gitleaks 确认历史无密钥
- [ ] 打包形态确定（是否内置 Python 运行时）
- [ ] `.dmg` / `.msi` 双平台实装验证通过
- [ ] README / 发布页 / Release Notes 就位
- [ ] CI 两个 workflow 已启用并跑通
- [ ] 下载量统计（Releases 计数）已接入 / 使用量打点方案已定（匿名、可关）

---

## 4. 现状速查

**已 OK**：`.env` 未入库；运行数据 / `settings.local.json` / `agent_runs` 未入库；git 历史无真实密钥；办公工具与写作链路已闭环（`369 passed`）；4 个提交已推送 `origin/main`。

**待办**：§2.1–§2.6 全部；其中 §2.1、§2.2、§2.5 是**硬阻塞**，§2.3、§2.4 是质量项。
