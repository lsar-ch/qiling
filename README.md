# 栖灵 Qiling — 桌面 AI 助理

> 本地优先、角色化、懂项目上下文的 AI 工作伙伴：2D 角色挂件常驻桌面、语音交互、项目记忆，复杂任务集成现有 Agent 执行。
> 支持**中英文双语**（侧栏 `English / 中文` 一键切换）；当前发布与版本计划见 `docs/RELEASE-PLAN-2026-10-10.md`。

## 设计理念

- **角色化工作伙伴 > 普通桌宠** — 有性格，但必须能帮助用户完成工作
- **集成 > 自研** — 调度 Codex、MCP 和现有工具，不自研通用 Computer Use
- **项目连续性优先** — 记住项目、偏好和技术决策
- **状态反馈优先** — 挂件是核心交互入口，程序状态驱动动画
- **克制 > 抢控制权** — 主动感知但不骚扰，高风险操作必须授权
- **隐私优先** — 本地优先，语音/记忆数据默认不出设备
- **渐进增强** — 2D 挂件起步，再扩展记忆、Agent 集成和角色表现

## 架构（Step 1 冻结决策）

```text
apps/desktop      Tauri 2 桌面运行时：拉起 AI 服务、托盘/挂件壳、打开 Tauri 主界面
apps/web          React + Vite 主界面（中文默认），由 ai-service 托管并由 Tauri 主窗口加载
services/ai-service  Python FastAPI 本地服务：health/事件总线/文字对话/语音/记忆/任务与 Agent 执行
packages/contracts 共享契约：pydantic 单一事实源 + TS 镜像 + 一致性测试
docs/             需求、技术方案、V1 接口与实施顺序
```

- 端口规范：ai-service `8736`（托管主界面 + `/api`）、web dev `5173`、desktop dev `1420`。
- 现有 `src/`（PyQt6 早期原型）只作参考，不参与新架构运行。

## 快速开始

```bash
# 1. 初始化（Python .venv + 依赖 + 前端构建）
./scripts/setup.sh

# 2. 启动本地 AI 服务（浏览器打开 http://127.0.0.1:8736/）
./scripts/dev.sh service

# 3.（可选）桌面运行时
cd apps/desktop && npm run tauri dev

# 检查（契约一致性 + 接口测试 + 前端类型）
./scripts/check.sh
```

## 目录速览

```text
apps/desktop/src-tauri/   Rust 运行时（服务进程管理、打开 Tauri 主窗口）
services/ai-service/app/  FastAPI 路由与事件总线
packages/contracts/py/    pydantic 契约（真相源）
packages/contracts/ts/    TS 类型镜像
docs/                     产品与技术文档
```

## V1 路线（详见 docs/V1-IMPLEMENTATION-PLAN.md）

Step 1 接口与开发基线 → Step 2 挂件与主界面 → Step 3 文字对话 → Step 4 语音闭环 → Step 4.5 设置与角色配置 → Step 5 项目记忆 → Step 6 任务分流 → Step 7 Codex 接入 → Step 8 回归与降级 → Step 9 视觉与体验打磨

## License

本项目依据 **PolyForm Noncommercial License 1.0.0** 授权，完整文本见 [`LICENSE`](LICENSE)。

- 任何人可在**非商业目的**下使用、复制、修改与再分发；
- **商业用途（含企业内部商用）不在授权范围内**，须事先取得作者书面商业授权；
- 商业授权请在本仓库提交 issue 并标注「商业授权」。

后续路线：`v0.2` 可自定义工作台（自行新增条目/模块）、`v0.3` 电商 / 跨境 / 数据处理垂直模板。
