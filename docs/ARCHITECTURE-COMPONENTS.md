# DeskMate 组件架构说明

## 1. 浏览器主界面

主界面继续走浏览器展示，不把第一版主界面做成原生桌面壳。

参考方向：

- Qwen-Audio-Agent 的 WebUI / browser interface 风格
- DeepTutor 的单工作区、多 surface 设计

建议结构：

- Home
- Chat
- Memory
- Knowledge Base
- My Agents
- Settings

原则：

- 页面本身负责展示与交互
- 桌面运行时只负责挂件、唤起和系统能力
- 本地服务通过端口和会话令牌与页面通信

## 2. 挂件状态机

挂件状态不要让模型自由发挥，而要由程序状态驱动。

推荐状态：

- idle
- listening
- thinking
- speaking
- executing
- awaiting_approval
- completed
- interrupted

状态来源：

- 音频输入
- LLM 生成状态
- Agent 任务状态
- 权限请求
- 用户打断
- 任务结果

动画映射原则：

- 一个状态对应一组固定动画
- 状态切换由事件驱动
- 动画只是状态可视化，不是决策源

这类设计和 Qwen-Audio-Agent 的实时语音前台一致，也和 DeepTutor 的“共享运行上下文”一致。

## 3. 记忆方案

记忆参考 DeepTutor 的三层结构：

- L1：事件 trace / 原始记录
- L2：每个 surface 的整理事实
- L3：跨 surface 的综合画像与摘要

建议 DeskMate 的记忆也做成可审计、可编辑、可回溯，而不是纯黑盒向量库。

建议存储内容：

- 用户偏好
- 角色偏好
- 项目进度
- 长期事实
- 最近任务
- 重要决策

## 4. 外部智能体接入

后台接入参考 Qwen-Audio-Agent 的方式：

- 统一前台
- 统一 Gateway / Router
- 统一 ACP / adapter 接口
- 统一结果回流

建议接入对象：

- Codex
- Claude Code
- DeepSeek Harness
- 云端任务平台

规则：

- 不把某个后端写死在前端
- 不把具体 Agent 当作产品主架构
- 不同后端都经过同一个任务路由层

## 5. 方向约束

这四块都要服务同一个产品目标：

- 桌面挂件是入口
- 浏览器主界面是工作台
- 语音是主要交互方式
- 记忆是持续个性化基础
- 外部智能体是复杂任务执行层

