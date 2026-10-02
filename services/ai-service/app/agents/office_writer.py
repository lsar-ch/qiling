"""办公写作渲染器：把模型写的 Markdown 落成"能直接交付"的 docx / xlsx / pptx / pdf。

落地标准（不是"能打开就行"）：排版按 ``standard_business_brief`` 预设固化为下面的
token，四个格式共用同一套视觉语言，且每条都在测试里被断言、并经过 soffice 渲染验收。

- 页面：Letter 纵向，四边 1in 页边距，页眉/页脚距 0.492in，正文宽 9360 DXA
- 字体：Calibri 11pt（中文走东亚洲字体），正文 after 6pt / 行距 1.10
- 标题：H1 16pt #2E74B5（前 16pt/后 8pt）、H2 13pt #2E74B5（12/6）、H3 12pt #1F4D78（8/4）
- 列表：真实 Word 编号定义，标记对齐 0.25in / 文本缩进 0.5in / 悬挂 0.25in，after 8pt
- 表格：固定 DXA 几何（tblW=tblGrid=每个 tcW=9360，tblInd=120），表头填充 #F2F4F7，
  单线边框、单元格边距 上下 80 / 左右 120 DXA；表头行跨页重复
- 页眉页脚：安静的运行标题 + 右对齐真实页码域，多页文档一致

模型只负责写 Markdown，排版全部由这里确定性生成——所以排版质量不取决于模型，
可以脱机单测，也可以渲染成图逐页验收。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ── 排版 token（standard_business_brief）────────────────────────────────
PRESET_NAME = "standard_business_brief"
FONT_LATIN = "Calibri"

# 中文字体必须按运行平台挑真实存在的字体，否则生成端就把字写丢了：
# 早前写死「等线」（Windows 字体）在 macOS 上渲染出来是空心方框甚至整段消失。
_MAC_CJK_FONTS = (
    ("Hiragino Sans GB", "/System/Library/Fonts/Hiragino Sans GB.ttc"),
    ("PingFang SC", "/System/Library/Fonts/PingFang.ttc"),
    ("Songti SC", "/System/Library/Fonts/Supplemental/Songti.ttc"),
)
_WIN_CJK_FONTS = ("微软雅黑", "Microsoft YaHei", "等线", "宋体")
# 每项是 (常规体, 粗体)：路径 + .ttc 子字体下标（.ttf 用 None）。
# PDF 必须真正嵌入字体文件，reportlab 的 CID 字体（STSong-Light）只写字体名，
# 查看器没有该字体时中文就变成空心方框——本机渲染验收时实测到过。
_PDF_FONTS = {
    "darwin": (
        ("/System/Library/Fonts/Supplemental/Songti.ttc", 6),   # STSongti-SC-Regular
        ("/System/Library/Fonts/Supplemental/Songti.ttc", 1),   # STSongti-SC-Bold
    ),
    "win32": (
        ("C:/Windows/Fonts/msyh.ttc", 0),
        ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ),
}
_PDF_FONTS_LINUX = (
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
)


def cjk_font_name() -> str:
    """当前平台上可用的中文字体名（供 docx / pptx 的 eastAsia 使用）。"""
    if sys.platform == "darwin":
        for name, path in _MAC_CJK_FONTS:
            if Path(path).exists():
                return name
    if sys.platform == "win32":
        return _WIN_CJK_FONTS[0]
    return "Noto Sans CJK SC"


def _register_pdf_fonts() -> tuple[str, str] | None:
    """注册可嵌入的中文字体，返回 (常规体名, 粗体名)；找不到可用字体返回 None。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular, bold = _PDF_FONTS.get(sys.platform, _PDF_FONTS_LINUX)
    if not (Path(regular[0]).exists() and Path(bold[0]).exists()):
        return None
    try:
        pdfmetrics.registerFont(TTFont("DeskMateCJK", regular[0], subfontIndex=regular[1])
                                if regular[1] is not None else TTFont("DeskMateCJK", regular[0]))
        pdfmetrics.registerFont(TTFont("DeskMateCJK-Bold", bold[0], subfontIndex=bold[1])
                                if bold[1] is not None else TTFont("DeskMateCJK-Bold", bold[0]))
    except Exception:
        return None
    pdfmetrics.registerFontFamily(
        "DeskMateCJK", normal="DeskMateCJK", bold="DeskMateCJK-Bold",
        italic="DeskMateCJK", boldItalic="DeskMateCJK-Bold",
    )
    return "DeskMateCJK", "DeskMateCJK-Bold"

PAGE_W_IN = 8.5
PAGE_H_IN = 11.0
MARGIN_IN = 1.0
HEADER_DISTANCE_IN = 0.492
CONTENT_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120
CELL_MARGIN_DXA = {"top": 80, "bottom": 80, "start": 120, "end": 120}

_TYPST_TIMEOUT_S = 120

logger = logging.getLogger(__name__)

HEADING_BLUE = "2E74B5"
HEADING_DARK = "1F4D78"
TABLE_HEADER_FILL = "F2F4F7"
TABLE_BORDER = "BFBFBF"
MUTED_INK = "595959"

BODY_PT = 11
BODY_AFTER_PT = 6
BODY_LINE = 1.10
BULLET_AFTER_PT = 8
BULLET_LINE = 1.167
BULLET_MARKER_AT_IN = 0.25
BULLET_TEXT_AT_IN = 0.5
BULLET_HANGING_IN = 0.25

HEADING_TOKENS = {
    "h1": {"pt": 16, "color": HEADING_BLUE, "before": 16, "after": 8},
    "h2": {"pt": 13, "color": HEADING_BLUE, "before": 12, "after": 6},
    "h3": {"pt": 12, "color": HEADING_DARK, "before": 8, "after": 4},
}
TITLE_TOKEN = {"pt": 24, "color": HEADING_DARK, "before": 0, "after": 6}

# 工作类型 → 默认输出后缀
_KIND_SUFFIX = {
    "word": ".docx",
    "excel": ".xlsx",
    "ppt": ".pptx",
    "pdf": ".pdf",
    "image": ".md",
    "email": ".md",
    "general": ".md",
    "code": ".md",
    "project": ".md",
    "browser": ".md",
}

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")

# PPT 一页放不下就分页：按要点条数 + 单条长度双重约束，避免文字溢出页面
PPT_MAX_BULLETS = 6
PPT_MAX_CHARS = 420


@dataclass
class Block:
    """一段结构化正文：标题 / 列表项 / 段落 / 表格。"""

    kind: str  # h1 | h2 | h3 | bullet | paragraph | table
    text: str = ""
    rows: list[list[str]] = field(default_factory=list)


def parse_markdown(text: str) -> list[Block]:
    """把模型输出的 Markdown 解析成渲染无关的块列表。"""
    blocks: list[Block] = []
    paragraph: list[str] = []
    table: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(Block("paragraph", text=" ".join(paragraph).strip()))
            paragraph.clear()

    def flush_table() -> None:
        if table:
            blocks.append(Block("table", rows=[row[:] for row in table]))
            table.clear()

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_table()
            continue
        if _TABLE_SEP.match(line):
            continue
        table_match = _TABLE_ROW.match(line)
        if table_match:
            flush_paragraph()
            table.append([cell.strip() for cell in table_match.group(1).split("|")])
            continue
        flush_table()
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            blocks.append(Block(f"h{len(heading.group(1))}", text=heading.group(2).strip()))
            continue
        bullet = _BULLET.match(line)
        if bullet:
            flush_paragraph()
            blocks.append(Block("bullet", text=bullet.group(1).strip()))
            continue
        paragraph.append(line.strip())
    flush_paragraph()
    flush_table()
    return blocks


def title_of(blocks: list[Block], fallback: str = "DeskMate 生成文档") -> str:
    for block in blocks:
        if block.kind == "h1" and block.text:
            return block.text
    for block in blocks:
        if block.text:
            return block.text[:40]
    return fallback


def default_filename(kind: str, title: str = "") -> str:
    """按工作类型给默认文件名；只用安全字符，避免模型内容变成路径。"""
    suffix = _KIND_SUFFIX.get(kind, ".md")
    stem = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (title or "").strip())[:30].strip("_")
    return f"{stem or 'deskmate_doc'}{suffix}"


def write_file(path: Path, kind: str, blocks: list[Block], raw_text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "word":
        # 装了 docxtpl 且放了 Word 模板就套版，否则走内置渲染器（always 可用）。
        if not _write_docx_via_template(path, blocks):
            _write_docx(path, blocks)
    elif kind == "excel":
        _write_xlsx(path, blocks)
    elif kind == "ppt":
        _write_pptx(path, blocks)
    elif kind == "pdf":
        # 装了 typst 就用它排版（版式更好），否则走内置 reportlab 渲染器。
        if not _write_pdf_via_typst(path, blocks):
            _write_pdf(path, blocks)
    else:
        path.write_text(raw_text or render_markdown(blocks), encoding="utf-8")
    return path


def render_markdown(blocks: list[Block]) -> str:
    lines: list[str] = []
    for block in blocks:
        if block.kind.startswith("h"):
            lines.append("#" * int(block.kind[1]) + " " + block.text)
        elif block.kind == "bullet":
            lines.append(f"- {block.text}")
        elif block.kind == "table" and block.rows:
            lines.append("| " + " | ".join(block.rows[0]) + " |")
            for row in block.rows[1:]:
                lines.append("| " + " | ".join(row) + " |")
        else:
            lines.append(block.text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ============================================================== DOCX

def _pt(value: float) -> int:
    """pt → OOXML 二十分之一磅（twips for spacing）。"""
    return int(round(value * 20))


def _set_east_asian(style, font_name: str | None = None) -> None:
    from docx.oxml.ns import qn

    font_name = font_name or cjk_font_name()
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)


def _configure_styles(doc) -> None:
    """把 Normal / Heading 1-3 写成预设的确切数值，不依赖 Word 默认。"""
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt, RGBColor

    normal = doc.styles["Normal"]
    normal.font.name = FONT_LATIN
    normal.font.size = Pt(BODY_PT)
    normal.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(BODY_AFTER_PT)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    normal.paragraph_format.line_spacing = BODY_LINE
    _set_east_asian(normal)

    for name, token in (("Heading 1", HEADING_TOKENS["h1"]),
                        ("Heading 2", HEADING_TOKENS["h2"]),
                        ("Heading 3", HEADING_TOKENS["h3"])):
        style = doc.styles[name]
        style.font.name = FONT_LATIN
        style.font.size = Pt(token["pt"])
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(token["color"])
        style.paragraph_format.space_before = Pt(token["before"])
        style.paragraph_format.space_after = Pt(token["after"])
        style.paragraph_format.keep_with_next = True
        _set_east_asian(style)


def _add_bullet_numbering(doc) -> int:
    """注入真实 Word 编号定义（不用内置 List Bullet 的默认值）。"""
    from docx.oxml.ns import qn

    numbering = doc.part.numbering_part.element
    abstract_ids = [int(node.get(qn("w:abstractNumId")))
                    for node in numbering.findall(qn("w:abstractNum"))]
    abstract_id = (max(abstract_ids) + 1) if abstract_ids else 1
    num_ids = [int(node.get(qn("w:numId"))) for node in numbering.findall(qn("w:num"))]
    num_id = (max(num_ids) + 1) if num_ids else 1

    abstract = numbering.makeelement(qn("w:abstractNum"), {qn("w:abstractNumId"): str(abstract_id)})
    multi = abstract.makeelement(qn("w:multiLevelType"), {qn("w:val"): "hybridMultilevel"})
    abstract.append(multi)
    level = abstract.makeelement(qn("w:lvl"), {qn("w:ilvl"): "0"})
    for tag, value in (
        ("w:start", "1"),
        ("w:numFmt", "bullet"),
        ("w:lvlText", "\u2022"),
        ("w:lvlJc", "left"),
    ):
        node = level.makeelement(qn(tag), {qn("w:val"): value})
        level.append(node)
    level_fonts = level.makeelement(
        qn("w:rFonts"),
        {
            qn("w:ascii"): FONT_LATIN,
            qn("w:hAnsi"): FONT_LATIN,
            qn("w:eastAsia"): cjk_font_name(),
            qn("w:hint"): "default",
        },
    )
    level.insert(0, level_fonts)
    indent = level.makeelement(qn("w:pPr"), {})
    ind = indent.makeelement(
        qn("w:ind"),
        {
            qn("w:left"): str(int(BULLET_TEXT_AT_IN * 1440)),
            qn("w:hanging"): str(int(BULLET_HANGING_IN * 1440)),
        },
    )
    indent.append(ind)
    level.append(indent)
    abstract.append(level)
    numbering.insert(0, abstract)

    num = numbering.makeelement(qn("w:num"), {qn("w:numId"): str(num_id)})
    ref = num.makeelement(qn("w:abstractNumId"), {qn("w:val"): str(abstract_id)})
    num.append(ref)
    numbering.append(num)
    return num_id


def _apply_bullet(paragraph, num_id: int) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt
    from docx.enum.text import WD_LINE_SPACING

    ppr = paragraph._p.get_or_add_pPr()
    numpr = ppr.makeelement(qn("w:numPr"), {})
    ilvl = numpr.makeelement(qn("w:ilvl"), {qn("w:val"): "0"})
    numid = numpr.makeelement(qn("w:numId"), {qn("w:val"): str(num_id)})
    numpr.append(ilvl)
    numpr.append(numid)
    ppr.append(numpr)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(BULLET_AFTER_PT)
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    paragraph.paragraph_format.line_spacing = BULLET_LINE


def _set_table_geometry(table, column_count: int) -> None:
    """固定 DXA 几何：tblW / tblInd / tblGrid / 每个 tcW 全部对齐 9360。"""
    from docx.oxml.ns import qn

    column_width = CONTENT_WIDTH_DXA // max(column_count, 1)
    tbl_pr = table._tbl.tblPr
    for tag in ("w:tblW", "w:tblInd"):
        existing = tbl_pr.find(qn(tag))
        if existing is not None:
            tbl_pr.remove(existing)
    tbl_w = tbl_pr.makeelement(qn("w:tblW"), {qn("w:w"): str(CONTENT_WIDTH_DXA), qn("w:type"): "dxa"})
    tbl_ind = tbl_pr.makeelement(qn("w:tblInd"), {qn("w:w"): str(TABLE_INDENT_DXA), qn("w:type"): "dxa"})
    tbl_pr.append(tbl_w)
    tbl_pr.append(tbl_ind)
    layout = tbl_pr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
    tbl_pr.append(layout)

    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        table._tbl.remove(grid)
    grid = table._tbl.makeelement(qn("w:tblGrid"), {})
    for index in range(column_count):
        width = column_width if index < column_count - 1 else CONTENT_WIDTH_DXA - column_width * (column_count - 1)
        grid.append(grid.makeelement(qn("w:gridCol"), {qn("w:w"): str(width)}))
    table._tbl.insert(list(table._tbl).index(tbl_pr) + 1, grid)

    for row in table.rows:
        for index, cell in enumerate(row.cells):
            width = column_width if index < column_count - 1 else CONTENT_WIDTH_DXA - column_width * (column_count - 1)
            tc_pr = cell._tc.get_or_add_tcPr()
            for tag in ("w:tcW", "w:tcMar"):
                found = tc_pr.find(qn(tag))
                if found is not None:
                    tc_pr.remove(found)
            tc_w = tc_pr.makeelement(qn("w:tcW"), {qn("w:w"): str(width), qn("w:type"): "dxa"})
            tc_pr.append(tc_w)
            mar = tc_pr.makeelement(qn("w:tcMar"), {})
            for side, value in CELL_MARGIN_DXA.items():
                mar.append(mar.makeelement(
                    qn(f"w:{'start' if side == 'start' else side}"),
                    {qn("w:w"): str(value), qn("w:type"): "dxa"},
                ))
            tc_pr.append(mar)


def _style_table(table, column_count: int) -> None:
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Pt, RGBColor

    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    table.style = "Table Grid"
    _set_table_geometry(table, column_count)

    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), TABLE_BORDER)
        borders.append(node)
    table._tbl.tblPr.append(borders)

    # 表头样式 + 跨页重复
    header_cells = table.rows[0].cells
    for cell in header_cells:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), TABLE_HEADER_FILL)
        cell._tc.get_or_add_tcPr().append(shading)
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:tblHeader"))

    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(2)
                paragraph.paragraph_format.space_after = Pt(2)
                for run in paragraph.runs:
                    run.font.size = Pt(10)
                    if row_index == 0:
                        run.font.bold = True
                        run.font.color.rgb = RGBColor.from_string(HEADING_DARK)


def _add_footer(doc, label: str) -> None:
    """页脚：左运行标题 + 右真实页码域。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    section = doc.sections[0]
    paragraph = section.footer.paragraphs[0]
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor.from_string(MUTED_INK)
    run.add_text(label + "　|　")
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = "PAGE"
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    run._r.append(begin); run._r.append(instr); run._r.append(end)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)


def _set_east_asian_run(run, font_name: str | None = None) -> None:
    """直接格式化的 run 也要显式给东亚洲字体，否则中文在部分渲染器里丢字形。"""
    from docx.oxml.ns import qn

    rpr = run._r.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), FONT_LATIN)
    rfonts.set(qn("w:hAnsi"), FONT_LATIN)
    rfonts.set(qn("w:eastAsia"), font_name or cjk_font_name())


def _configure_page(doc) -> None:
    from docx.shared import Inches

    section = doc.sections[0]
    section.page_width = Inches(PAGE_W_IN)
    section.page_height = Inches(PAGE_H_IN)
    section.top_margin = Inches(MARGIN_IN)
    section.bottom_margin = Inches(MARGIN_IN)
    section.left_margin = Inches(MARGIN_IN)
    section.right_margin = Inches(MARGIN_IN)
    section.header_distance = Inches(HEADER_DISTANCE_IN)
    section.footer_distance = Inches(HEADER_DISTANCE_IN)


def _write_docx(path: Path, blocks: list[Block]) -> None:
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    _configure_page(doc)
    _configure_styles(doc)
    num_id = _add_bullet_numbering(doc)
    _add_footer(doc, "DeskMate")

    title = title_of(blocks)
    heading = doc.add_paragraph()
    heading.paragraph_format.space_before = Pt(TITLE_TOKEN["before"])
    heading.paragraph_format.space_after = Pt(TITLE_TOKEN["after"])
    run = heading.add_run(title)
    run.font.name = FONT_LATIN
    _set_east_asian_run(run)
    run.font.size = Pt(TITLE_TOKEN["pt"])
    run.font.bold = True
    run.font.color.rgb = RGBColor.from_string(TITLE_TOKEN["color"])

    first_heading_skipped = False
    for block in blocks:
        if block.kind == "h1":
            # 首个 h1 已经作为标题渲染过，不再重复
            if not first_heading_skipped and block.text == title:
                first_heading_skipped = True
                continue
            doc.add_heading(block.text, level=1)
        elif block.kind in ("h2", "h3"):
            doc.add_heading(block.text, level=int(block.kind[1]))
        elif block.kind == "bullet":
            paragraph = doc.add_paragraph()
            _apply_bullet(paragraph, num_id)
            paragraph.add_run(block.text)
        elif block.kind == "table" and block.rows:
            column_count = max(len(row) for row in block.rows)
            table = doc.add_table(rows=0, cols=column_count)
            for row in block.rows:
                cells = table.add_row().cells
                for index in range(column_count):
                    cells[index].text = row[index] if index < len(row) else ""
            _style_table(table, column_count)
            doc.add_paragraph()
        elif block.text:
            doc.add_paragraph(block.text)
    doc.save(str(path))


# ============================================================== XLSX

def _write_xlsx(path: Path, blocks: list[Block]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    thin = Side(style="thin", color=TABLE_BORDER)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor=TABLE_HEADER_FILL)
    header_font = Font(name=FONT_LATIN, bold=True, color=HEADING_DARK, size=11)

    wb = Workbook()
    sheet = wb.active
    sheet.title = "说明"
    sheet.sheet_properties.tabColor = HEADING_BLUE
    row = 1
    title = title_of(blocks)
    sheet.cell(row=row, column=1, value=title).font = Font(
        name=FONT_LATIN, bold=True, size=14, color=HEADING_DARK
    )
    row += 2
    for block in blocks:
        if block.kind == "table":
            continue
        if block.kind.startswith("h"):
            cell = sheet.cell(row=row, column=1, value=block.text)
            cell.font = Font(name=FONT_LATIN, bold=True, size=12, color=HEADING_BLUE)
        elif block.kind == "bullet":
            sheet.cell(row=row, column=1, value="•")
            sheet.cell(row=row, column=2, value=block.text)
            sheet.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        elif block.text:
            cell = sheet.cell(row=row, column=1, value=block.text)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    sheet.column_dimensions["A"].width = 60
    sheet.column_dimensions["B"].width = 60

    for index, block in enumerate([b for b in blocks if b.kind == "table" and b.rows], start=1):
        data = wb.create_sheet(f"表{index}")
        data.sheet_properties.tabColor = HEADING_BLUE
        for row_index, values in enumerate(block.rows, start=1):
            for column_index, value in enumerate(values, start=1):
                cell = data.cell(row=row_index, column=column_index, value=value)
                cell.border = border
                cell.alignment = Alignment(
                    wrap_text=True, vertical="center",
                    horizontal="center" if row_index == 1 else "left",
                )
                if row_index == 1:
                    cell.fill = header_fill
                    cell.font = header_font
        data.freeze_panes = "A2"
        if len(block.rows) > 1:
            data.auto_filter.ref = (
                f"A1:{get_column_letter(max(len(r) for r in block.rows))}{len(block.rows)}"
            )
        for column_index in range(1, max(len(r) for r in block.rows) + 1):
            widest = max(
                (len(str(r[column_index - 1])) for r in block.rows if len(r) >= column_index),
                default=8,
            )
            data.column_dimensions[get_column_letter(column_index)].width = min(max(widest + 4, 12), 40)
        data.row_dimensions[1].height = 22

    wb.save(str(path))


# ============================================================== PPTX

def _slides_from_blocks(blocks: list[Block]) -> list[tuple[str, list[str]]]:
    """按 h1/h2 分节，再按条数/字数分页——避免内容溢出页面。"""
    slides: list[tuple[str, list[str]]] = []
    title: str | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        if title is not None and lines:
            for start in range(0, len(lines), PPT_MAX_BULLETS):
                chunk = lines[start:start + PPT_MAX_BULLETS]
                suffix = "" if start == 0 else "（续）"
                slides.append((title + suffix, chunk))
        elif title is not None:
            slides.append((title, []))
        lines = []

    for block in blocks:
        if block.kind in ("h1", "h2"):
            flush()
            title = block.text
        elif block.kind == "table" and block.rows:
            for row in block.rows:
                lines.append(" | ".join(row))
        elif block.text:
            lines.append(block.text)
        if sum(len(line) for line in lines) > PPT_MAX_CHARS and title is not None:
            flush()
            title = title.replace("（续）", "")
    flush()
    return slides or [("DeskMate", [])]


def _write_pptx(path: Path, blocks: list[Block]) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    # Title Only：保留真实标题占位符，PowerPoint 大纲视图与朗读模式才读得到标题
    title_layout = prs.slide_layouts[5]
    accent = RGBColor.from_string(HEADING_BLUE)
    dark = RGBColor.from_string(HEADING_DARK)
    muted = RGBColor.from_string(MUTED_INK)

    cjk = cjk_font_name()

    def set_run_font(run, size: float, *, color=dark, bold=False) -> None:
        """PowerPoint 的 run.font.name 只写拉丁字体，中文要另外写 a:ea，否则丢字形。"""
        from pptx.oxml import parse_xml
        from pptx.oxml.ns import nsdecls

        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = FONT_LATIN
        rpr = run._r.get_or_add_rPr()
        for tag, typeface in (("a:ea", cjk), ("a:cs", FONT_LATIN)):
            element = parse_xml(f'<{tag} {nsdecls("a")} typeface="{typeface}"/>')
            rpr.append(element)

    def add_text(slide, left, top, width, height, text, size, *, color=dark,
                 bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
        box = slide.shapes.add_textbox(left, top, width, height)
        frame = box.text_frame
        frame.word_wrap = True
        frame.vertical_anchor = anchor
        frame.text = text
        paragraph = frame.paragraphs[0]
        paragraph.alignment = align
        set_run_font(paragraph.runs[0], size, color=color, bold=bold)
        return frame

    def set_title(slide, text, left, top, width, height, size) -> None:
        """写进版式自带的标题占位符，而不是另加文本框。"""
        placeholder = slide.shapes.title
        placeholder.left, placeholder.top = left, top
        placeholder.width, placeholder.height = width, height
        frame = placeholder.text_frame
        frame.word_wrap = True
        frame.text = text
        paragraph = frame.paragraphs[0]
        paragraph.alignment = PP_ALIGN.LEFT
        set_run_font(paragraph.runs[0], size, bold=True)

    def add_footer(slide, index: int, total: int) -> None:
        add_text(slide, Inches(0.6), Inches(6.95), Inches(6.0), Inches(0.35),
                 "DeskMate", 10, color=muted)
        add_text(slide, Inches(11.2), Inches(6.95), Inches(1.5), Inches(0.35),
                 f"{index} / {total}", 10, color=muted, align=PP_ALIGN.RIGHT)

    slides = _slides_from_blocks(blocks)
    title_text = title_of(blocks)

    # 封面
    cover = prs.slides.add_slide(title_layout)
    bar = cover.shapes.add_shape(1, Inches(0), Inches(2.6), Inches(13.333), Inches(0.09))
    bar.fill.solid(); bar.fill.fore_color.rgb = accent; bar.line.fill.background()
    set_title(cover, title_text, Inches(1.2), Inches(2.85), Inches(10.9), Inches(1.6), 40)
    add_text(cover, Inches(1.2), Inches(4.5), Inches(10.9), Inches(0.5),
             "由 DeskMate 生成", 16, color=muted)

    total = len(slides) + 1
    for index, (slide_title, lines) in enumerate(slides, start=2):
        slide = prs.slides.add_slide(title_layout)
        rule = slide.shapes.add_shape(1, Inches(0.6), Inches(1.25), Inches(12.13), Inches(0.03))
        rule.fill.solid(); rule.fill.fore_color.rgb = accent; rule.line.fill.background()
        set_title(slide, slide_title, Inches(0.6), Inches(0.5), Inches(12.13), Inches(0.7), 28)
        if lines:
            body = add_text(slide, Inches(0.75), Inches(1.6), Inches(11.8), Inches(5.1),
                            lines[0], 16, color=RGBColor.from_string("1A1A1A"))
            for line in lines[1:]:
                paragraph = body.add_paragraph()
                paragraph.text = line
                set_run_font(paragraph.runs[0], 16, color=RGBColor.from_string("1A1A1A"))
                paragraph.space_after = Pt(10)
        add_footer(slide, index, total)

    prs.save(str(path))


# ============================================================== PDF

def _pdf_styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch

    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=TITLE_TOKEN["pt"],
                                textColor=f"#{TITLE_TOKEN['color']}", spaceAfter=14, alignment=0),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=HEADING_TOKENS["h1"]["pt"],
                             textColor=f"#{HEADING_BLUE}",
                             spaceBefore=HEADING_TOKENS["h1"]["before"],
                             spaceAfter=HEADING_TOKENS["h1"]["after"]),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=HEADING_TOKENS["h2"]["pt"],
                             textColor=f"#{HEADING_BLUE}",
                             spaceBefore=HEADING_TOKENS["h2"]["before"],
                             spaceAfter=HEADING_TOKENS["h2"]["after"]),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=HEADING_TOKENS["h3"]["pt"],
                             textColor=f"#{HEADING_DARK}",
                             spaceBefore=HEADING_TOKENS["h3"]["before"],
                             spaceAfter=HEADING_TOKENS["h3"]["after"]),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=BODY_PT, leading=BODY_PT * 1.6,
                               spaceAfter=BODY_AFTER_PT, alignment=0),
        "bullet": ParagraphStyle("bu", parent=base["BodyText"], fontSize=BODY_PT,
                                 leading=BODY_PT * 1.6, spaceAfter=BULLET_AFTER_PT,
                                 leftIndent=int(BULLET_TEXT_AT_IN * inch),
                                 bulletIndent=int(BULLET_MARKER_AT_IN * inch)),
    }


def _write_pdf(path: Path, blocks: list[Block]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    registered = _register_pdf_fonts()
    if registered is not None:
        regular_font, bold_font = registered
    else:
        # 兜底：没有可嵌入字体时用 CID 字体（查看器缺字体可能显示方框，
        # 单元测试会断言必须走到嵌入分支）。
        regular_font = bold_font = "Helvetica"
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            regular_font = bold_font = "STSong-Light"
        except Exception:
            pass

    styles = _pdf_styles()
    for style in styles.values():
        style.fontName = bold_font if style.name in ("t", "h1", "h2", "h3") else regular_font
    font = regular_font
    cell_style = ParagraphStyle("cell", parent=styles["body"], fontSize=9, leading=12, spaceAfter=0)

    content_width = (PAGE_W_IN - 2 * MARGIN_IN) * inch
    story: list = [Paragraph(title_of(blocks), styles["title"])]
    for block in blocks:
        if block.kind == "h1":
            if block.text == title_of(blocks):
                continue
            story.append(Paragraph(block.text, styles["h1"]))
        elif block.kind in ("h2", "h3"):
            story.append(Paragraph(block.text, styles[block.kind]))
        elif block.kind == "bullet":
            story.append(Paragraph(block.text, styles["bullet"], bulletText="•"))
        elif block.kind == "table" and block.rows:
            column_count = max(len(row) for row in block.rows)
            data = [
                [Paragraph(str(cell or ""), cell_style) for cell in row]
                + [Paragraph("", cell_style)] * (column_count - len(row))
                for row in block.rows
            ]
            table = Table(data, colWidths=[content_width / column_count] * column_count, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#" + TABLE_BORDER)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + TABLE_HEADER_FILL)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.extend([table, Spacer(1, 8)])
        elif block.text:
            story.append(Paragraph(block.text, styles["body"]))
    if len(story) == 1:
        story.append(Paragraph("（无内容）", styles["body"]))

    def draw_page(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(font, 9)
        canvas.setFillColor(colors.HexColor("#" + MUTED_INK))
        canvas.drawRightString(PAGE_W_IN * inch - MARGIN_IN * inch, 0.75 * inch, f"DeskMate　|　{doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(path), pagesize=letter,
        leftMargin=MARGIN_IN * inch, rightMargin=MARGIN_IN * inch,
        topMargin=MARGIN_IN * inch, bottomMargin=MARGIN_IN * inch,
        title=title_of(blocks), author="DeskMate",
    )
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)


# ============================================================== 可选引擎（装了才用）

_TYPST_PREAMBLE = """#set page(
  paper: "us-letter",
  margin: 1in,
  footer: context [
    #set text(size: 9pt, fill: rgb("#595959"))
    #h(1fr)
    #counter(page).display()
  ],
)
#set text(size: 11pt, lang: "zh")
#set par(justify: true, leading: 0.72em, spacing: 12pt)

#show heading.where(level: 1): it => block(above: 16pt, below: 8pt, text(size: 16pt, weight: "bold", fill: rgb("#2E74B5"), it.body))
#show heading.where(level: 2): it => block(above: 12pt, below: 6pt, text(size: 13pt, weight: "bold", fill: rgb("#2E74B5"), it.body))
#show heading.where(level: 3): it => block(above: 8pt, below: 4pt, text(size: 12pt, weight: "bold", fill: rgb("#1F4D78"), it.body))
"""

# Typst 标记语言里这些字符有含义，正文必须转义，否则模型写的 # * _ [ 会把版面搞坏。
_TYPST_ESCAPE = re.compile(r"([\\#$*_`<>@~\[\]])")
_TYPST_BOLD = re.compile(r"\*\*(.+?)\*\*")


def template_dir() -> Path:
    """模板目录（支持 ``DESKMATE_OFFICE_TEMPLATES`` 覆盖）。"""
    from app.config import repo_root

    configured = os.environ.get("DESKMATE_OFFICE_TEMPLATES")
    return Path(configured) if configured else repo_root() / "config" / "office_templates"


def _typst_escape(text: str) -> str:
    """转义 Typst 标记字符；顺手把 Markdown 的 **粗体** 换成 Typst 的 *粗体*。"""
    return _TYPST_ESCAPE.sub(r"\\\1", _TYPST_BOLD.sub(r"*\1*", text or ""))


def typst_source(blocks: list[Block]) -> str:
    """把块列表编译成 Typst 源码（预置样式 + 正文）。"""
    lines = [_TYPST_PREAMBLE]
    previous = ""
    for block in blocks:
        # 连续的列表项之间不能插空行，否则会被拆成多个列表、行距变松。
        if previous and not (previous == "bullet" and block.kind == "bullet"):
            lines.append("")
        if block.kind.startswith("h"):
            lines.append("=" * int(block.kind[1]) + " " + _typst_escape(block.text))
        elif block.kind == "bullet":
            lines.append("- " + _typst_escape(block.text))
        elif block.kind == "table" and block.rows:
            header = block.rows[0]
            cells = ", ".join(_typst_cell(cell) for row in block.rows[1:] for cell in row)
            lines.append("#table(")
            lines.append(f"  columns: {len(header)}, inset: 7pt, align: left,")
            lines.append('  stroke: 0.5pt + rgb("#BFBFBF"),')
            lines.append("  table.header(" + ", ".join(_typst_cell(c) for c in header) + "),")
            lines.append(f"  {cells},")
            lines.append(")")
        elif block.text:
            lines.append(_typst_escape(block.text))
        previous = block.kind
    return "\n".join(lines).strip() + "\n"


def _typst_cell(text: str) -> str:
    return "[" + _typst_escape(text) + "]"


def _write_pdf_via_typst(path: Path, blocks: list[Block]) -> bool:
    """用 typst binary 排版 PDF；未安装或编译失败返回 False 交给内置渲染器。"""
    binary = shutil.which("typst")
    if binary is None:
        return False
    with tempfile.TemporaryDirectory(prefix="deskmate-typst-") as tmp:
        source = Path(tmp) / "doc.typ"
        source.write_text(typst_source(blocks), encoding="utf-8")
        try:
            proc = subprocess.run(
                [binary, "compile", str(source), str(path)],
                capture_output=True, text=True, timeout=_TYPST_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("typst 编译失败，回落内置 PDF 渲染：%s", exc)
            return False
    if proc.returncode != 0 or not path.exists():
        logger.warning("typst 编译失败，回落内置 PDF 渲染：%s", (proc.stderr or "").strip()[:300])
        return False
    return True


def docx_template_context(blocks: list[Block]) -> dict:
    """docxtpl 模板的渲染上下文；模板写法见 docs/OFFICE-TOOLS-2026-10-01.md。"""
    title = title_of(blocks)
    sections: list[dict] = []
    current = _new_section("", 0, sections)
    consumed_title = False
    for block in blocks:
        if block.kind == "h1" and not consumed_title:
            consumed_title = True
            continue
        if block.kind in ("h1", "h2", "h3"):
            current = _new_section(block.text, int(block.kind[1]), sections)
        elif block.kind == "bullet":
            current["bullets"].append(block.text)
        elif block.kind == "table":
            current["tables"].append(block.rows)
        elif block.text:
            current["paragraphs"].append(block.text)
    return {
        "title": title,
        "subtitle": "由 DeskMate 生成",
        "sections": [s for s in sections if _section_has_content(s)],
    }


def _new_section(heading: str, level: int, into: list[dict]) -> dict:
    section = {"heading": heading, "level": level, "paragraphs": [], "bullets": [], "tables": []}
    into.append(section)
    return section


def _section_has_content(section: dict) -> bool:
    return bool(
        section["heading"] or section["paragraphs"] or section["bullets"] or section["tables"]
    )


def _write_docx_via_template(path: Path, blocks: list[Block]) -> bool:
    """装了 docxtpl 且模板目录里有 word.docx 时套用品牌模板；否则返回 False。

    仓库自带默认模板（与内置 token 同源），用户可用公司模板整体覆盖；没有模板或没装
    docxtpl 时，内置渲染器已经能产出统一排版的 Word。占位符见
    ``docs/WRITING-STANDARD-2026-10-02.md``。
    """
    template = template_dir() / "word.docx"
    if not template.exists():
        return False
    try:
        from docxtpl import DocxTemplate
    except ImportError:
        return False
    try:
        document = DocxTemplate(str(template))
        document.render(docx_template_context(blocks))
        document.save(str(path))
    except Exception as exc:  # 模板语法错误等一律回落，不能因为装了个引擎反而写不出文件
        logger.warning("docxtpl 模板渲染失败，回落内置 Word 渲染：%s", exc)
        return False
    return True
