"""Экспорт результатов: тот же Result, но в разных форматах.

Вся логика форматирования чисел живёт в core.formatting и в рендерерах.
Процедуры отдают голые числа - это позволяет одному и тому же результату быть
корректным и в вебе, и в DOCX, и в Excel.
"""

from winnow.export.html import report_to_html, result_to_html, table_to_html

__all__ = ["report_to_html", "result_to_html", "table_to_html"]

try:  # pragma: no cover - зависит от окружения
    from winnow.export.docx import DOCX_AVAILABLE, result_to_docx

    __all__ += ["DOCX_AVAILABLE", "result_to_docx"]
except Exception:  # pragma: no cover
    DOCX_AVAILABLE = False

try:  # pragma: no cover - зависит от окружения
    from winnow.export.xlsx import XLSX_AVAILABLE, result_to_xlsx

    __all__ += ["XLSX_AVAILABLE", "result_to_xlsx"]
except Exception:  # pragma: no cover
    XLSX_AVAILABLE = False
