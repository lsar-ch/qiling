# 办公模板目录

放这里的东西会被 `office_writer` 自动使用（前提是装了对应引擎）：

- `word.docx` —— docxtpl 用的 Word 模板（装了 `docxtpl` 时生效）。
  仓库自带一份默认模板，与 `standard_business_brief` token 同源；可整份替换成公司模板。
  模板里可用的变量：`title`、`subtitle`、`sections`。
  `sections` 每项含 `heading` / `level` / `paragraphs[]` / `bullets[]` / `tables[][][]`。
  模板里保留着 `{%p %}` / `{%tr %}` / `{%tc %}` 标签——这是 docxtpl 的写法，直接在 Word
  里看会是原始文本，属正常现象。排版规则见 `docs/WRITING-STANDARD-2026-10-02.md`。

Typst 不需要模板：样式预置在代码里，装了 `typst` 就自动生效。

目录可用环境变量 `DESKMATE_OFFICE_TEMPLATES` 指到别处。
