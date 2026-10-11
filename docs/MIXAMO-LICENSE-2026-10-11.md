# Mixamo 动作库授权链路核对（2026-10-11）

> 对应发布计划硬阻塞：确认 `data/motion-library`（71M VRMA，male/female 各 20 条）授权链路。
> 结论：**VRMA 不入库、不随仓库分发即可，无需替换动作；公开仓库无授权风险。**

## 事实

- 来源：`idle_yawn` / `hover` / `idle` / `speak_alt` / `success_happy` 等候选片段源自 Mixamo（Adobe），
  经 Blender 重定向到 VRM 1.0 标准 52 骨后导出为 `.vrma`（见 `data/motion-library/README.md`）。
- 当前处置（2026-10-10 已完成）：
  - `.gitignore` 已忽略 `data/motion-library/`，`git ls-files` 跟踪数 = **0**；
  - `git filter-repo` 清历史后，全历史 `git rev-list --objects | rg '\.vrma$'` 无任何命中；
  - 物理文件仅保留在本机用于测试。

## Mixamo 条款要点（2026-10-11 核对）

- Mixamo 角色与动画可**免版税商用**，无需额外授权费（Adobe 社区官方 FAQ 与多个独立解读一致）。
- 唯一红线：**不得将原始角色/动画文件作为独立资产再分发**（"can't distribute the raw character and animation files"），
  不得转售、不得批量下载用于 ML 训练。
- 嵌入到具体项目（游戏/应用/影片）中使用是允许的；关键判据是资产能否被直接提取。

## 对栖灵的判定

1. **公开 GitHub 仓库（v0.1）**：VRMA 既不在当前树也不在历史中，下载源码的人拿不到 Mixamo 派生文件 → 无再分发行为，无风险。
2. **公开 Release 安装包（M5）**：这是真正的决策点，二选一：
   - **方案 A（推荐，零法律不确定性）**：安装包不打 VRMA，动作改为「首次需要时按需下载」或由自制动作替换；
   - 方案 B：把 VRMA 打进 `.dmg/.msi`。我方观点是 VRMA 已做骨骼重定向/格式转换、且嵌入应用不可直接提取，
     属"incorporated into a larger project"，但 Mixamo 对"转换格式后是否仍算 raw files"无明文许可，
     属于灰色地带——非商业发行（PolyForm Noncommercial）下风险更低，但不建议在没问 Adobe 的前提下赌。
3. 自制可再分发动作（与硬阻塞 A 的自制 VRM 同一 Blender 工序，`scripts/vrm/normalize_vrma.py`）
   可彻底消除该问题：后续 Blender 研究产出的自制 VRMA 入库后，Mixamo 片段连本地测试都可退役。

## 行动项

- [x] 确认当前仓库与历史无 VRMA（0 tracked / 0 history hits）
- [ ] M5 打包时按方案 A 处理：打包流程排除 `data/motion-library/`，或在此之前用自制 VRMA 替换
- [ ] （可选，长期）自制全套 11 trigger × 2 性别的可再分发 VRMA，彻底去掉 Mixamo 依赖
