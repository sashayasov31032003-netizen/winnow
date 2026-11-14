"""Структурированный результат статистической процедуры.

Контракт: движок НИКОГДА не возвращает готовый текст. Он возвращает дерево
объектов Table/Result, а рендеринг в Qt-Viewer, DOCX, XLSX или HTML - задача
отдельного слоя (winnow.export). Без этого разделения добавление нового
формата экспорта превращается в переписывание всех процедур.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from winnow.core.formatting import num


def _json_value(value: Any) -> Any:
    """Приводит значение ячейки к JSON-совместимому виду."""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


@dataclass
class Column:
    """Колонка таблицы.

    align/decimals/suffix - подсказки для рендерера, а не разметка. Процедура
    отдаёт голое число, а знак процента или иное обозначение добавляет слой
    вывода - иначе в Excel вместо числа окажется строка "25.0%".
    """

    label: str
    key: str = ""
    align: str = "right"  # "left" | "right" | "center"
    decimals: int | None = None
    is_metric: bool = True
    suffix: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            self.key = self.label


@dataclass
class Table:
    """Одна таблица вывода (в терминах SPSS - одна "таблица результатов")."""

    title: str
    columns: list[Column] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    # Номер таблицы в отчёте: "Таблица 1".
    number: int | None = None

    def add_row(self, values: list[Any]) -> None:
        if self.columns and len(values) != len(self.columns):
            raise ValueError(
                f"Строка содержит {len(values)} ячеек, а колонок {len(self.columns)}: {values!r}"
            )
        self.rows.append(list(values))

    def footnote(self, text: str) -> None:
        if text not in self.footnotes:
            self.footnotes.append(text)

    @property
    def caption(self) -> str:
        return f"Таблица {self.number}. {self.title}" if self.number else self.title

    def iter_values(self) -> Iterator[Any]:
        for row in self.rows:
            yield from row


@dataclass
class Finding:
    """Фраза «простыми словами» - то, что следует из чисел отчёта.

    Зачем отдельный вид данных. Отчёт показывает «t = -2,695, p = 0,008,
    d = -0,38». Опытный исследователь прочитает это сразу, начинающий видит набор
    чисел и не понимает, что из них следует. А нужен именно вывод: значима ли
    разница, в какую сторону, велика ли она.

    Формулировку строит процедура, которая посчитала числа (формулировки живут в
    модуле `interpretation`), а как показать - решает рендерер. Поэтому Finding
    хранит вид и текст, но не разметку.
    """

    kind: str  # "conclusion" - вывод, "caution" - предупреждение, "note" - пояснение
    text: str
    #: Имя процедуры-источника: по нему видно, к какому отчёту относится вывод.
    source: str = ""
    #: Группа вывода, если в одном отчёте несколько независимых анализов:
    #: например «статус x пол». Пустая строка - вывод общий для отчёта.
    group: str = ""

    @property
    def is_conclusion(self) -> bool:
        return self.kind == "conclusion"

    @property
    def is_caution(self) -> bool:
        return self.kind == "caution"


@dataclass
class Result:
    """Результат выполнения одной процедуры: несколько таблиц плюс замечания."""

    procedure: str
    title: str = ""
    tables: list[Table] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    syntax: str = ""
    created: _dt.datetime = field(default_factory=_dt.datetime.now)
    meta: dict[str, Any] = field(default_factory=dict)
    #: Выводы «простыми словами»: показываются в начале отчёта.
    findings: list[Finding] = field(default_factory=list)

    def add_table(self, table: Table) -> Table:
        """Добавляет таблицу и присваивает сквозной номер.

        Таблица без колонок - это заголовок группы (при разбиении файла или при
        нескольких парах переменных), а не таблица данных. Номер она не занимает,
        иначе нумерация в отчёте прыгает: после «Таблица 5» идёт «Таблица 7».
        """
        if table.columns:
            table.number = sum(1 for item in self.tables if item.columns) + 1
        self.tables.append(table)
        return table

    def conclude(self, text: str) -> Finding:
        """Добавляет вывод - главное, что следует из отчёта."""
        return self._add_finding("conclusion", text)

    def caution(self, text: str) -> Finding:
        """Добавляет предупреждение о применимости или трактовке."""
        return self._add_finding("caution", text)

    def explain(self, text: str) -> Finding:
        """Добавляет пояснение, которое помогает прочитать отчёт."""
        return self._add_finding("note", text)

    def add_findings(self, findings: Iterable[tuple[str, str]]) -> None:
        """Добавляет готовые выводы, построенные модулем `interpretation`.

        Процедура передаёт пары «вид, текст»: формулировки живут в одном месте,
        а вид и порядок определяет процедура, которая знает свой отчёт.
        """
        for kind, text in findings:
            self._add_finding(kind, text)

    def _add_finding(self, kind: str, text: str) -> Finding:
        finding = Finding(
            kind=kind,
            text=text,
            source=self.procedure,
            group=getattr(self, "_group", ""),
        )
        if finding.text not in [item.text for item in self.findings]:
            self.findings.append(finding)
        return finding

    @property
    def conclusions(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.is_conclusion]

    def table(self, title: str) -> Table:
        return self.add_table(Table(title=title))

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    @property
    def is_empty(self) -> bool:
        return not self.tables

    def as_payload(self) -> dict[str, Any]:
        """Сериализует результат для сохранения рядом с JSON-отчётом.

        Нужен Stress Test: отчёт уже посчитан и сохранён, а экспорт в Word/Excel
        не должен пересчитывать модель заново.
        """
        return {
            "procedure": self.procedure,
            "title": self.title,
            "warnings": list(self.warnings),
            "notes": list(self.notes),
            "findings": [
                {
                    "kind": item.kind,
                    "text": item.text,
                    "source": item.source,
                    "group": item.group,
                }
                for item in self.findings
            ],
            "tables": [
                {
                    "title": table.title,
                    "number": table.number,
                    "footnotes": list(table.footnotes),
                    "columns": [
                        {
                            "label": column.label,
                            "key": column.key,
                            "align": column.align,
                            "decimals": column.decimals,
                            "is_metric": column.is_metric,
                            "suffix": column.suffix,
                        }
                        for column in table.columns
                    ],
                    "rows": [
                        [_json_value(value) for value in row] for row in table.rows
                    ],
                }
                for table in self.tables
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Result:
        """Восстанавливает Result из `as_payload`."""
        tables: list[Table] = []
        for raw_table in payload.get("tables", []):
            columns = [
                Column(
                    label=str(column.get("label", "")),
                    key=str(column.get("key", "")),
                    align=str(column.get("align", "right")),
                    decimals=column.get("decimals"),
                    is_metric=bool(column.get("is_metric", True)),
                    suffix=str(column.get("suffix", "")),
                )
                for column in raw_table.get("columns", [])
            ]
            table = Table(
                title=str(raw_table.get("title", "")),
                columns=columns,
                rows=[list(row) for row in raw_table.get("rows", [])],
                footnotes=[str(item) for item in raw_table.get("footnotes", [])],
                number=raw_table.get("number"),
            )
            tables.append(table)
        findings = [
            Finding(
                kind=str(item.get("kind", "note")),
                text=str(item.get("text", "")),
                source=str(item.get("source", "")),
                group=str(item.get("group", "")),
            )
            for item in payload.get("findings", [])
        ]
        return cls(
            procedure=str(payload.get("procedure", "")),
            title=str(payload.get("title", "")),
            tables=tables,
            warnings=[str(item) for item in payload.get("warnings", [])],
            notes=[str(item) for item in payload.get("notes", [])],
            findings=findings,
        )

    def to_text(self) -> str:
        """Простое текстовое представление - для консоли, логов и тестов."""
        lines: list[str] = []
        if self.title:
            lines.append(self.title)
        # Выводы «простыми словами» идут первыми: в консоли это единственное
        # место, где пользователь читает смысл, а не числа.
        if self.findings:
            lines.append("")
            lines.append("Простыми словами:")
            for finding in self.findings:
                mark = {"conclusion": "Вывод", "caution": "Внимание", "note": "Пояснение"}.get(
                    finding.kind, ""
                )
                lines.append(f"  {mark}. {finding.text}" if mark else f"  {finding.text}")
        for table in self.tables:
            lines.append("")
            lines.append(table.caption)
            if table.columns:
                header = [c.label for c in table.columns]
                lines.append(" | ".join(header))
                lines.append("-" * max(8, sum(len(h) + 3 for h in header)))
            for row in table.rows:
                cells = []
                for column, value in zip(table.columns, row):
                    if isinstance(value, float):
                        cells.append(num(value, column.decimals) + column.suffix)
                    elif value is None:
                        cells.append(".")
                    else:
                        cells.append(str(value))
                lines.append(" | ".join(cells))
            for note in table.footnotes:
                lines.append(f"  {note}")
        for warning in self.warnings:
            lines.append(f"! {warning}")
        for note in self.notes:
            lines.append(f"  {note}")
        return "\n".join(lines)


__all__ = ["Column", "Result", "Table"]
