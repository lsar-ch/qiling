# 写作落地标准（standard_business_brief）— 2026-10-02

> `office_writer.py` 的排版 token 独立成文档，供评审。改 token 时同步改这里的表和
> `tests/test_office_writer.py::TestLayoutStandard` 的断言。

## 1. 一句话

模型只写 Markdown；页面、字体、标题、列表、表格、页眉页脚由 `office_writer` 按
`standard_business_brief` 确定性生成，四个格式共用同一套视觉语言，不依赖模型。

## 2. Token

| 项 | 值 |
| --- | --- |
| 页面 | Letter 纵向 8.5x11in，四边 1in 页边距，页眉/页脚距 0.492in，正文宽 9360 DXA |
| 正文 | Calibri 11pt（中文走东亚洲字体），color `#1A1A1A`，段后 6pt，行距 1.10 |
| 标题 H1 / H2 / H3 | 16pt `#2E74B5`（前 16/后 8）、13pt `#2E74B5`（12/6）、12pt `#1F4D78`（8/4） |
| 文档标题 | 24pt `#1F4D78`，取第一个 H1 |
| 列表 | 真实 Word 编号定义：标记对齐 0.25in / 文本缩进 0.5in / 悬挂 0.25in，段后 8pt |
| 表格 | 固定 DXA 几何（tblW=tblGrid=每格 tcW=9360，tblInd=120），表头填充 `#F2F4F7`，单线边框 `#BFBFBF`，单元格边距 上下 80 / 左右 120 DXA，表头行跨页重复 |
| 页眉页脚 | 安静的运行标题 + 右对齐真实 PAGE 域，多页一致 |

## 3. 各格式落地

| 格式 | 渲染器 | 说明 |
| --- | --- | --- |
| Word | `_write_docx`（内置） | 全套 token；装了 docxtpl 且有模板时走模板 |
| Excel | `_write_xlsx` | 「说明」表 + 每个表格一个「表N」sheet，表头填充/边框/冻结/筛选 |
| PPT | `_write_pptx` | 13.333x7.5in；Title Only 版式，标题进真实占位符；每页页脚页码 |
| PDF | `_write_pdf`（reportlab） | 内嵌中文字体（真字体文件，不用 CID 字体名）；装了 typst 时走 typst |

## 4. 增强引擎与回落

内置渲染器永远兜底，装了增强引擎才启用：

| 格式 | 增强引擎 | 触发条件 |
| --- | --- | --- |
| PDF | Typst | PATH 里有 `typst` |
| Word | docxtpl | 装了 `docxtpl` 且 `config/office_templates/word.docx` 存在 |

Pandoc / Marp / WeasyPrint / LibreOffice 仍是「可装、可探测」，未接进落盘链路。

## 5. 默认 Word 模板

`config/office_templates/word.docx` 已入库，与上面的 token 同源生成。它是 docxtpl
模板，占位符上下文：

- `title`：第一个 H1；`subtitle`：固定「由 DeskMate 生成」
- `sections[]`：`heading` / `level` / `paragraphs[]` / `bullets[]` / `tables[][][]`

用户可用公司模板覆盖同名文件（`DESKMATE_OFFICE_TEMPLATES` 也可指到别处）。

已知上限：一个分节没有表格时，模板会保留一个 0 行表格节点（Word/LibreOffice 中不可见）。

## 6. 验收口径

- **单元断言**：`tests/test_office_writer.py::TestLayoutStandard` 断言页面尺寸、页边距、
  字号、颜色、编号缩进、表格 DXA 几何、表头填充/PAGE 域、PPT 真标题占位、Excel 表头、
  默认模板几何。改 token 必须先改这里。
- **本机渲染验收**：`soffice` + `pdftoppm`（在
  `/Users/lxb/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/`）出图逐页看。
- **中文字形**：macOS 的 `soffice` 缺 fontconfig，docx/pptx 转 PDF 时中文渲染为空白，
  纯文本转 PDF 也空白——**判定为验收环境问题，不是生成端问题**（PDF 走 reportlab/typst，
  已内嵌字体，不受影响）。
- 因此：**docx/pptx 的中文验收以 Word / PowerPoint 真机为准，本机只认 PDF 渲染图**。
  不修本机 fontconfig。
