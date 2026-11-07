"""Экспорт отчёта в Word (.docx).

Зачем: конечная цель пользователя - вставить таблицу в статью или отчёт. Если
для этого приходится перерисовывать таблицу руками, продукт проигрывает SPSS
именно там, где это важнее всего.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from winnow.core.formatting import num
from winnow.stats.result import Result, Table

try:  # pragma: no cover - зависит от окружения
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    DOCX_AVAILABLE = True
except Exception:  # pragma: no cover
    Document = None
    DOCX_AVAILABLE = False


class DocxNotAvailable(RuntimeError):
    """python-docx не установлен."""


def _require_docx() -> None:
    if not DOCX_AVAILABLE:
        raise DocxNotAvailable(
            "Для экспорта в Word установите python-docx: pip install python-docx"
        )


def _cell_text(value: Any, decimals: int | None, suffix: str = "") -> str:
    if value is None:
        return "."
    if isinstance(value, float):
        return num(value, decimals) + suffix
    return str(value)


def _add_table(document: Any, table: Table) -> None:
    docx_table = document.add_table(rows=1, cols=len(table.columns))
    docx_table.style = "Table Grid"

    for index, column in enumerate(table.columns):
        cell = docx_table.rows[0].cells[index]
        cell.text = column.label
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(9)

    for row in table.rows:
        cells = docx_table.add_row().cells
        is_total = bool(row) and isinstance(row[0], str) and row[0].strip().lower() in (
            "всего",
            "итого",
        )
        for index, (column, value) in enumerate(zip(table.columns, row)):
            cells[index].text = _cell_text(value, column.decimals, column.suffix)
            for paragraph in cells[index].paragraphs:
                if column.align == "right":
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                for run in paragraph.runs:
                    run.font.size = Pt(9)
                    run.bold = bool(is_total)

    for note in table.footnotes:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(note)
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x55, 0x63, 0x6F)


def result_to_docx(
    results: list[Result] | Result, path: str | Path, title: str = "Отчёт Winnow"
) -> Path:
    """Сохраняет один или несколько результатов в .docx."""
    _require_docx()
    if isinstance(results, Result):
        results = [results]

    path = Path(path)
    document = Document()
    document.add_heading(title, level=0)

    for result in results:
        document.add_heading(result.title or result.procedure, level=1)
        # Блок «Простыми словами» - первым: его вставляют в текст работы, тогда
        # как таблицы идут в приложение.
        if result.findings:
            document.add_heading("Простыми словами", level=2)
            for finding in result.findings:
                paragraph = document.add_paragraph()
                run = paragraph.add_run(finding.text)
                run.font.size = Pt(10)
                if finding.is_conclusion:
                    run.bold = True
                elif finding.is_caution:
                    run.font.color.rgb = RGBColor(0x8A, 0x3B, 0x00)
        for note in result.notes:
            paragraph = document.add_paragraph()
            run = paragraph.add_run(note)
            run.italic = True
            run.font.size = Pt(9)

        for table in result.tables:
            document.add_heading(table.caption, level=2)
            _add_table(document, table)

        for warning in result.warnings:
            paragraph = document.add_paragraph()
            run = paragraph.add_run("Внимание: " + warning)
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x8A, 0x3B, 0x00)

    document.save(str(path))
    return path


def result_to_docx_html_fallback(results: list[Result] | Result, path: str | Path) -> Path:
    """Запасной путь: без python-docx сохраняем HTML с расширением .doc.

    Word открывает такой файл корректно, и пользователь не остаётся без отчёта.
    """
    if isinstance(results, Result):
        results = [results]
    from winnow.export.html import report_to_html

    Path(path).write_text(report_to_html(results), encoding="utf-8")
    return Path(path)


__all__ = [
    "DOCX_AVAILABLE",
    "DocxNotAvailable",
    "result_to_docx",
    "result_to_docx_html_fallback",
]
