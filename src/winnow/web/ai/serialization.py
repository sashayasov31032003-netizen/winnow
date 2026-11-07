"""Превращение результата движка в JSON — для модели, отчётов и API.

Движок сознательно не знает про ИИ и про JSON: он отдаёт `Result` с таблицами.
Здесь этот результат становится данными, которые можно сохранить в
`analysis_runs`, показать в интерфейсе и передать модели. Один сериализатор на
все случаи — иначе модель, отчёт и экран начнут видеть разные числа.
"""

from __future__ import annotations

import math
from typing import Any

from winnow.stats.result import Column, Result, Table

#: Сколько строк и колонок отдавать модели. Полные таблицы остаются в
#: сохранённом расчёте и показываются интерфейсом.
MODEL_MAX_TABLES = 8
MODEL_MAX_ROWS = 25
MODEL_MAX_COLUMNS = 12


def json_safe(value: Any) -> Any:
    """Готовит значение к JSON: NaN и бесконечность не сериализуются."""
    if value is None:
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):  # numpy-скаляры
        try:
            return json_safe(value.item())
        except (ValueError, AttributeError):
            return str(value)
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _column(column: Column) -> dict[str, Any]:
    return {
        "label": column.label,
        "key": column.key,
        "align": column.align,
        "decimals": column.decimals,
        "suffix": column.suffix,
        "is_metric": column.is_metric,
    }


def _table(table: Table) -> dict[str, Any]:
    return {
        "title": table.title,
        "number": table.number,
        "columns": [_column(column) for column in table.columns],
        "rows": [[json_safe(value) for value in row] for row in table.rows],
        "footnotes": list(table.footnotes),
    }


def result_payload(
    result: Result,
    *,
    procedure: str,
    params: dict[str, Any] | None = None,
    dataset_name: str = "",
    dataset_revision: str = "",
    n_cases: int = 0,
    run_id: int | None = None,
    duration_ms: int = 0,
) -> dict[str, Any]:
    """Полное представление результата: его сохраняем и показываем."""
    created = getattr(result, "created", None)
    return {
        "run_id": run_id,
        "procedure": procedure,
        "title": result.title or procedure,
        "dataset": {
            "name": dataset_name,
            "revision": dataset_revision,
            "n_cases": int(n_cases),
        },
        "params": dict(params or {}),
        "duration_ms": int(duration_ms),
        "created": created.isoformat() if hasattr(created, "isoformat") else "",
        "tables": [_table(table) for table in result.tables],
        "findings": [
            {
                "kind": finding.kind,
                "text": finding.text,
                "source": finding.source,
                "group": finding.group,
            }
            for finding in result.findings
        ],
        "warnings": list(result.warnings),
        "notes": list(result.notes),
        "syntax": result.syntax,
    }


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Версия для модели: те же числа, но без бесконечных таблиц.

    Модели не нужны все 200 строк частотной таблицы: ей нужны заголовки,
    ключевые строки и выводы. Полный результат доступен по run_id, а
    интерфейс показывает его целиком.
    """
    tables: list[dict[str, Any]] = []
    for table in payload.get("tables", [])[:MODEL_MAX_TABLES]:
        columns = table.get("columns", [])[:MODEL_MAX_COLUMNS]
        rows = table.get("rows", [])
        trimmed = rows[:MODEL_MAX_ROWS]
        entry = {
            "title": table.get("title", ""),
            "columns": [column.get("label", "") for column in columns],
            "rows": [row[:MODEL_MAX_COLUMNS] for row in trimmed],
        }
        if len(rows) > len(trimmed):
            entry["rows_truncated"] = len(rows) - len(trimmed)
        if len(table.get("columns", [])) > len(columns):
            entry["columns_truncated"] = len(table.get("columns", [])) - len(columns)
        if table.get("footnotes"):
            entry["footnotes"] = list(table["footnotes"])
        tables.append(entry)

    result = {
        "run_id": payload.get("run_id"),
        "procedure": payload.get("procedure"),
        "title": payload.get("title"),
        "dataset": payload.get("dataset"),
        "tables": tables,
        "findings": payload.get("findings", []),
        "warnings": payload.get("warnings", []),
        "notes": payload.get("notes", []),
    }
    if len(payload.get("tables", [])) > len(tables):
        result["tables_truncated"] = len(payload["tables"]) - len(tables)
    return result


def run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Короткая карточка расчёта для интерфейса и событий SSE."""
    return {
        "run_id": payload.get("run_id"),
        "procedure": payload.get("procedure"),
        "title": payload.get("title"),
        "n_tables": len(payload.get("tables", [])),
        "n_findings": len(payload.get("findings", [])),
        "warnings": payload.get("warnings", []),
        "dataset": payload.get("dataset", {}),
    }


__all__ = [
    "MODEL_MAX_COLUMNS",
    "MODEL_MAX_ROWS",
    "MODEL_MAX_TABLES",
    "compact_payload",
    "json_safe",
    "result_payload",
    "run_summary",
]
