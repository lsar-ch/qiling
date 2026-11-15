# Meshy 生成资产授权凭证（P0-2 归档 / 2026-11-15 风险接受）

- **建档日期**：2026-11-14
- **关联角色**：`cat_vrm`（加菲，Russian Blue cat，VRM 3.34 MB）、`meshy_female`（绯，stylized anime，VRM 21.38 MB）
- **决策**：两只猫已随 v0.2 **本地候选包**打包（用户 2026-11-14 授权）；**2026-11-15 用户明确接受剩余授权风险**，允许随 v0.2 公开发布包分发，P0-2 由「阻断」转为「风险接受」，不再是发布前置条件。**授权事实仍未核验，不得据此记录为授权通过。**
- **状态**：🟡 已归档 Workspace、Pro 状态和 ToS 截图；🔴 生成记录与 Pro 有效期映射、源素材权属及社区发布状态未核验（事实缺口保留）。用户于 2026-11-14 指示跳过历史材料追查；2026-11-15 用户接受剩余风险，并在 T-07 追加「风险接受例外」。详见 §5。

---

## 1. 授权条款原文（官方，已抓取核验）

来源：`meshy.ai/terms-of-use`（中文版 `meshy.ai/zh/terms-of-use`，2026-09-19 版；英文原版同页）。

### 1.1 付费档拥有输出（核心条款；适用前提待核验）

> "Customers on a paid Meshy plan, and to the extent possible under applicable law, such customers on a paid Meshy plan own their Customer Output."

中文版页面同段可见：`…such customers on a paid Meshy plan own their Custo… Content.`

含义：**若该次生成确在付费档有效期内，且源素材不侵犯第三方版权**，则用户拥有其生成输出，可自由复制、分发、销售，无需给 Meshy 署名（仅不可去除模型内的 AI 生成标识）。本节仅描述条款内容，**不表示两只猫已满足其适用前提**（见第 2、3 节）。

Help Center 补充（`help.meshy.ai`，《Can I use Meshy assets commercially》）：

> "if you are a paid customer, you own the assets created through our platform, provided that you have used materials that do not violate the copyrights of others."

### 1.2 免费档受限（为何免费档不满足铁律；档位适用期仍待核验）

> "Customers using Meshy's Services under the free plan … Meshy owns all right, title, and interest … makes such rights available to free plan customers under the Creative Commons Attribution 4.0 International License (CC BY 4.0) … credit to Meshy."

即免费档仅 CC BY 4.0 使用权、必须署名 → **不满足**「付费完全所有权」铁律。Pro 面板截图仅能证明 2026-11-14 截图时账户显示 Pro，**不能证明 2026-10-28 生成素材时已处于付费档**，因此该条是否适用于这两只猫尚未确定。

### 1.3 社区发布会转 CC0（前提条件）

> "3.3 Community License … if You upload … any content on the Meshy Community page … Customer Output … is licensed under the Creative Commons Zero v1.0 Universal Public Domain Dedication (CC0)."

即：模型**不得发布到 Meshy 社区**，否则变 CC0 公共领域、失去专属所有权。「未发布社区」是保持专属所有权的前提，**该状态尚未核验，不能记为满足**（见第 3 节）。

---

## 2. 账户订阅状态（付费凭证）

- 证据：`docs/evidence/meshy_female-authorization-2026-11-14/02-Meshy-Pro专业版订阅.png`，账号面板显示 **Pro 专业版**、通用积分 976；截图时间为 2026-11-14，但未显示订阅起止日期。
- 结论：可确认截图时账户显示 Pro；目前不能据此确认 2026-10-28 生成素材时已处于付费档。

> 事实缺口：订阅确认邮件 / 账单（含订单号、周期、金额）截图，以确认生成日期落在 Pro 权益有效期内。2026-11-14 用户指示不再追查未留存的历史材料；该缺口保留，由 §5 的风险接受决策覆盖。

---

## 3. 资产溯源（🔴 事实缺口保留 — 已由用户接受风险，不再作为发布前置条件）

已找到 `meshy_female` 的本地 Meshy 导出素材包：WorkBuddy 工作目录 `2026-11-13-12-51-43/model_review/zip/Meshy_AI_Stylized_Anime_Female_biped/`，内含 Character FBX、贴图和 Walking FBX；文件系统记录时间为 2026-10-28。该目录名与 WorkBuddy 构建记录中的 `meshy_female_pipeline_ready.glb`、后续 `model.vrm` 处理链相吻合，但**本地目录名和文件时间不是 Meshy 生成历史/资产 ID 的权威证明**。

用户提供的 Workspace 截图已归档为 `docs/evidence/meshy_female-authorization-2026-11-14/01-Meshy-Workspace资产列表.jpg`，但截图没有清晰显示该模型对应的生成记录/ID。若日后需要补证，应在 `meshy.ai/zh/workspace` 生成历史中定位：

- `cat_vrm`（加菲）：对应生成项（如 "Rig-ready realistic Russian Blue cat" 之类）。
- `meshy_female`（绯）：对应生成项（如 "Animation Ready Stylized Anime" 之类）。

**未核验的三项事实（永久留档，不再追查、也不再作为发布阻断）**：

1. 上述两只猫的生成**源参考图 / 提示词均为用户自有或已授权素材，不侵犯任何第三方版权**（第 1.1 条 "provided that" 前提）。
2. 两只猫**从未发布到 Meshy 社区**（第 1.3 条 CC0 前提）。
3. `meshy_female` 对应生成记录的日期/ID，以及账户 Pro 权益在该生成日期有效的证据（账单/订阅周期或 Workspace 生成详情）。

---

## 4. 结论

- v0.2 候选包已包含角色资产；当前证据不足以确认两只 Meshy 资产均满足付费完全所有权要求，**授权事实未核验**。打包存在不代表授权已通过。
- **发布处置（2026-11-15 用户决策）**：用户明确接受剩余授权风险，允许这两只资产随 v0.2 公开发布；P0-2 由「阻断」转为「风险接受」，不再是公开 Release 的前置条件。T-07 已追加例外记录（见 `栖灵Desktop/01-方向与决策/T-07 资产授权红线.md` §2026-11-15 例外决策）。
- 该决策**不是**授权核验通过，**不改写** T-07「内置资产只接受自制 / CC0 / 付费完全所有权」的一般红线；后续新增资产仍须先过授权闸门。
- 关联改动：提交 `baef64e`（gitignore 例外 + `license_status: owner_authorized` + ASSET-NOTICE 更新）。其中 `license_status: owner_authorized` 是当时的乐观口径，**现已不视为授权通过，不得作为本次公开发布的依据**；历史不改，发布文案不得引用该字段作为授权结论。
- **残留技术性矛盾（风险接受覆盖范围内）**：`meshy_female/model.vrm` 的 VRM meta 仍为收紧值 `allowRedistribution=false`、`creditNotation=required`、`commercialUsage=personalProfit`，与「随公开包分发」在元数据层面不一致。用户接受风险不等于元数据已放宽；对外不得声称该模型允许再分发。若日后补齐证据，再复核并放宽 meta → 重跑 `verify_vrm.py` 与 `check_vrm.mjs`。

---

## 5. 2026-11-15 风险接受决策记录

| 项 | 内容 |
| --- | --- |
| 决策人 / 日期 | 用户（项目所有者）/ 2026-11-15 |
| 决策 | 「接受风险」——允许 `cat_vrm`、`meshy_female` 随 v0.2 公开发布包分发，P0-2 不再阻断发布 |
| 性质 | **风险接受（risk acceptance）**，不是授权核验通过、不是 T-07 红线放宽 |
| 适用范围 | **仅限**上述两只 v0.2 已冻结资产；后续新增资产不适用 |
| 已知缺口 | 生成记录/资产 ID 与 Pro 权益期映射、源素材权属、未发布 Community 三项；VRM meta 与分发行为不一致 |
| 边界 | 不得写成「授权已核验 / 授权通过 / 满足铁律」；T-07 一般红线与动作闸门三步不变 |
| 回滚条件 | 收到 Meshy 或第三方权利主张，或补证发现生成时不满足付费档前提 → 立即移除/替换资产并回滚例外 |
| 决策落点 | Obsidian `栖灵Desktop/01-方向与决策/T-07 资产授权红线.md`；本文；`data/persona-assets/meshy_female/ASSET-NOTICE.txt`；v0.2 交接 §4 P0-2 |

> 证据截图目录 `docs/evidence/meshy_female-authorization-2026-11-14/` 为调试过程资料，按 2026-11-15 用户决定不入库、不进包，本地保留至完整资料包整理时统一清理。
