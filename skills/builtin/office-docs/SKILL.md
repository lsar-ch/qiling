---
name: office-docs
description: Office 办公：读取、生成和修改 Word、Excel、PowerPoint 文件，支持模板套数据与内容整理。
triggers: ["word", "excel", "ppt", "文档", "表格", "幻灯片", "office"]
tools: ["office_scripts"]
enabled: true
---
# Office 文档处理流程

1. **明确目标**：确认文件类型（.docx/.xlsx/.pptx）与动作（读取/生成/修改/提取/套模板）；旧格式 .doc/.xls 不支持。
2. **先读后改**：处理前先读取现有结构（段落、工作表、幻灯片），保留原有内容与格式，只改要求的部分。
3. **用脚本执行**：调用本技能 scripts/ 下的脚本，参数走白名单；不执行任意 shell。
4. **写入前确认**：新建可直接执行；覆盖、批量修改、删除内容需先向用户确认。
5. **回报**：给出文件路径、改动摘要与关键数据（行数/工作表数/页数）。

依赖 python-docx / openpyxl / python-pptx；若运行环境未安装，先提示安装，不假装处理成功。
