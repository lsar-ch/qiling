# 形象资产自研最终方案（2026-10-12 定稿）

> 状态：**最终方案**。此前所有角色形象生成路径以本文裁定为准；旧文档仅保留历史与实现细节。
> 依据：两条自动生成路线均已有真实产物并经三道校验 + 人工观感复核，结论不是推测。
> 关联：`docs/RELEASE-PLAN-2026-10-10.md` §C（授权硬阻塞）、`docs/VRM-EXPORT-SPEC.md`、`docs/WIDGET-VRM-3D-PLAN.md`

## 1. 一句话结论

**官方默认人形形象用 VRoid Studio 人工原创**（免费、自带规范骨骼/15 表情/spring、导出即合规 VRM 1.0、授权可自定可再分发）；AI 图生3D 与程序化脚本生成只产出过"过闸门但不能看"的模型，放弃作为官方形象来源；动物维持 2D only。项目自研的资产管线（导入闸门、规范化、动作库）全部保留，它们解决"资产如何被消费"，与"形象从哪来"无关。

## 2. 最终方案（按角色类型与使用者）

### 2.1 官方默认角色（发布交付物）

- 生产方式：**VRoid Studio 人工捏制原创角色**（不用任何现成模型、不用 AI 生成网格）。
- 导出：VRM 1.0，按 `docs/VRM-EXPORT-SPEC.md` 设置授权四项 false + `allowRedistribution=True`。
- 入闸：`scripts/vrm/verify_vrm.py`（静态）→ `services/ai-service/app/core/vrm_validator.py`（导入闸门）→ `apps/desktop/scripts/check_vrm.mjs`（three-vrm 运行时），三道全过。
- 人工观感验收（闸门管不到，必须单独过）：挂件 150px 尺寸辨识度、五官/手指完整、头发衣物 spring 自然、T-pose 缩略图无破碎。
- 接线：建 `config/personas/qiling.yaml` → 资产落 `data/persona-assets/qiling/` → 切为默认 → 移除 k81 / komano / vrm_demo 的默认引用（RELEASE-PLAN §C 闭环）。
- 工时预期：简洁原创角色约 0.5–1 天。

### 2.2 用户自定义角色（产品功能，已上线 / 保留）

| 输入 | 链路 | driver | 状态 |
| --- | --- | --- | --- |
| 一张立绘图 | `PUT /api/personas/{id}/avatar` → `normalize_avatar_image` | `procedural_2d` | 已上线，主入口 |
| 分层 PSD（器官级动效） | `scripts/import_psd_layers.py` → `layers.json`，人工放置（无 zip 接口） | `procedural_2d` | 已落地，离线生产 |
| 自备 VRM（VRoid 自捏 / Booth 购买等） | 角色页 3D zip → `POST /api/personas/{id}/import3d` → 闸门 | `vrm_3d` | 已上线，授权责任归用户 |
| 照片 → AI 3D | Blender MCP（混元/Hyper3D/Tripo）→ GLB → `scripts/vrm/build_vrm_from_glb.py` | `vrm_3d` | **玩具级试验功能，不承诺质量，不用于官方形象** |

### 2.3 动物（蓝猫线）

- `motion_family: animal` + `procedural_2d`，猫狗通用 2D 动作表。
- VRM 以人形骨骼为硬前提，动物不做 3D。

### 2.4 动作（.vrma，与形象生产解动）

- 共享库 `data/motion-library/{male,female}`（Mixamo 转换）：可商用、禁止原始资产再分发 → 不入库不打包，按需下载或用自制动作替换。
- 微调/收口：`roundtrip_vrma.py` → `normalize_vrma.py`（52 骨）→ `check_vrma.mjs`；定制动作 Blender MCP K 帧 + 人工复查穿模/权重。
- 该链路 2026-09 起已与 XiaoMate / Mate Engine / open-annie 多方独立收敛，不动。

## 3. 历史路径裁定总表（以后检索以此为准）

| # | 路径 | 裁定 | 依据 / 实测 |
| --- | --- | --- | --- |
| 1 | 提示词→文生图→拆层（2D） | ❌ 走不通 | 2026-09-11 实测：成品无 alpha、近白底噪点、眼嘴 100-200px、部件错位；文生图不产出结构信息。见 `docs/CHARACTER-ASSET-GENERATION.md` §2 |
| 2 | 参考图→VL 抽特征→参数化 SVG 生成器 | 🟡 能用但未达交付 | POC 跑通（2026-09-11），仅模板化小人，未产品化；2D 后续备选，不承接官方形象 |
| 3 | See-through 拆 PSD → layers.json（2D 分层） | ✅ 采用（2D 用户线） | 已落地，器官级局部动效（眨眼/口型/发飘）；上限就是局部动，非全身 |
| 4 | EchoMimicV3 音频驱动离线视频 | 🟡 备选未实施 | 写实人像甜区、需租 GPU、跨片段身份漂移、≤768p；仅写实角色主界面档，与挂件无关 |
| 5 | `scripts/vrm/build_qiling_vrm.py` 无头脚本程序化原创 VRM | 🔴 质量不达标，放弃作为官方形象 | 2026-10-12 全新重跑，三道校验全 PASS（21784 面/15 表情/5 spring），但成品为 Q 版积木感：阶梯拼合脸、团状无指手、纯色块、5 spring 近乎无物理，距 k81/komano 等真实资产差一个量级。脚本保留为 bpy 自动化参考 |
| 6 | AI 图生3D（混元3D 等）→ GLB → `build_vrm_from_glb.py` → VRM | 🔴 质量不达标，仅留作用户试验 | 产物 `build/vrm/qiling_glb/model.vrm` 过三道闸（36200 面），但 40 万面减面后碎玻璃低模、0 spring、18 个表情靠五官坐标聚类硬造；且 Tripo/混元等生成物再分发授权需逐个确认。可借鉴工程点：Mixamo autorig、`path_mode='COPY', embed_textures=True` 防丢贴图（见 XiaoMate 调研 P0） |
| 7 | **VRoid Studio 人工原创 → VRM 1.0** | ✅ **最终采用（官方形象）** | 免费、自带规范骨骼+15 表情+spring，导出即过闸；k81/komano/vrm_demo 同生态成品证明质量上限；授权自定解决再分发硬阻塞；Mate Engine/N.E.K.O./XiaoMate 生态同路线 |
| 8 | Booth.pm / VRoid Hub 下载现成模型 | 🟡 用户线可用，官方线不可用 | 质量高、下载即用；许可逐个筛，多数 `Redistribution_Prohibited`，重蹈当前三模型授权覆辙 |
| 9 | 外包定制（VRoid/美术，¥500–3000） | 🟡 兜底 | 质量高、零工时；前提是合同写明买断 + 可再分发；VRoid 自跑不通时再用 |
| 10 | 照片→VRM 转换服务（Neural4D / VTubeMe 类） | ⛔ 不采用 | 调研仅提名、标注还原度有限，与 #6 同属 AI 转模，拓扑/表情问题相同 |
| 11 | Live2D 路线 | ❌ 已决策不做 | Cubism 发布授权门槛 + 美术绑骨成本 + Intel Mac 无独显（2026-09-26 决策） |
| 12 | 动物 / 异形 3D 化 | ❌ 不做 | VRM 人形骨骼硬前提；动物留 2D |
| 13 | 客户端内嵌重模型（本地 See-through / 3D 生成） | ❌ 走不通 | Intel Mac + UHD630 无显存，违反零新增运行时依赖原则；所有生成都在离线侧 |

> 标签含义：✅ 采用 ｜ 🟡 能用但有明确边界/不承接交付 ｜ 🔴 技术跑通但资产质量差 ｜ ⛔ 评估后不采用 ｜ ❌ 已验证走不通

## 4. 关键认知（避免重复试错）

1. **闸门只保证"能加载不崩"，不保证好看。** 两个自动生成产物全部过闸但都不可交付；验收必须加人工观感项。
2. **VRM 的质量护城河是人工内容**：权重、15 个 blendshape、spring、toon 美学，AI 网格给不了；这也是 VRoid 存在的原因。
3. **自研代码的价值在消费侧，不在生产侧**：导入闸门、契约、动作库、motion-lab 全部继续用；被否的只是"用代码/AI 凭空造形象"。
4. **授权与质量是两件事**：#5 授权最干净但质量差，#8 质量好但授权多数不干净；VRoid 原创是唯一两者同时满足的零成本路径。

## 5. 立即可执行的落地步骤

1. VRoid Studio 捏制原创角色（简洁发型/服装，控制 spring 链 ≤30 关节预算）。
2. 导出 VRM 1.0，授权四项全 false、允许再分发/修改。
3. 三道校验全绿 + 人工观感验收。
4. `config/personas/qiling.yaml` + `data/persona-assets/qiling/`（model.vrm + avatar.png），切为系统默认。
5. 移除 k81 / komano / vrm_demo 默认引用与工作区文件，关闭 RELEASE-PLAN §C。
6. `#/motion-lab` 挂共享动作库，实机验收 11 个 trigger。

## 6. 本文与旧文档的关系

| 旧文档 | 现效力 |
| --- | --- |
| `docs/CHARACTER-ASSET-GENERATION.md` | 2D 结论（单图/分层/SVG 备选）仍有效；3D 形象相关表述以本文为准 |
| `docs/WIDGET-ASSET-PLAN.md` | V1 2D 形态历史记录，仍有效 |
| `docs/WIDGET-VRM-3D-PLAN.md` | **渲染/驱动**方案，仍有效（与形象来源无关） |
| `docs/VRM-EXPORT-SPEC.md` / `docs/VRM-ASSET-NOTES.md` / `docs/BLENDER-VRMA-WORKFLOW.md` | 导出规范与踩坑手册，继续生效 |
| `docs/MIXAMO-LICENSE-2026-10-11.md` | 动作授权结论，继续生效 |
| 桌面《角色资产生成与商业化方案备忘》docx（2026-09-19/10-08 备份） | 历史备忘：2D 分层商业化与 3D 动作 K 帧仍参考；形象生成以本文为准 |
| `scripts/vrm/build_qiling_vrm.py` / `build_vrm_from_glb.py` | 保留：前者为 bpy 程序化参考，后者承接用户自备 GLB 的转换试验；均非官方形象来源 |
