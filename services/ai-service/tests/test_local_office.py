"""LocalOfficeAdapter 与办公降级逻辑测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents.base import AgentTaskRequest
from app.agents.local_office import (
    LocalOfficeAdapter,
    _find_office_files,
    _read_docx,
    _read_xlsx,
    _read_pptx,
)


@pytest.fixture
def tmp_office_dir(tmp_path):
    """创建临时办公文件用于测试。"""
    from docx import Document
    doc = Document()
    doc.add_heading("测试标题", level=1)
    doc.add_paragraph("这是第一段正文内容。")
    doc.add_paragraph("这是第二段。")
    doc.save(str(tmp_path / "test.docx"))

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "数据"
    ws.append(["姓名", "年龄", "城市"])
    ws.append(["张三", 25, "北京"])
    ws.append(["李四", 30, "上海"])
    ws.append(["王五", 28, "广州"])
    wb.save(str(tmp_path / "test.xlsx"))

    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "首页标题"
    if len(slide.placeholders) > 1:
        slide.placeholders[1].text = "副标题内容"
    slide2 = prs.slides.add_slide(prs.slide_layouts[0])
    slide2.shapes.title.text = "第二页"
    if len(slide2.placeholders) > 1:
        slide2.placeholders[1].text = "第二页正文"
    prs.save(str(tmp_path / "test.pptx"))

    return tmp_path


class TestFindOfficeFiles:
    def test_finds_docx(self, tmp_office_dir):
        files = _find_office_files(str(tmp_office_dir), "word")
        assert len(files) == 1
        assert files[0].name == "test.docx"

    def test_finds_xlsx(self, tmp_office_dir):
        files = _find_office_files(str(tmp_office_dir), "excel")
        assert len(files) == 1
        assert files[0].name == "test.xlsx"

    def test_finds_pptx(self, tmp_office_dir):
        files = _find_office_files(str(tmp_office_dir), "ppt")
        assert len(files) == 1
        assert files[0].name == "test.pptx"

    def test_returns_empty_for_unknown_kind(self, tmp_office_dir):
        files = _find_office_files(str(tmp_office_dir), "unknown")
        assert files == []

    def test_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        from docx import Document
        doc = Document()
        doc.add_paragraph("hidden")
        doc.save(str(hidden / "secret.docx"))
        files = _find_office_files(str(tmp_path), "word")
        assert files == []


class TestReadDocx:
    def test_reads_heading_and_body(self, tmp_office_dir):
        result = _read_docx(tmp_office_dir / "test.docx")
        assert "测试标题" in result
        assert "第一段正文" in result
        assert "第二段" in result

    def test_empty_doc(self, tmp_path):
        from docx import Document
        doc = Document()
        doc.save(str(tmp_path / "empty.docx"))
        result = _read_docx(tmp_path / "empty.docx")
        assert "空" in result or result == ""


class TestReadXlsx:
    def test_reads_header_and_data(self, tmp_office_dir):
        result = _read_xlsx(tmp_office_dir / "test.xlsx")
        assert "数据" in result
        assert "姓名" in result
        assert "张三" in result
        assert "北京" in result


class TestReadPptx:
    def test_reads_slides(self, tmp_office_dir):
        result = _read_pptx(tmp_office_dir / "test.pptx")
        assert "首页标题" in result
        assert "第二页" in result


class TestLocalOfficeAdapter:
    def test_detect_returns_ready(self):
        adapter = LocalOfficeAdapter()
        info = asyncio.run(adapter.detect())
        assert info.integration_status == "ready"
        assert info.available is True

    def test_run_reads_docx(self, tmp_office_dir):
        adapter = LocalOfficeAdapter()
        events = []

        async def on_update(kind, payload):
            events.append((kind, payload))

        async def run():
            request = AgentTaskRequest(
                task_id="test_001",
                prompt="读取这个文档",
                cwd=str(tmp_office_dir),
                config={"work_kind": "word"},
            )
            return await adapter.run(request, on_update)

        result = asyncio.run(run())
        assert result.status == "completed"
        assert "测试标题" in result.message
        assert len(events) > 0

    def test_run_reads_xlsx(self, tmp_office_dir):
        adapter = LocalOfficeAdapter()

        async def on_update(kind, payload):
            pass

        async def run():
            request = AgentTaskRequest(
                task_id="test_002",
                prompt="读取表格",
                cwd=str(tmp_office_dir),
                config={"work_kind": "excel"},
            )
            return await adapter.run(request, on_update)

        result = asyncio.run(run())
        assert result.status == "completed"
        assert "张三" in result.message

    def test_run_fails_for_unsupported(self, tmp_office_dir):
        adapter = LocalOfficeAdapter()

        async def on_update(kind, payload):
            pass

        async def run():
            request = AgentTaskRequest(
                task_id="test_003",
                prompt="读取代码",
                cwd=str(tmp_office_dir),
                config={"work_kind": "code"},
            )
            return await adapter.run(request, on_update)

        result = asyncio.run(run())
        assert result.status == "failed"
        assert "不支持" in result.error

    def test_run_fails_when_no_files(self, tmp_path):
        adapter = LocalOfficeAdapter()

        async def on_update(kind, payload):
            pass

        async def run():
            request = AgentTaskRequest(
                task_id="test_004",
                prompt="读取文档",
                cwd=str(tmp_path),
                config={"work_kind": "word"},
            )
            return await adapter.run(request, on_update)

        result = asyncio.run(run())
        assert result.status == "failed"
        assert "未找到" in result.error
