"""Экспорт отчёта в Excel: каждая таблица - на отдельном листе.

Числа пишутся как числа (а не строки), чтобы пользователь мог сразу считать
по ним что-то своё. Это частая причина раздражения при экспорте из SPSS.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from winnow.stats.result import Result, Table

try:  # pragma: no cover - зависит от окружения
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    XLSX_AVAILABLE = True
except Exception:  # pragma: no cover
    Workbook = None
    XLSX_AVAILABLE = False


class XlsxNotAvailable(RuntimeError):
    """openpyxl не установлен."""


def _require_openpyxl() -> None:
    if not XLSX_AVAILABLE:
        raise XlsxNotAvailable(
            "Для экспорта в Excel установите openpyxl: pip install openpyxl"
        )


_INVALID_SHEET = re.compile(r"[\\/*?:\[\]]")


def _sheet_name(index: int, table: Table) -> str:
    """Excel ограничивает имя листа 31 символом и запрещает часть символов."""
    base = _INVALID_SHEET.sub("-", table.title or f"Таблица {index}")
    return f"{index}. {base}"[:31]


def _write_table(sheet: Any, table: Table) -> None:
    header_font = Font(bold=True, size=10)
    header_fill = PatternFill("solid", fgColor="E8EEF4")
    thin = Side(style="thin", color="B9C4CF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    body_font = Font(size=10)
    caption_font = Font(bold=True, size=11)

    sheet.cell(row=1, column=1, value=table.caption).font = caption_font

    header_row = 3
    for column_index, column in enumerate(table.columns, start=1):
        cell = sheet.cell(row=header_row, column=column_index, value=column.label)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_index, row in enumerate(table.rows, start=header_row + 1):
        for column_index, (column, value) in enumerate(zip(table.columns, row), start=1):
            # Проценты и подобные величины пишутся строкой: иначе Excel покажет
            # "25.0" без знака процента и пользователь не поймёт, что это доля.
            written: Any = (
                str(value) + column.suffix if (column.suffix and value is not None) else value
            )
            cell = sheet.cell(row=row_index, column=column_index, value=written)
            cell.font = body_font
            cell.border = border
            if column.align == "right":
                cell.alignment = Alignment(horizontal="right")
                if isinstance(value, float) and column.decimals is not None and not column.suffix:
                    cell.number_format = "0." + "0" * column.decimals
            else:
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

    note_row = header_row + len(table.rows) + 2
    for offset, note in enumerate(table.footnotes):
        cell = sheet.cell(row=note_row + offset, column=1, value=note)
        cell.font = Font(size=9, color="55636F")

    for column_index, column in enumerate(table.columns, start=1):
        width = max(10, min(38, len(column.label) + 4))
        if column.align == "left":
            width = max(width, 22)
        sheet.column_dimensions[get_column_letter(column_index)].width = width


def result_to_xlsx(results: list[Result] | Result, path: str | Path) -> Path:
    _require_openpyxl()
    if isinstance(results, Result):
        results = [results]

    workbook = Workbook()
    workbook.remove(workbook.active)

    index = 0
    for result in results:
        for table in result.tables:
            index += 1
            sheet = workbook.create_sheet(_sheet_name(index, table))
            _write_table(sheet, table)

    if index == 0:
        sheet = workbook.create_sheet("Пусто")
        sheet.cell(row=1, column=1, value="В отчёте нет таблиц")

    path = Path(path)
    workbook.save(str(path))
    return path


__all__ = ["XLSX_AVAILABLE", "XlsxNotAvailable", "result_to_xlsx"]
