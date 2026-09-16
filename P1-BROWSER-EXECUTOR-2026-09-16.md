# P1 任务卡：浏览器窄场景执行器（2026-09-16）

> 背景：V1 已收口（`docs/PROJECT-ROADMAP.md` P0 全绿）。按 roadmap P1 顺序推进，
> 先拿稳定的网页工作能力，不建设通用 Computer Use。本卡是 P1 第一项。

## 目标

- 在现有 `AgentAdapter` / `AgentRegistry` 上新增浏览器执行器，**不在前端加浏览器特例**。
- 先实现：打开 URL、搜索、读取页面、提取结果、翻页、滚动。
- 复用 `AgentRun`、进度事件、取消、授权、结果归档（`services/ai-service/app/agents/runtime.py`、`app/api/agent-runs`）。
- 用一个代表性任务做端到端验收，再决定是否增加表单填写。

## 非目标（V1.1 不做）

- 通用 Computer Use / 全桌面控制
- 表单自动填写（先按代表任务验收后再评估）
- 登录、验证码、提交、发送、删除、支付 —— 统一暂停并请求用户确认

## 实施顺序

1. 浏览器执行器适配器（按 `services/ai-service/app/agents/base.py` 的 `AgentAdapter` 形状实现）。
2. 会话生命周期：创建 / 复用 / 失效重建 / 关闭。
3. 动作原语：打开 URL、搜索、读页面（DOM 提取）、翻页、滚动。
4. 安全闸：敏感动作（登录/验证码/提交/发送/删除/支付）转 `request_approval`。
5. 端到端验收：对话页发任务 → 进度/失败原因可见 → 取消后浏览器与任务状态收口 → 结果进 Chat、挂件与项目记忆。

## 验收信号

- 浏览器会话能创建、复用、失效重建和关闭
- 每一步有可展示的进度/失败原因
- 用户取消后浏览器和任务状态正确收口
- 任务结果可进入 Chat、挂件反馈和项目记忆

## 待决策项（开工前需用户拍板）

1. ✅ 浏览器技术栈：**Playwright**（已装包 + chromium，2026-09-16）
2. ✅ 代表验收任务：**搜索一个主题并返回前几条摘要**

## 进度（2026-09-16）

- ✅ `app/agents/browser.py`：Playwright headless 适配器（detect / run / cancel）
- ✅ 注册进 `config/agents.yaml`（adapter: browser）+ `factory.py`；`/api/agents` 探测 `ready`
- ✅ 只读安全闸：登录/验证码/提交/发送/删除/支付/下载等 prompt 直接拒绝，不启动浏览器
- ✅ 代表任务端到端：搜索「石家庄中考招生政策」返回前 5 条标题+URL+摘要；抽取用 `textContent`（Bing 对 headless 隐藏文本，`innerText` 为空）
- ✅ 依赖声明 `services/ai-service/requirements.txt` += playwright
- ✅ 测试：新增 `test_browser.py`（解析+敏感词拒绝，不依赖网络）；`./scripts/check.sh` 171 passed + typecheck 全绿
- ⏳ 待下一步：对话页自动选择 browser 执行器（当前 auto_run 走 `default_executor=workbuddy`），再补翻页/读页面原语

## 基线

- V1 已收口：Windows 真机回归 18/18，macOS 复验通过（`docs/WINDOWS-MIGRATION-2026-09.md`）
- 分流规则已真机验证（2026-09-16，8 例全符合，零残留）
- 测试基线：`./scripts/check.sh` 169 passed + Web/Desktop typecheck 全绿
- 当前提交：`834b50c`

## 完成判定

- 验收信号 4 项全过 + 代表任务端到端通过 + `./scripts/check.sh` 全绿 → P1 第一项完成，进入「轻量主动性与对话模式」或表单填写评估。
