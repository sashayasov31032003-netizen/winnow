"""Таблицы сопряжённости и хи-квадрат.

Процедура специально сделана "эталонной": она прогоняет весь путь от задачи до
отчёта (таблица -> проверка значимости -> меры связи -> предупреждения) и служит
шаблоном для остальных процедур.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.core.dataset import Dataset
from winnow.core.formatting import fmt_int
from winnow.stats import interpretation
from winnow.stats.multianswer import _cells, _split_cell, detect_column
from winnow.stats.command import CommandError, CrosstabsCommand
from winnow.stats.common import category_label, ordered_categories, percent, percent_value
from winnow.stats.result import Column, Result, Table


def compute_independence(table: np.ndarray, chi_square_ok: bool) -> dict[str, Any]:
    """Хи-квадрат Пирсона, отношение правдоподобия и меры связи.

    Знаменатель для Cramér's V - это min(R-1, C-1), а не R-1: для таблиц, где
    строк больше, чем столбцов, это даёт другую (правильную) оценку.
    """
    table = np.asarray(table, dtype=float)
    rows, cols = table.shape
    n = float(table.sum())
    out: dict[str, Any] = {
        "n": n,
        "df": (rows - 1) * (cols - 1),
        "value": float("nan"),
        "p": float("nan"),
        "lr_value": float("nan"),
        "lr_p": float("nan"),
        "fisher_p": None,
        "min_expected": float("nan"),
        "small_expected_share": 0.0,
        "n_small_expected": 0,
        "cramers_v": None,
        "contingency": None,
        "phi": None,
        "n_cells": rows * cols,
    }

    if n <= 0 or rows < 2 or cols < 2:
        return out

    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / n
    out["min_expected"] = float(expected.min())
    below_five = expected < 5
    out["n_small_expected"] = int(below_five.sum())
    out["small_expected_share"] = float(below_five.mean())

    # Знаменатель Cramér's V: (N * min(R-1, C-1)).
    denom = n * min(rows - 1, cols - 1)

    if chi_square_ok and not np.isclose(expected, 0).any():
        chi2_value = float(np.sum((table - expected) ** 2 / expected))
        out["value"] = chi2_value
        out["p"] = float(sps.chi2.sf(chi2_value, out["df"]))
        if denom > 0:
            out["cramers_v"] = float(math.sqrt(chi2_value / denom))
            out["contingency"] = float(math.sqrt(chi2_value / (chi2_value + n)))
            if min(rows, cols) == 2:
                out["phi"] = float(math.sqrt(chi2_value / n))

    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(table > 0, table * np.log(table / expected), 0.0)
    if chi_square_ok and np.isfinite(terms).all():
        lr_value = float(2.0 * terms.sum())
        out["lr_value"] = lr_value
        out["lr_p"] = float(sps.chi2.sf(lr_value, out["df"]))

    if rows == 2 and cols == 2:
        try:
            out["fisher_p"] = float(sps.fisher_exact(table.astype(int))[1])
        except ValueError:
            out["fisher_p"] = None

    return out


def _cross_table(
    dataset, row_var: str, col_var: str
) -> tuple[np.ndarray, list[Any], list[Any], int, int]:
    """Строит матрицу наблюдаемых частот и списки категорий."""
    row_meta = dataset.var(row_var)
    col_meta = dataset.var(col_var)
    frame = dataset.analysis_frame([row_var, col_var])

    rows = ordered_categories(frame[row_var], row_meta.value_labels)
    cols = ordered_categories(frame[col_var], col_meta.value_labels)

    row_index = {value: i for i, value in enumerate(rows)}
    col_index = {value: i for i, value in enumerate(cols)}

    matrix = np.zeros((len(rows), len(cols)), dtype=float)
    valid = frame.dropna(subset=[row_var, col_var])
    for row_value, col_value in zip(valid[row_var], valid[col_var]):
        matrix[row_index[row_value], col_index[col_value]] += 1.0

    n_valid = int(matrix.sum())
    n_missing = int(len(frame) - n_valid)
    return matrix, rows, cols, n_valid, n_missing


def _cell_text(
    count: float,
    row_total: float,
    col_total: float,
    total: float,
    command: CrosstabsCommand,
    expected: float,
    residual: float,
) -> str:
    """Содержимое ячейки: количество, проценты, ожидаемая частота, остаток."""
    lines = [str(int(round(count)))] if command.count else []
    if command.row_percent:
        lines.append(percent(count, row_total, 1))
    if command.col_percent:
        lines.append(percent(count, col_total, 1))
    if command.total_percent:
        lines.append(percent(count, total, 1))
    if command.expected:
        lines.append(f"ожид. {expected:.1f}")
    if command.residuals:
        lines.append(f"ост. {residual:+.1f}")
    return "\n".join(lines) if lines else str(int(round(count)))


def _crosstab_table(
    dataset,
    command: CrosstabsCommand,
    row_var: str,
    col_var: str,
    matrix: np.ndarray,
    rows: list[Any],
    cols: list[Any],
    n_valid: int,
) -> Table:
    row_meta = dataset.var(row_var)
    col_meta = dataset.var(col_var)
    total = float(matrix.sum())

    expected = np.zeros_like(matrix)
    if total > 0 and matrix.shape[0] > 1 and matrix.shape[1] > 1:
        expected = np.outer(matrix.sum(axis=1), matrix.sum(axis=0)) / total

    columns = [
        Column(
            f"{row_meta.display_name} \\ {col_meta.display_name}",
            align="left",
            is_metric=False,
        )
    ]
    columns += [Column(category_label(c, col_meta.value_labels), decimals=1) for c in cols]
    columns.append(Column("Всего", decimals=1))

    table = Table(title="Таблица сопряжённости", columns=columns)

    for i, row_value in enumerate(rows):
        row_total = float(matrix[i, :].sum())
        cells: list[Any] = [category_label(row_value, row_meta.value_labels)]
        for j in range(len(cols)):
            cells.append(
                _cell_text(
                    matrix[i, j],
                    row_total,
                    float(matrix[:, j].sum()),
                    total,
                    command,
                    expected[i, j],
                    matrix[i, j] - expected[i, j],
                )
                if total
                else "."
            )
        cells.append(
            _cell_text(row_total, row_total, row_total, total, command, row_total, 0.0)
            if total
            else "."
        )
        table.add_row(cells)

    # Итоговая строка по столбцам.
    totals: list[Any] = ["Всего"]
    for j in range(len(cols)):
        col_total = float(matrix[:, j].sum())
        totals.append(
            _cell_text(col_total, col_total, col_total, total, command, col_total, 0.0)
            if total
            else "."
        )
    totals.append(
        str(int(round(total))) + ("\n100.0%" if command.count and command.total_percent else "")
    )
    table.add_row(totals)

    parts = []
    if command.count:
        parts.append("количество")
    if command.row_percent:
        parts.append("процент по строке")
    if command.col_percent:
        parts.append("процент по столбцу")
    if command.total_percent:
        parts.append("процент от общего итога")
    if command.expected:
        parts.append("ожидаемая частота")
    if command.residuals:
        parts.append("остаток")
    table.footnote("В ячейках: " + ", ".join(parts) + ".")
    return table


def _case_summary(row_var: str, col_var: str, n_valid: int, n_missing: int) -> Table:
    total = n_valid + n_missing
    table = Table(
        title="Сводка по обработке наблюдений",
        columns=[
            Column("", align="left", is_metric=False),
            Column("N", decimals=0),
            Column("Процент", decimals=1, suffix="%"),
        ],
        footnotes=[f"Переменные: {row_var} x {col_var}"],
    )
    table.add_row(["Валидные", n_valid, percent_value(n_valid, total)])
    table.add_row(["Пропущенные", n_missing, percent_value(n_missing, total)])
    table.add_row(["Всего", total, 100.0 if total else None])
    return table


def _chi_square_tables(values: dict[str, Any]) -> list[Table]:
    tables: list[Table] = []

    chi_table = Table(
        title="Критерии хи-квадрат",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Значение", decimals=3),
            Column("ст. св.", decimals=0),
            Column("Асимпт. знач. (2-стор.)", decimals=3),
        ],
    )
    chi_table.add_row(["Хи-квадрат Пирсона", values["value"], values["df"], values["p"]])
    chi_table.add_row(["Отношение правдоподобия", values["lr_value"], values["df"], values["lr_p"]])
    # N - счётчик, а не метрика: он печатается строкой, иначе выходит "200.000".
    chi_table.add_row(["N валидных наблюдений", fmt_int(values["n"]), None, None])

    n_cells = values["n_cells"]
    small = values["n_small_expected"]
    if n_cells:
        chi_table.footnote(
            f"В {small} ячейках ({100.0 * small / n_cells:.1f}%) ожидаемая частота меньше 5. "
            f"Минимальная ожидаемая частота: {values['min_expected']:.2f}."
        )
    if n_cells and small / n_cells > 0.2:
        chi_table.footnote(
            "ВНИМАНИЕ: более 20% ячеек имеют ожидаемую частоту меньше 5 - "
            "результат хи-квадрата может быть недостоверным."
        )

    if values["fisher_p"] is not None:
        fisher = Table(
            title="Точный критерий Фишера (таблица 2x2)",
            columns=[
                Column("", align="left", is_metric=False),
                Column("Значение", decimals=3),
                Column("Точная знач. (2-стор.)", decimals=3),
            ],
        )
        fisher.add_row(["Точный критерий Фишера", None, values["fisher_p"]])
        fisher.footnote("Вычислен только для таблиц 2x2.")
        tables.append(fisher)

    tables.append(chi_table)
    return tables


def _symmetric_measures(values: dict[str, Any]) -> Table | None:
    rows = []
    if values.get("phi") is not None:
        rows.append(["Фи (Phi)", values["phi"], values["p"]])
    if values.get("cramers_v") is not None:
        rows.append(["V Крамера", values["cramers_v"], values["p"]])
    if values.get("contingency") is not None:
        rows.append(["Коэффициент сопряжённости", values["contingency"], values["p"]])
    if not rows:
        return None

    table = Table(
        title="Симметричные меры",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Значение", decimals=3),
            Column("Прибл. знач.", decimals=3),
        ],
        rows=rows,
    )
    table.footnote("Для номинальных переменных: Фи и V Крамера. Значимость дана по хи-квадрату.")
    return table


def _multi_answer_table(dataset: Dataset, item, col_var: str) -> Table | None:
    """Таблица «вариант ответа x группа» для вопроса с несколькими ответами.

    Каждая строка - вариант ответа, каждый столбец - группа (например, пол), в
    ячейке - сколько человек из этой группы вариант выбрали. Один человек может
    попасть в несколько строк: он ведь мог выбрать несколько вариантов, и это
    нормально для такого вопроса.
    """
    variable = dataset.var(col_var)
    frame = dataset.analysis_frame([item.name, col_var])
    cells = _cells(frame[item.name])
    groups = frame[col_var]

    categories = ordered_categories(groups.dropna(), variable.value_labels)
    if len(categories) < 2:
        return None
    labels = [category_label(value, variable.value_labels) for value in categories]

    rows: list[list[object]] = []
    for option in item.options:
        chosen = cells.map(
            lambda value, target=option: pd.notna(value) and target in _split_cell(value)
        )
        counts = [int((chosen & (groups == value)).sum()) for value in categories]
        rows.append([option, *counts, sum(counts)])

    totals = ["Всего выборов"]
    totals += [sum(int(row[index + 1]) for row in rows) for index in range(len(categories))]
    totals.append(sum(int(row[-1]) for row in rows))
    rows.append(totals)

    columns = [Column("Вариант ответа", align="left", is_metric=False)]
    columns += [Column(label, decimals=0) for label in labels]
    columns.append(Column("Всего", decimals=0))
    table = Table(
        title=f"Выбор вариантов: {dataset.var(item.name).display_name} x {variable.display_name}",
        columns=columns,
        rows=rows,
    )
    table.footnote(
        "Один человек мог выбрать несколько вариантов, поэтому сумма по столбцу "
        "больше числа людей в группе. В ячейках - число выбравших вариант, а не "
        "проценты: группы разного размера, и сравнивать по числам проще."
    )
    return table


def _multi_answer_findings(dataset: Dataset, item, col_var: str, table: Table):
    """Вывод простыми словами: что чаще выбирают в каждой группе."""
    labels = [column.label for column in table.columns[1:-1]]
    findings: list[tuple[str, str]] = []
    leaders: list[str] = []
    for index, label in enumerate(labels):
        column_values = [int(row[index + 1]) for row in table.rows[:-1]]
        if not column_values or max(column_values) == 0:
            continue
        best = max(range(len(column_values)), key=lambda position: column_values[position])
        leaders.append(
            f"«{label}» — «{table.rows[best][0]}» ({column_values[best]} выборов)"
        )
    if leaders:
        findings.append(
            (
                "conclusion",
                "Чаще всего выбирают: " + "; ".join(leaders) + ".",
            )
        )
    findings.append(
        (
            "note",
            "Вопрос допускает несколько ответов, поэтому проценты считаются от "
            "числа людей в группе, а сумма по столбцу может быть больше ста.",
        )
    )
    return findings


def run(command: CrosstabsCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    if dataset.weight_values() is not None:
        result.note(f"Учтены веса кейсов: {dataset.weight_var}")

    # Когда пар «строка x столбец» несколько, каждая - отдельный анализ со своими
    # выводами. Без заголовка отчёт читается как один анализ с противоречивыми
    # выводами, поэтому пары разделяются подзаголовком.
    multiple_pairs = len(command.row_vars) * len(command.col_vars) > 1

    for row_var in command.row_vars:
        for col_var in command.col_vars:
            pair_title = (
                f"{dataset.var(row_var).display_name} x "
                f"{dataset.var(col_var).display_name}"
            )
            if multiple_pairs:
                result.add_table(Table(title=pair_title))
            # Все выводы этой пары получают её метку: в отчёте с несколькими
            # парами видно, какой вывод к какому анализу относится.
            result._group = pair_title if multiple_pairs else ""
            # Вопрос с несколькими ответами: варианты склеены в одной ячейке, и
            # обычная таблица сопряжённости по нему бессмысленна (десятки
            # уникальных строк). По нему строится таблица «вариант x группа» -
            # ровно то, что нужно, чтобы увидеть, сколько мужчин выбрало каждый
            # вариант.
            multi = detect_column(dataset, row_var)
            if multi is not None:
                table = _multi_answer_table(dataset, multi, col_var)
                if table is None:
                    result.warn(
                        f"{multi.label} x {col_var}: нужно хотя бы две группы, "
                        "чтобы сравнить варианты ответа"
                    )
                    continue
                result.add_table(table)
                result.add_findings(
                    _multi_answer_findings(dataset, multi, col_var, table)
                )
                continue

            matrix, rows, cols, n_valid, n_missing = _cross_table(dataset, row_var, col_var)

            result.add_table(_case_summary(row_var, col_var, n_valid, n_missing))

            if n_valid == 0 or len(rows) == 0 or len(cols) == 0:
                result.warn(
                    f"{row_var} x {col_var}: нет валидных наблюдений для построения таблицы"
                )
                continue
            degenerate = len(rows) < 2 or len(cols) < 2
            if degenerate:
                result.warn(
                    f"{row_var} x {col_var}: таблица вырождена (одна категория) - "
                    "хи-квадрат не вычисляется"
                )

            result.add_table(
                _crosstab_table(dataset, command, row_var, col_var, matrix, rows, cols, n_valid)
            )

            if command.chi_square:
                values = compute_independence(matrix, chi_square_ok=not degenerate)
                for table in _chi_square_tables(values):
                    result.add_table(table)
                if command.phi_cramers_v:
                    measures = _symmetric_measures(values)
                    if measures is not None:
                        result.add_table(measures)
                # Вывод «простыми словами»: связаны ли признаки на самом деле.
                # Хи-квадрат показывает значимость, V Крамера - силу связи, а
                # человеку нужен ответ на вопрос «связаны или нет».
                p_value = values.get("p")
                strength = values.get("cramers_v")
                if not degenerate and p_value is not None:
                    # В человеческой фразе нужно название переменной без
                    # технического имени в скобках: «Пол респондента», а не
                    # «Пол респондента [gender]».
                    first_label = dataset.var(row_var).label or row_var
                    second_label = dataset.var(col_var).label or col_var
                    result.add_findings(
                        interpretation.association(
                            first=first_label,
                            second=second_label,
                            p_value=float(p_value),
                            cramers_v=float(strength) if strength is not None else None,
                            n=int(n_valid),
                            has_small_expected=bool(values.get("n_small_expected")),
                        )
                    )

    if result.is_empty:
        result.warn("Ни одной таблицы не построено")
    return result


__all__ = ["compute_independence", "run"]
