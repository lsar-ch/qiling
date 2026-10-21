# Mixamo 动作库授权链路核对（2026-10-11）

> 对应发布计划硬阻塞：确认 `data/motion-library` 授权链路。
> 当前现状：**`female` 15 条、2.3M；已随仓库和安装包分发，并附 `NOTICE`。**
> 这些文件由 Mixamo 参考片逐帧重定向并修正后生成，不是原始文件；完整声明见下方行动项。

## 事实

- 来源：`idle` / `hover` / `speaking` / `success` / `project` 等候选片段源自 Mixamo（Adobe），
  经 Blender 重定向到 VRM 1.0 标准 52 骨后导出为 `.vrma`（见 `data/motion-library/README.md`）。
- 当前处置（2026-10-10 已完成）：
  - `.gitignore` 不再排除 `data/motion-library/`，15 条 `.vrma` 随仓库提交；
  - 2026-10-21 清理前的历史不含这些动作文件，本次提交新增 15 条并保留 `NOTICE`；
  - 本地与干净 checkout 使用同一份随仓库分发的动作库。

## Mixamo 条款要点（2026-10-11 核对）

- Mixamo 角色与动画可**免版税商用**，无需额外授权费（Adobe 社区官方 FAQ 与多个独立解读一致）。
- 唯一红线：**不得将原始角色/动画文件作为独立资产再分发**（"can't distribute the raw character and animation files"），
  不得转售、不得批量下载用于 ML 训练。
- 嵌入到具体项目（游戏/应用/影片）中使用是允许的；关键判据是资产能否被直接提取。

## 对栖灵的判定

1. **公开 GitHub 仓库（v0.1）**：15 条修正后的派生动作随仓库分发；根目录 `NOTICE` 明确声明其为 Mixamo 参考片逐帧重定向派生、非原始文件。
2. **公开 Release 安装包（M5）**：2026-10-21 已由用户决策改为方案 B，VRMA 随 `.dmg/.msi` 分发。
   我方口径是动作文件已重定向到自有 VRM 骨架并嵌入应用，不作为独立动画库分发；
   `NOTICE` 明示其为 Mixamo 参考片派生作品并附使用条款链接。该问题仍不是 Adobe 明文许可，
   属于已知的授权灰区，后续仍应用可再分发动作替换。
3. 自制可再分发动作（与硬阻塞 A 的自制 VRM 同一 Blender 工序，`scripts/vrm/normalize_vrma.py`）
   可彻底消除该问题：后续 Blender 研究产出的自制 VRMA 入库后，Mixamo 片段连本地测试都可退役。

## 行动项

- [x] 15 条修正后的派生 VRMA 随本次提交入库，根目录 `NOTICE` 声明来源与非原始文件属性
- [x] ~~M5 打包时按方案 A 处理：打包流程排除 `data/motion-library/`~~
  **→ 2026-10-21 决策变更为方案 B（随包分发）**：不含动作库时安装后只剩程序化待机，
  用户体验不完整；改为打包动作库 + 源码/安装包内声明「动作由 Mixamo 参考片派生」
  （见根目录 `NOTICE` 与 `scripts/package/stage_home.py` 注释）。
  需要无动作资产的干净包时用 `QILING_STAGE_NO_MOTION_LIB=1` 显式排除。
  动作库现状：15 条（Mixamo 参考片逐帧重定向到自有 VRM 骨架的衍生品，52 骨规范）。
- [ ] （可选，长期）用 CMU Motion Capture Database（可再分发许可）重定向替换 Mixamo 派生动作，
  彻底消除来源依赖。现状：`scripts/vrm/cmu_retarget.py` 通路可跑通，但存在
  首帧跳变、躯干旋转叠加变形、hips 无位移三个待修问题（2026-10-21 实测 141_16 / 111_25）。
