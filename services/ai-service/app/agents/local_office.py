"""本地办公执行器：读取 docx/xlsx/pptx 并返回内容摘要。

B 为主、A 兜底：外部 Agent（Codex/WorkBuddy）不可用时，用本地库处理
窄场景办公任务（读取内容、数据摘要、简单统计）。复杂编辑/生成/美化
仍走外部 Agent。
"""

from __future__ import annotations

import logging
from pathlib import Path

from deskmate_contracts.agent import AgentInfo

from app.agents.base import (
    AgentAdapter,
    AgentTaskRequest,
    AgentTaskResult,
)

logger = logging.getLogger(__name__)

_SUFFIXES = {
    "word": {".docx"},
    "excel": {".xlsx"},
    "ppt": {".pptx"},
}


def _find_office_files(cwd: str, work_kind: str, limit: int = 5) -> list[Path]:
    """在工作目录下找到匹配 work_kind 的办公文件，按修改时间倒序。"""
    root = Path(cwd)
    if not root.is_dir():
        return []
    suffixes = _SUFFIXES.get(work_kind, set())
    found: list[tuple[float, Path]] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            if any(part.startswith(".") for part in path.parts):
                continue
            if path.name.startswith("~"):
                continue
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
    found.sort(reverse=True)
    return [path for _, path in found[:limit]]


def _read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    lines: list[str] = []
    for para in doc.paragraphs[:80]:
        text = para.text.strip()
        if text:
            style = para.style.name if para.style else ""
            if "Heading" in style:
                lines.append(f"## {text}")
            else:
                lines.append(text)
    for i, table in enumerate(doc.tables[:5]):
        lines.append(f"\n[表格 {i + 1}]")
        for row in table.rows[:20]:
            cells = [cell.text.strip() for cell in row.cells]
            lines.append(" | ".join(cells))
    if not lines:
        return "（文档为空或无可提取文本）"
    return "\n".join(lines)


def _read_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    for name in wb.sheetnames[:10]:
        ws = wb[name]
        parts.append(f"## 工作表：{name}")
        rows = list(ws.iter_rows(max_row=30, values_only=True))
        if not rows:
            parts.append("（空表）")
            continue
        header = [str(c) if c is not None else "" for c in rows[0]]
        parts.append(" | ".join(header))
        parts.append("-" * 40)
        for row in rows[1:]:
            cells = [str(c) if c is not None else "" for c in row]
            parts.append(" | ".join(cells))
        total_rows = ws.max_row or len(rows)
        if total_rows > 30:
            parts.append(f"... 共 {total_rows} 行，仅显示前 30 行")
    wb.close()
    return "\n".join(parts) if parts else "（工作簿为空）"


def _read_pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    parts: list[str] = []
    for i, slide in enumerate(list(prs.slides)[:30]):
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        texts.append(text)
        if texts:
            parts.append(f"## 第 {i + 1} 页")
            parts.extend(texts)
    if not parts:
        return "（演示文稿为空或无可提取文本）"
    return "\n".join(parts)


_READERS = {
    "word": _read_docx,
    "excel": _read_xlsx,
    "ppt": _read_pptx,
}


class LocalOfficeAdapter(AgentAdapter):
    """本地办公文件读取执行器，外部 Agent 不可用时的兜底。"""

    name = "local-office"
    adapter_id = "local-office"
    display_name = "本地办公"
    executable = True
    default_eligible = False

    async def detect(self) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            integration_status="ready",
            available=True,
            enabled=True,
            default_eligible=self.default_eligible,
            protocol="builtin",
            capabilities=["office", "read", "summarize"],
            tags=["builtin", "local"],
            detail="本地 python-docx/openpyxl/python-pptx 读取执行器",
        )

    async def run(
        self,
        request: AgentTaskRequest,
        on_update,
    ) -> AgentTaskResult:
        work_kind = request.config.get("work_kind", "")
        if work_kind not in _READERS:
            return AgentTaskResult(
                status="failed",
                error=f"本地执行器不支持类型：{work_kind}",
            )
        files = _find_office_files(request.cwd, work_kind)
        if not files:
            return AgentTaskResult(
                status="failed",
                error=f"工作目录下未找到 {_SUFFIXES.get(work_kind)} 文件",
            )
        reader = _READERS[work_kind]
        summaries: list[str] = []
        for path in files[:3]:
            try:
                await on_update(
                    "progress",
                    {"message": f"正在读取 {path.name}..."},
                )
                content = reader(path)
                if len(content) > 2000:
                    content = content[:2000] + "\n...（内容过长，已截断）"
                summaries.append(f"### {path.name}\n\n{content}")
            except Exception as exc:
                logger.warning("读取 %s 失败: %s", path, exc)
                summaries.append(f"### {path.name}\n\n读取失败：{exc}")
        if not summaries:
            return AgentTaskResult(
                status="failed",
                error="所有文件读取均失败",
            )
        return AgentTaskResult(
            status="completed",
            message="\n\n".join(summaries),
        )
