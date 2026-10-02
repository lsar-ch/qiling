# 办公工具清单（按需安装）— 2026-10-01

## 结论

写作/排版走**插件市场模式**：DeskMate 只提供清单、探测、安装入口与调用，
工具本体由社区项目自行分发，我们不复制它们的代码。位置在「技能扩展 → 办公工具」。

这套模式与「我的智能体」的执行器目录、「技能扩展」的 Skill / MCP 是同一个思路：
清单驱动、按需启用、装完即用。

## 机制

| 环节 | 实现 |
| --- | --- |
| 清单 | `config/office_tools.yaml`（支持 `DESKMATE_OFFICE_TOOLS_CONFIG` 覆盖） |
| 探测 | `app/agents/office_tools.py`：`builtin` 恒真 / `python-module` 看 import / `command` 看 PATH |
| 接口 | `GET /api/office-tools`、`POST /api/office-tools/{name}/install`（挂在 extensions 路由下） |
| 界面 | `apps/web/src/ExtensionsPage.tsx` 的「办公工具」tab |
| 契约 | `OfficeToolInfo`（py 单一事实源 + ts 镜像，受 `test_contracts_sync` 约束） |

`install.kind` 三种取值：

- `builtin`：随 AI 服务内置，无需安装；
- `pip`：点「安装」在本服务虚拟环境执行 `pip install`，装完即可调用；
- `link`：点「去下载」打开官方下载页，用户自行安装后回来点「重新检测」。

## 当前清单

内置排版引擎、docxtpl（Word 模板）、WeasyPrint（CSS 排版 PDF）、Typst（出版级 PDF）、
Pandoc（全格式转换）、Marp（Markdown 转幻灯片）、LibreOffice（转换兜底）。

## 新增一个工具

只改 `config/office_tools.yaml` 追加一条即可，前后端不用动：

```yaml
  - name: my-tool
    label: 我的工具
    detail: 一句话说明它能给哪个格式带来什么提升。
    homepage: https://example.com/download
    license: MIT
    powers: [pdf]
    install:
      kind: pip          # 或 link / builtin
      package: my-package
    detect:
      kind: command      # 或 python-module / builtin
      value: my-tool
```

## 已接进落盘链路（2026-10-01）

`office_writer.write_file` 现在按「装了就用、没装回落」分发，内置渲染器始终是兜底：

| 格式 | 增强引擎 | 触发条件 | 回落 |
| --- | --- | --- | --- |
| PDF | Typst | PATH 里有 `typst` | `_write_pdf`（reportlab，内嵌中文字体） |
| Word | docxtpl | 装了 `docxtpl` **且** 有 `config/office_templates/word.docx` | `_write_docx`（内置 token 排版） |

Typst 无需额外模板：样式预置在 `office_writer._TYPST_PREAMBLE`，与内置渲染器同一套
token（Letter、1in 页边距、#2E74B5 标题、页码页脚），并对 `# * _ [ ]` 等 Typst 标记字符转义。

docxtpl 的模板可由用户提供（公司抬头、页眉页脚、品牌样式）；仓库也自带一份默认模板
`config/office_templates/word.docx`（与内置 token 同源），可直接替换。模板渲染上下文：

```
title           字符串，文档标题（取第一个 H1）
subtitle        字符串，固定「由 DeskMate 生成」
sections[]      heading / level / paragraphs[] / bullets[] / tables[][][]
```

列表连续项之间不插空行，避免 Typst 把它们拆成多个列表。

## 已接：格式转换（2026-10-02）

自然语言入口：说「把 xxx.docx 转成 PDF」「把这个 Excel 导出为 pdf」「把 xxx.docx 转成
markdown」「把 readme.md 转成 docx」就走本机引擎转换，产物落在源文件同目录：

| 目标 | 引擎 | 说明 |
| --- | --- | --- |
| pdf / docx / xlsx / pptx 互转（非 Markdown 源） | LibreOffice | `soffice --headless --convert-to`（独立 profile） |
| md -> docx、任意 -> md | Pandoc | `pandoc <src> -o <dst>` |
| md -> pptx | Marp | 有主题；但 PowerPoint 里是文本框、没有真标题占位符（大纲/朗读读不到） |
| md -> pdf | 内置渲染器 | 避免 Pandoc 转 PDF 依赖 LaTeX |

装了就用、没装则提示到本页安装；目标格式取整句里最后一个格式词（源在前、目标在后，
中英文语序都覆盖）。

## 未做（明确记录）

- WeasyPrint 未接：它需要 pango（macOS 要 brew）+ GTK 运行库，且吃 HTML/CSS，得先补一层
  Markdown -> HTML；PDF 已有内置 reportlab 与 Typst 两条路，边际价值低。要有 CSS 主题排版
  需求时再接。
- 不支持用户自行添加任意 pip 包：清单是白名单，避免把任意包名当命令执行。
- docxtpl 默认模板已入库（2026-10-02）：装了 docxtpl 即生效；用户可整份替换成公司模板。
