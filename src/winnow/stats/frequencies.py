"""Частоты.

Простейшая процедура и одновременно витрина продукта: пользователь судит о
статистическом пакете по тому, насколько понятна его самая первая таблица.
Поэтому здесь есть и метки значений, и раздельные проценты (от всех / от
валидных), и накопительный процент.
"""

from __future__ import annotations

from typing import Any

from winnow.stats import interpretation
from winnow.stats.command import CommandError, FrequenciesCommand
from winnow.stats.common import category_label, ordered_categories, percent_value
from winnow.stats.result import Column, Result, Table

# Подписи для запрашиваемых статистик частотных распределений.
FREQ_STATISTICS: dict[str, str] = {
    "mean": "Среднее",
    "median": "Медиана",
    "mode": "Мода",
    "std": "Стд. отклонение",
    "variance": "Дисперсия",
    "range": "Размах",
    "min": "Минимум",
    "max": "Максимум",
    "sum": "Сумма",
    "skewness": "Асимметрия",
    "kurtosis": "Эксцесс",
}


def run(command: FrequenciesCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    if dataset.weight_values() is not None:
        result.note(f"Учтены веса кейсов: {dataset.weight_var}")

    for name in command.variables:
        variable = dataset.var(name)
        series = dataset.categorical_series(name)
        total = int(len(series))
        valid_series = series.dropna()
        n_valid = int(len(valid_series))
        n_missing = total - n_valid

        result.add_table(_case_summary_table(variable.display_name, n_valid, n_missing, total))

        categories = ordered_categories(valid_series, variable.value_labels)
        if not categories:
            result.warn(f"Переменная {variable.display_name}: нет валидных значений")
            continue

        counts = valid_series.value_counts()
        cumulative = 0
        rows: list[list[Any]] = []

        for value in categories:
            frequency = int(counts.get(value, 0))
            cumulative += frequency
            row: list[Any] = [category_label(value, variable.value_labels)]
            if command.show_counts:
                row.append(frequency)
            if command.show_percent:
                row.append(percent_value(frequency, total))
            if command.show_valid_percent:
                row.append(percent_value(frequency, n_valid))
            if command.show_cumulative:
                row.append(percent_value(cumulative, n_valid))
            rows.append(row)

        # Итоговая строка: "Всего" - привычный элемент отчёта.
        total_row: list[Any] = ["Всего"]
        if command.show_counts:
            total_row.append(n_valid)
        if command.show_percent:
            total_row.append(percent_value(n_valid, total))
        if command.show_valid_percent:
            total_row.append(100.0 if n_valid else None)
        if command.show_cumulative:
            total_row.append(100.0 if n_valid else None)
        rows.append(total_row)

        columns = [Column(variable.display_name, align="left", is_metric=False)]
        if command.show_counts:
            columns.append(Column("Частота", decimals=0))
        if command.show_percent:
            columns.append(Column("Процент", decimals=1, suffix="%"))
        if command.show_valid_percent:
            columns.append(Column("Валидный процент", decimals=1, suffix="%"))
        if command.show_cumulative:
            columns.append(Column("Накопленный процент", decimals=1, suffix="%"))

        table = Table(title=f"Частоты: {variable.display_name}", columns=columns, rows=rows)
        if n_missing:
            table.footnote(f"Пропущено значений: {n_missing}")
        result.add_table(table)

        # Вывод «простыми словами»: таблица частот отвечает на вопрос «сколько
        # кого», но не говорит, что из этого следует.
        result.add_findings(
            interpretation.describe_categories(
                name=variable.label or name,
                items=[
                    (category_label(value, variable.value_labels), int(counts.get(value, 0)))
                    for value in categories
                ],
                n_valid=n_valid,
                n_missing=n_missing,
            )
        )

        if command.statistics and variable.is_numeric:
            _add_statistics_table(result, dataset, command, variable.display_name)

    return result


def _case_summary_table(name: str, n_valid: int, n_missing: int, total: int) -> Table:
    table = Table(
        title=f"Сводка по обработке наблюдений: {name}",
        columns=[
            Column("", align="left", is_metric=False),
            Column("N", decimals=0),
            Column("Процент", decimals=1, suffix="%"),
        ],
    )
    table.add_row(["Валидные", n_valid, percent_value(n_valid, total)])
    table.add_row(["Пропущенные", n_missing, percent_value(n_missing, total)])
    table.add_row(["Всего", total, 100.0 if total else None])
    return table


def _add_statistics_table(result: Result, dataset, command: FrequenciesCommand, name: str) -> None:
    import numpy as np
    from scipy import stats as sps

    from winnow.stats.common import valid_values

    series = dataset.analysis_series(name)
    values = valid_values(series)
    if values.size == 0:
        return

    # Одна колонка "Значение" с общей точностью: Table намеренно не поддерживает
    # разную точность внутри колонки - смешение форматов в одной колонке читается
    # как ошибка вывода, а не как забота о пользователе.
    table = Table(
        title=f"Статистики: {name}",
        columns=[
            Column("Статистика", align="left", is_metric=False),
            Column("Значение", decimals=2),
        ],
    )
    computed: dict[str, float] = {
        "mean": float(np.mean(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "range": float(np.max(values) - np.min(values)),
        "sum": float(np.sum(values)),
    }
    if values.size > 1:
        computed["std"] = float(np.std(values, ddof=1))
        computed["variance"] = float(np.var(values, ddof=1))
        computed["median"] = float(np.median(values))
    if values.size > 2:
        computed["skewness"] = float(sps.skew(values, bias=False))
    if values.size > 3:
        computed["kurtosis"] = float(sps.kurtosis(values, bias=False))

    table.add_row(["N валидных", float(values.size)])
    for key in command.statistics:
        if key == "n":
            table.add_row([FREQ_STATISTICS.get(key, key), float(values.size)])
        elif key == "missing":
            table.add_row([FREQ_STATISTICS.get(key, key), float(series.isna().sum())])
        else:
            table.add_row([FREQ_STATISTICS.get(key, key), computed.get(key)])
    result.add_table(table)


__all__ = ["FREQ_STATISTICS", "run"]
