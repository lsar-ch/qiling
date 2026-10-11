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
3. **硬阻塞 A — 移除禁止再分发 VRM（高危，需单独授权）**：
   - 当前工作区仍跟踪 `data/persona-assets/{komano,k81,vrm_demo}/model.vrm`（64M / 31M / 38M）。
   - 步骤：先用可再分发资产（`scripts/vrm/build_qiling_vrm.py` 产出的自制 VRM，`allow_redistribution=True`）替换默认引用 → 从工作区移除三个第三方 VRM → 验证应用默认形象可加载。
   - 删除前需用户确认这些模型已另行备份。
4. **硬阻塞 B — 清理 git 历史 + 大二进制（高危，需单独授权）**：
   - `.git` 当前 **956M**；历史含上述三个 VRM（合计 ~140M）及早期 9M 版本。
   - 用 `git filter-repo`（推荐）在公开前清历史；操作不可逆、会改变所有 commit hash，私有阶段做。
   - 清理后核对：历史无禁止 VRM、仓库体积可接受、gitleaks 复跑通过。
   - Mixamo 来源的 `data/motion-library`（71M，VRMA）需确认授权链路（Mixamo 内容使用规则），存疑则一并替换或改为按需下载不入库。
5. **M5 打包 + 真机**：定打包形态（是否内置 Python/ai-service sidecar）；`npm run tauri build` 出 `.dmg` / `.msi`，双平台实装验证；Windows 真机截图补齐。
6. **公开前最终核对**：`.env` / API key / 运行数据确认不入库；CI 两个 workflow 跑通；Releases 文案与截图就位。
7. **M6 发布（需授权推送）**：公开仓库 + 挂 Release；随后启动宣传。

### 首次向导增强 + 启动自检（向导完成后紧接着做）
> 2026-10-10 决定：与首次配置向导合并推进，先把向导做完，再做启动自检。
> 事实源统一复用 `GET /api/health`（已返回整体 `status` + 逐项 `diagnostics`：`label`/`status`/`detail`/`fix_hint`/`fix_action`），不另写一套检查。
- [ ] 向导增强：现有 `SetupWizard` 仅 2 步（LLM 必填 → 语音可选），补「角色选择」步，向导读写与自检共用 `/api/health`。
- [ ] Web 启动自检呈现：启动拉一次 health；`error` → 阻断式卡片（如服务未起 / 对话模型不可用），`degraded` → 可关闭横幅（语音 / 执行器不可用），正常则静默；`fix_action` 渲染为「去设置 / 去智能体」按钮。
- [ ] 挂件侧：`pollHealth` 目前只判服务通断；服务不可用时给「重连 / 打开主界面」，详细诊断不塞进挂件。
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
- [ ] 依赖许可证白名单核对（无 GPL/AGPL 混入，含新增 3 个 MIT）

### B. 安全审计（M3，只读）
- [x] gitleaks：90 commits 扫描，无泄露（2026-10-10）
- [ ] bandit（Python）
- [ ] npm audit（web / desktop）
- [ ] cargo audit（Rust）
- [ ] pip-audit（Python 依赖）
- [ ] 分级问题清单产出，高危项修复

### C. VRM 资产授权（硬阻塞）
- [ ] 自制可再分发 VRM 完成并验证（`allowRedistribution=True`）
- [ ] 移除 komano / k81 / vrm_demo 三个第三方 VRM 并替换默认引用
- [ ] 确认 motion-library（Mixamo 来源 VRMA）授权链路

### D. Git 历史与体积（硬阻塞，高危）
- [x] 备份仓库（`.git` + VRM/VRMA → `~/qiling-backup-20261010`）
- [x] `git filter-repo` 清除历史中的禁分发模型 / 大文件（2026-10-10）
- [x] 核对仓库体积（`.git` 956M → 21M）
- [x] 清理后构建确认功能正常（gitleaks 待 B 阶段统一复跑）
- [x] 清理后完整 check.sh 回归（369 passed + typecheck + vitest，2026-10-10）

> VRM/VRMA 物理文件已拷回原路径并 gitignore，仅本地测试用；自制可再分发资产完成后删除并正式替换。
> filter-repo 已移除 origin，已重新配置（不推送）。

### E. 打包与真机（M5）
- [ ] 定打包形态（是否内置 Python / ai-service sidecar）
- [ ] macOS `.dmg` 构建并实装验证
- [ ] Windows `.msi/.exe` 构建并实装 + 真机截图
- [ ] （可选）macOS 公证 / Windows 签名

### F. 公开前最终核对
- [ ] `.env` / API key / 运行数据 / 缓存不入库（复查 `.gitignore`）
- [ ] CI 两个 workflow 跑通
- [ ] Release Notes / 截图 / 安装步骤就位
- [ ] 全新环境走通安装 → 启动 → 核心闭环（语音 / 对话 / 执行）

### G. 发布与宣传（需授权推送）
- [ ] 公开仓库 + 挂 Release
- [ ] 首波宣传（LINUX DO / V2EX / 即刻 / 少数派 / 知乎 + 社群）
- [ ] 预埋 v0.2 工作台话题
