# DeskMate V2 P1 任务卡

> 创建时间：2026-09-18
> 前置：V2 P0 已完成（办公任务分流、项目节点数据层、工作/闲聊路由、多任务隔离）
> 方向：工作能力为骨架、项目记忆为连续性、角色陪伴为入口与留存、主动监督为连接点

---

## P1-T1 办公任务执行（外部 Agent 为主 + 本地兜底）

**来源**：V2 P0 已完成识别（WorkKind + infer_work_kind()），但执行完全依赖外部 Agent。

**设计决策**：B 为主（Codex/WorkBuddy 处理复杂办公任务，灵活度高），A 兜底（本地 python-docx/openpyxl/python-pptx 处理高频窄场景，不依赖外部 Agent）。

**本地执行器能力边界**：

| 库 | 擅长（本地处理） | 不擅长（转外部 Agent） |
|---|---|---|
| python-docx | 读取内容摘要、替换文本、插入段落/表格 | 复杂排版、多栏、.doc 旧格式、修订追踪 |
| openpyxl | 读取数据摘要、简单公式、数据清洗、统计 | 超大文件、复杂图表定制、.xls 旧格式 |
| python-pptx | 读取内容、增删幻灯片、文本框编辑 | 动画、过渡效果、SmartArt、复杂模板适配 |

**本地兜底触发条件**：
- 外部 Agent 不可用（未安装、未登录、已禁用）
- 任务为纯读取类（帮我看看这个文件、表格数据汇总）

**实施范围**：
1. services/ai-service/app/agents/local_office.py：LocalOfficeAdapter
2. 注册到 factory.py，default_eligible=False
3. runtime.py 增加降级逻辑
4. 安装依赖：python-docx、openpyxl、python-pptx

**验收标准**：
- 本地能读取 docx/xlsx/pptx 内容摘要
- 外部 Agent 可用时仍走外部 Agent
- 外部 Agent 不可用时自动降级到本地
- check.sh 全绿

**状态**：已完成（2026-09-18）

---

## P1-T2 项目节点可视化与编辑

**来源**：V2 P0 已建数据层，页面是空壳。

**实施范围**：
1. ProjectNodesPage.tsx 完整 CRUD（新建/编辑/删除/状态流转）
2. 流程图渲染（CSS 连线，按 kind 着色）
3. 节点与对话/任务自动关联
4. 项目概览面板

**验收**：手动 CRUD 可用、流程图正确渲染、任务完成自动更新节点

**状态**：已完成（2026-09-18）

**验收记录**：
- 前端：ProjectNodesPage 编辑态回填、保存/删除、任务关联勾选、概览进度条（13/17→14/17 实测同步）
- 后端：runtime 任务收尾按 task_ids 推进节点 completed/blocked，3 个新测试通过；check.sh 238 passed，web build 通过
- 浏览器实测：打开本项目，节点页 17 节点渲染、编辑 T2 状态并保存成功

---

## P1-T3 主动监督连接点

**来源**：V2 方向决策。

**实施范围**：
1. 跨项目后台任务完成/失败主动推送（挂件气泡 + 语音）
2. 项目阻塞/里程碑主动提醒
3. 长时间无进展轻提醒

**验收**：跨对话任务完成 30s 内挂件弹通知、blocker 创建后提醒

**状态**：已完成（2026-09-18）

**验收记录**：
- 跨对话任务完成/失败气泡+语音：Step 9 挂件全局 WS 已覆盖（task.completed/failed → showBrief+playTts），本轮确认无缺口
- 新增事件 project.blocked / project.milestone / task.stale（contracts EventType + KNOWN tuple）；节点失败转 blocked 或 phase/project 节点完成时由 runtime 发布
- 无进展巡检：AgentRunManager.start_stale_sweeper（默认 5min 轮询、15min 阈值、每 run 只提醒一次），main.py lifespan 启动
- 挂件 Widget.tsx 在状态机之前消费三类事件：气泡 6s + TTS
- 测试：failed 任务断言 project.blocked 事件；独立 manager 断言 task.stale 只发一次；check.sh 240 passed，desktop dist 已重建

---

## P1-T4 角色陪伴入口增强

**来源**：V2 方向决策。

**实施范围**：
1. 挂件显示当前项目 + 最近任务状态
2. 角色按 InteractionKind 调整表现（work/casual/project）
3. 项目切换时角色给上下文摘要

**验收**：挂件显示项目名、模式切换表情变化、切换后 3s 弹出摘要

**状态**：已完成（2026-09-19）

**验收记录**：
- 三形象（human/animal/anime）动作库 + 权重随机/冷却/优先级防抖；DOM 冒烟：hover→lean、click→nod、空闲 act-breath 周期轮换
- 分层资产：qianwen_t4 19 层按 z 序叠放、7 role 分组动画（眨眼/说话嘴型/头发/配饰），浏览器实测图层全部加载且动画生效；无 layers.json 自动回退单图
- 项目上下文经 `task.classified` 单通道：显示项目名+状态，切换触发 project 动作 + 3s 摘要；InteractionKind 三档节奏与气泡样式（浏览器实测 project→work 切换通过）
- `./scripts/check.sh` 243 passed；`apps/desktop` build 成功；设计见 `docs/V2-P1-T4-ROLE-COMPANION-PLAN-2026-09-19.md`

---

## P1-T5 项目记忆连续性

**来源**：V2 方向决策。

**实施范围**：
1. 对话/任务/决策自动归档到项目节点
2. 跨对话项目上下文继承
3. 对话中决策语句自动创建 decision 节点

**验收**：新对话绑项目后看到进度摘要、记忆按项目过滤正确

**状态**：已完成（2026-09-18）

**验收记录**：
- 决策语句（含"决定/采用"）在绑定项目的对话中自动创建 decision 节点
- 项目记忆独立文档（L2/proj-<slug>.md），recall 按绑定项目取 surface，未绑定回退全局 project 文档
- 每轮对话上下文注入 project_node_store.summary（进度/进行中/阻塞/下一步/最近决策），casual 模式也带
- 新增测试 test_project_memory_continuity_and_decision_node；check.sh 239 passed

---

## Dogfooding

把 DeskMate 自身项目导入系统，实测项目节点能否正确表达阶段进展。

## 执行顺序

P1-T1 -> P1-T2 -> P1-T5 -> P1-T3 -> P1-T4
