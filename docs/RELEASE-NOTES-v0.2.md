# 栖灵 Qiling v0.2.0

> 本地优先、角色化、懂项目上下文的 AI 工作伙伴。
> v0.2 把「工作台」和 Agent 控制面做实，并把桌面角色从单一形象扩展到 6 张可切换角色卡。
>
> 状态：发布文案定稿；本文件在 Release 创建前不再改动内容。

## 这一版有什么

### 可自定义工作台（原「项目」页）

- 导航「项目」改称「工作台」（URL 仍为 `project`，旧书签不受影响）
- 项目概览整合节点进度、运行指标、便签、待办与已配置入口
- 便签 / 待办按项目目录归属，支持新增、编辑、完成、删除；历史无项目归属的数据不会误并入当前项目
- 快捷链接支持新增 / 编辑 / 显隐 / 删除 / 排序，服务端校验 URL 只允许 HTTP(S)
- 工作台内可直接创建项目任务并交给既有任务分流，任务显式写入当前项目
- AgentRun 的状态、进度、产物与错误在任务卡内展示，可运行（默认只读）、取消、批准、拒绝
- 结构化结果：产物 / 检查 / 阻塞 / 下一步四段按需展示，产物汇入项目文件列表并去重

### 统一的 Agent / Skill / MCP 控制面

- 三种执行模式 `inline → mcp → acp`：轻量文案走内置 LLM，只读工具走托管 MCP，代码与多文件长任务交给外部 ACP Agent
- 扩展目录统一展示 Agent / Skill / MCP 的来源、许可证、权限与部署方式
- Skill 绑定任务、MCP profile 白名单（仅 `access: read` 服务器可暴露）、二步串行「实现 → 审查」工作流
- 运行记录持久化 Agent / Skill / MCP / 权限 / 工作目录 / 会话 / 结果；服务重启收口孤儿任务，不自动重放工作流
- 高风险操作仍需显式授权；没有外部 Agent 时轻量任务仍可用

### 6 张角色卡与挂件表现

- 本版冻结 6 张角色：`qiling`（栖灵 3D VRM）、`cat_vrm`（加菲 VRM）、`meshy_female`（绯 VRM）、`pet_cat_walk_test`（蓝猫 GLB 四足）、`default` 与 `persona_2`（程序化 2D）
- 动物挂件新增独立的移动与动作系统：朝向、步态、状态转场、像素级命中判定、贴边吸附
- VRM 挂件动作与状态对齐；A-pose 卡补环境光补偿；「动作检阅」等开发期入口不进入生产包
- 角色卡页面可切换角色，运行时模型与头像资源随包提供

### 模型、语音与启动

- 模型档案按对话 / 多模态 / 语音识别 / 语音合成分类，保存即生效并支持测试连接
- STT / TTS 各自独立选供应商（dashscope / openai_compatible / minimax / breeze）
- 首启向导、启动自检与 API Key 安全录入；语音未配置时健康状态为 `degraded` 而非 `error`，文字对话不受影响
- 桌面安装包构建 workflow 的 artifact 名同步为 `Qiling-0.2.0_*`

## 从 v0.1 升级

- 直接安装新包即可；工作台的便签 / 待办 / 快捷链接数据格式保持兼容，历史全局记录不会自动并入某个项目
- v0.1 的「项目」页 URL 保持可用
- 首次启动仍需填一个 OpenAI 兼容端点与 API Key（语音可选，不填也能用文字对话）

## 下载安装

从 [Releases](../../releases) 下载对应平台安装包（无需自备 Python，运行时已内置）：

| 平台 | 文件 |
| --- | --- |
| Apple 芯片 Mac | `Qiling_*_arm64.dmg` |
| Intel Mac | `Qiling_*_x64.dmg`（macOS 12 Monterey 或更高） |
| Windows | `Qiling_*_x64-setup.exe`（Windows 10 1809 / Windows 11 或更高，自带 WebView2 引导） |

> 当前 Releases 页面公开的最新版本仍为 `v0.1.0`；v0.2 安装包在 Release 创建后于同一页面提供。请勿把 v0.1 的旧 artifact 当作本版使用。

**未签名、未公证**：v0.2 沿用 v0.1 的分发方式，尚未购买 Apple Developer / Windows 代码签名证书，首次打开会有系统安全提示，属正常现象：

- **macOS**：提示「无法验证开发者」或「已损坏」时，把 Qiling 拖进「应用程序」后**右键点应用 → 打开**确认一次；仍不行则执行
  `xattr -dr com.apple.quarantine /Applications/Qiling.app`
- **Windows**：SmartScreen 蓝色警告时点「更多信息 → 仍要运行」

浏览器执行器的 Chromium 内核不随包分发，首次使用时按界面提示下载。

## 角色资产与授权说明（请阅读）

本版 6 张角色卡中，`qiling` 为项目自制可再分发 VRM，`pet_cat_walk_test` 为项目自制 GLB，`default` / `persona_2` 为程序化 2D 形象；**`cat_vrm`（加菲）与 `meshy_female`（绯）由 Meshy AI 生成**。关于后两只角色，需要如实说明：

- 其生成记录与账户付费（Pro）权益有效期的对应关系、源参考素材权属，以及是否曾发布到 Meshy 社区，均**未完成核验**。
- 项目所有者已明确知悉并接受由此产生的风险，允许其随本版发布。**这不等于授权已核验，也不构成授权通过的声明。**
- `meshy_female/model.vrm` 内嵌的 VRM 元数据仍标注 `allowRedistribution: false`，版权信息写有「NOT cleared for redistribution until Meshy Pro ownership is verified」。该声明会随包一起交付，与随公开包分发存在表述上的不一致；本项目未修改这段元数据，也不对这两只模型的可再分发性作出承诺。
- 若您计划再分发或商用这些角色，请自行评估并联系项目作者；本项目整体另受下方 PolyForm Noncommercial 许可证约束。

动作库的来源声明见根目录 [`NOTICE`](../NOTICE) 与下方「已知限制」。

## 已知限制

- 未签名、未公证，安装时会有系统警告（见上）
- macOS arm64 与 Windows v0.2 安装包尚未完成真机实装验收；v0.1 的旧 artifact 不适用于本版
- `data/motion-library/` 的 15 个 `.vrma` 由 Mixamo 参考片逐帧重定向派生，随包分发；它们不是 Mixamo 原始文件，但动作设计与节奏来源于 Mixamo，属衍生作品。来源与条款提示见根目录 `NOTICE`，长期计划用自制 / CC0 动作替换
- 动物 3D 的尾巴 / 耳朵 / 眼皮由运行时程序化驱动，不烘进 VRMA；真四足骨架不能复用人物线动作库
- 便签 / 待办使用 JSON 直接写入，进程在写入中崩溃可能产生截断文件；启动时损坏记录会被跳过
- 隔离环境下未配置 LLM key 时无法验证对话与语音闭环；这不是安装损坏，属可选降级项

## 接下来

- 补齐 macOS arm64 与 Windows v0.2 真机实装验收
- 用自制 / CC0 动作替换 Mixamo 参考片派生的动作库
- **v0.3**：电商运营 / 跨境业务 / 数据处理垂直模板

## License

[PolyForm Noncommercial License 1.0.0](../LICENSE)：非商业用途可自由使用、修改、再分发；商业用途（含企业内部商用）需事先取得作者书面授权，联系方式见 LICENSE。
