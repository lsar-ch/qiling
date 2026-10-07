# 执行器与办公能力决策材料（2026-10-01）

> 状态：**已定案并落地**（2026-10-01）。用户拍板：执行器主线走 ACP；办公能力按用户要求
> 扩充到 PDF / 图片 / 邮件。实现见 `app/agents/acp_cli.py`、`config/agents.yaml`、
> `app/agents/local_office.py`。所有外部事实于 2026-10-01 经官方源核准，来源见文末。
>
> 落地范围：通用 `adapter: acp-cli` + 3 个执行器转正；页面统一开放 codex/workbuddy/acp-cli
> 配置（含自备 Key 与注册入口）；本地办公执行器新增 PDF 文本提取、图片元数据、.eml 邮件解析，
> 并把 pdf/image/email 三个工作类型打通到分流与降级链路。

## 0. 一句话结论

1. 执行器对接**押注 ACP 一条主线**，MCP 只做工具/数据层，不为每个厂商写专用 adapter。
2. 内置保底办公引擎分三档落地：**零依赖基础档 → 纯 Python 标准档 → 外部引擎增强档**，
   目标覆盖 办公文档 / 数据 / PDF / 图片 / 邮件，不追求万能用例。
3. 端点型（填 OpenAI 兼容 URL+Key）只给「模型能力」，给不了「干活能力」，
   与设置页已有的 LLM 配置重叠，**不放进执行器目录**。

---

## 1. ACP 是什么（已核准）

- **定义**：Agent Client Protocol，标准化「编辑器/IDE（client）」与「编码 agent（agent）」
  之间的通信，本地与远程场景都覆盖。类比 LSP：实现一次协议，双方自由组合。
  由 Zed 与 JetBrains 共建，Apache 许可。
  来源：<https://agentclientprotocol.com/get-started/introduction>、<https://www.jetbrains.com/acp/>
- **传输**：JSON-RPC + UTF-8。稳定可用的是 **stdio**（client 拉起 agent 子进程，逐行消息）；
  **Streamable HTTP 仍是 draft proposal**，自定义 transport 允许但需自行保证生命周期。
  来源：<https://agentclientprotocol.com/protocol/v1/transports>
- **协议面（v1 稳定）**：initialize、authentication、session setup/list/delete/resume、
  prompt turn、content、tool calls、elicitation、file system、cancellation、terminals、
  agent plan、session modes、config options、slash commands、extensibility。
  权限确认（permission）与文件/终端访问**都是协议内建**，由 client 守门。

## 2. 版本与成熟度（已核准）

| 项 | 状态 |
| --- | --- |
| 协议 v1 | Latest 稳定 |
| 协议 v2 | Draft（2026-07-20 发布），含破坏性变更，须做版本协商与特性开关，v1/v2 并行支持 |
| Rust / TypeScript SDK | 1.0.0（2026-06-25） |
| Python / Java / Kotlin SDK | 官方库页列出 |
| Registry | 已 stabilized，机器可读 JSON 可直接拉取 |

来源：<https://agentclientprotocol.com/updates>、
<https://agentclientprotocol.com/announcements/sdk-1-0-releases>、
<https://agentclientprotocol.com/announcements/acp-v2-draft>、<https://agentclientprotocol.com/get-started/registry>

## 3. 生态覆盖（2026-10-01 实测注册表 41 个 agent）

注册表原始数据：`https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json`

与我们直接相关的：

- **Codebuddy Code 2.161.0（Tencent Cloud）** —— 与 WorkBuddy 同源，**官方已在 ACP 注册表内**。
  即：我们现有的 workbuddy adapter 本质就是一个 ACP/stdio 客户端，方向已经对了。
- **Codex 2.1.1**、**Claude Agent 0.84.0**、**Gemini CLI 0.62.0**、**GitHub Copilot 1.0.90**、
  **Kimi CLI 1.52.0**、**Qwen Code 0.24.7**、**MiniMax Code 0.2.7**、**Cursor**、
  **Junie（JetBrains）**、**Devin**、**Factory Droid**、**Google Antigravity**、
  **Goose**、**OpenCode**、**Cline**、**Amp**、**Mistral Vibe**、**Qoder CLI**、**Stakpak**、**Poolside** 等。

**含义**：我们 catalog 里的 7 条，其厂商几乎都已被 ACP 注册表覆盖（reasonix 属长尾，browser 是另一条只读通道）。
新增执行器从「写 adapter」变成「装 CLI + 注册/探测」，维护成本从 O(厂商) 降到 O(1)。

客户端侧同样成规模：Zed、JetBrains AI Assistant、VS Code 系列扩展、neovim 多个插件、
Sublime、Emacs、Qt Creator、Unity、Chrome 扩展，以及 **Obsidian 的 ACP 插件**
（Agent Client / Copilot for Obsidian / Obsidian Harness）—— 后者与 栖灵 定位最接近：
宿主应用 + ACP agent + 本地上下文。
来源：<https://agentclientprotocol.com/get-started/clients>

## 4. 栖灵 现状对照

- `services/ai-service/app/agents/acp.py` 已实现：initialize、session 生命周期、
  streamed updates、permission 请求、cancel、close，以及 16 MiB 单行上限。
- `adapter: codex` → codex-acp；`adapter: workbuddy` → `workbuddy`/`wb` ACP stdio。
- 缺口（相对 v1 全量）：authentication 方法、file system 方法、terminal 方法、
  session list/resume、elicitation、session config options。

**要点**：我们不是「要不要引入 ACP」，而是「已经站在 ACP 上，要不要把它当唯一主线」。

## 5. 风险与限制（必须如实告诉用户）

1. **进程依赖**：stdio 模式 = 本机必须装 agent CLI。ACP 不负责安装、不负责登录。
2. **远程不可靠**：远程 ACP 依赖的 Streamable HTTP 仍是草案，「填个 URL 就能远程跑」现在做不到。
3. **凭据仍是厂商专属**：ACP 标准化握手/授权信号，但 key/授权码还是各家自己的
   （例：WorkBuddy 需付费订阅后申请 API Key）。协议解决不了许可与费用。
4. **v2 破坏性变更**：现在锁 v1，v2 出来做协商；不要默认发 v2。
5. **与 MCP 不是替代关系**：MCP = 工具/数据源；ACP = 谁执行 + 权限边界。二者组合使用。

## 6. 办公能力：当前真实底座（已核准）

- 仓库依赖：`python-docx`、`openpyxl`、`python-pptx`、`pillow`。
- 系统引擎：`soffice/libreoffice`、`pandoc`、`qpdf`、`gs`、`ImageMagick`、`tesseract`、
  `pdftotext` **全部未安装**。
- `agents/local_office.py` 目前**只读**（docx/xlsx/pptx 出摘要），后缀仅 `.docx/.xlsx/.pptx`。

结论：**PDF / 图片处理 / 邮件现在没有任何支撑**，扩宽即意味着新增依赖或外部引擎，需先明确取舍。

## 7. 办公能力分层方案

### 档 A：零新增依赖（stdlib + 已装库）
- 办公文档读写：docx / xlsx / pptx（已有库，读+写）
- 数据处理：`csv`、`json`、`sqlite3`、`zipfile`（OOXML 本质是 zip）
- 邮件收发：`email`（MIME 解析/构造）、`imaplib`（收）、`smtplib`（发）、`poplib` —— 全 stdlib
- 图片基础：`Pillow` 已装 —— 缩放/裁剪/旋转/格式转换/缩略图/水印/EXIF

### 档 B：少量纯 Python 依赖（推荐主投）
- PDF 读：`pypdf`（文本/元数据/合并拆分/加密）；复杂表格 `pdfplumber`
- PDF 生成：`reportlab` 或 `fpdf2`
- PDF→图片/高保真渲染：`PyMuPDF`（fitz），或外部 poppler
- OCR：`pytesseract` + tesseract 二进制（外部）；扫描件/图片转文字走这里
- 更多格式：`icalendar`（.ics）、`odfpy`（.odt/.ods）、`striprtf`（.rtf）、
  `beautifulsoup4`（HTML）、markdown 转换

### 档 C：外部引擎（探测式增强，不预装）
- LibreOffice headless（soffice）：docx/xlsx/pptx/pdf 互转 + 高保真渲染，体积大（数百 MB）
- Pandoc：markdown/html/docx 互转
- Tesseract / ImageMagick：OCR 与图片批处理
- 定位：**探测到才启用**，随产品分发成本过高

## 8. 待用户拍板

- **P1 执行器**：确认 ACP 为唯一对接主线、MCP 为工具层、不做逐厂商 adapter？
- **P2 办公边界**：三档优先级如何排（A 现做 → B 主投 → C 可选）？PDF 读/写/渲染分别要哪一档？
- **P3 邮件**：是否纳入内置引擎（需用户自填 SMTP/IMAP 凭据）？
- **P4 默认执行器**：出厂默认现为 codex；WorkBuddy 需付费订阅，不应做开箱默认。

## 9. 来源

- ACP 官网：<https://agentclientprotocol.com/>（Introduction / Architecture / Agents / Clients / Registry / Transports / Updates）
- ACP 注册表 JSON：<https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json>
- JetBrains × Zed：<https://www.jetbrains.com/acp/>、<https://blog.jetbrains.com/ai/2025/10/jetbrains-zed-open-interoperability-for-ai-coding-agents-in-your-ide/>
- Zed：<https://zed.dev/acp>
- 仓库内对照：`services/ai-service/app/agents/acp.py`、`config/agents.yaml`、`docs/AGENT-CONFIG-ENTRY-PLAN.md`
