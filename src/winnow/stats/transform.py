"""Вычисление и перекодирование переменных.

Это подготовка данных - этап, который в реальной работе занимает больше времени,
чем сам анализ. Без него пользователю приходится готовить переменные в Excel и
возвращаться, а это худший сценарий для статистического пакета.

Вычисление использует безопасный вычислитель выражений: выражение разбирается в
дерево, и разрешены только арифметика, сравнения, логика и небольшой набор
функций. Произвольный код выполнить нельзя.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from winnow.core.variable import Measure, VarType
from winnow.stats.command import CommandError, ComputeCommand, RecodeCommand
from winnow.stats.expressions import evaluate
from winnow.stats.result import Column, Result, Table


def _preview(values: pd.Series, limit: int = 5) -> str:
    """Показывает несколько первых значений результата."""
    numbers = pd.to_numeric(values, errors="coerce").dropna()
    if numbers.empty:
        sample = values.dropna().head(limit).astype(str).tolist()
    else:
        sample = [f"{value:.3g}" for value in numbers.head(limit).tolist()]
    return ", ".join(sample) if sample else "нет значений"


def run_compute(command: ComputeCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())

    # Выражение вычисляется на полных данных: новые переменные должны получить
    # значение для каждого кейса, включая те, что исключены отбором.
    variables = {
        name: dataset.frame[name].to_numpy() for name in dataset.names()
    }
    try:
        computed = evaluate(command.expression, variables)
    except CommandError:
        raise
    except Exception as exc:  # noqa: BLE001 - показываем понятный текст
        raise CommandError(f"Не удалось вычислить выражение: {exc}") from exc

    series = _to_series(computed, len(dataset.frame))
    if series is None:
        raise CommandError(
            "Выражение вернуло значение, которое нельзя сохранить как переменную"
        )

    numeric = pd.to_numeric(series, errors="coerce")
    # Бесконечность в результате (например, деление на ноль) статистически
    # бессмысленна, поэтому считаем её пропуском - иначе средние по новой
    # переменной будут равны бесконечности.
    infinite = np.isinf(numeric.to_numpy(dtype=float))
    if infinite.any():
        series = series.mask(infinite)
        numeric = pd.to_numeric(series, errors="coerce")

    successes = int(numeric.notna().sum()) if numeric.notna().any() else int(series.notna().sum())
    failures = int(len(series) - successes)

    if command.target in dataset.variables and command.overwrite:
        dataset.frame[command.target] = series
        variable = dataset.var(command.target)
        variable.var_type = VarType.NUMERIC if numeric.notna().any() else VarType.STRING
        variable.decimals = command.decimals
        if command.label:
            variable.label = command.label
    else:
        dataset.add_variable(command.target, series)
        variable = dataset.var(command.target)
        variable.decimals = command.decimals
        variable.label = command.label or command.expression
        if numeric.notna().any():
            variable.measure = Measure.SCALE

    table = Table(
        title=f"Результат вычисления: {command.target}",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", align="left", is_metric=False),
        ],
        footnotes=[
            "Переменная добавлена в набор данных и доступна всем процедурам.",
            "Если выражение не удалось вычислить для кейса (например, деление на "
            "ноль), значение помечено как пропущенное.",
        ],
    )
    table.add_row(["Выражение", command.expression])
    table.add_row(["Метка", variable.label or "—"])
    table.add_row(["Вычислено значений", str(successes)])
    table.add_row(["Пропущено значений", str(failures)])
    table.add_row(["Примеры значений", _preview(series)])
    result.add_table(table)

    if failures and failures >= len(series):
        result.warn("Выражение не дало ни одного значения - проверьте его правильность")
    elif failures > len(series) * 0.2:
        result.warn(
            f"Пропущено {failures} значений из {len(series)} - проверьте выражение "
            "и пропуски в исходных переменных"
        )
    return result


def _to_series(value: Any, length: int) -> pd.Series | None:
    """Приводит результат выражения к ряду нужной длины."""
    if isinstance(value, pd.Series):
        return value.reset_index(drop=True)
    if np.isscalar(value):
        return pd.Series([value] * length)
    array = np.asarray(value)
    if array.ndim == 0:
        return pd.Series([array.item()] * length)
    if array.ndim != 1 or array.size != length:
        return None
    return pd.Series(array)


def _matches(series: pd.Series, rule, current: pd.Series | None = None) -> np.ndarray:
    """Проверяет, попадает ли значение кейса под правило.

    Для правила «все остальные» нужен текущий результат: оно должно заполнять
    только те кейсы, которые не попали ни под одно предыдущее правило. Без этого
    «все остальные» перекрывало бы уже присвоенные значения, и перекодирование
    молча давало бы неверный результат.
    """
    if rule.kind == "else":
        if current is None:
            return np.ones(len(series), dtype=bool)
        return current.isna().to_numpy()
    if rule.kind == "system_missing":
        return series.isna().to_numpy()
    if rule.kind == "value":
        target = rule.value
        # Сравнение терпимо к типу: «1» и 1 должны совпасть.
        numeric = pd.to_numeric(series, errors="coerce")
        target_number = pd.to_numeric(pd.Series([target]), errors="coerce").iloc[0]
        if pd.notna(target_number) and numeric.notna().any():
            return (numeric == float(target_number)).to_numpy()
        return (series.astype(str) == str(target)).to_numpy()
    if rule.kind == "range":
        numeric = pd.to_numeric(series, errors="coerce")
        # Нижняя граница включается, верхняя - нет: так же, как в SPSS.
        return ((numeric >= rule.low) & (numeric < rule.high)).to_numpy()
    return np.zeros(len(series), dtype=bool)


def apply_recode(series: pd.Series, rules: list) -> pd.Series:
    """Применяет правила перекодирования по порядку.

    Правила применяются последовательно: более позднее правило перекрывает
    более раннее для тех кейсов, которые попали в оба. Это предсказуемо и
    объясняется в подсказке к диалогу.
    """
    result = pd.Series(None, index=series.index, dtype=object)
    for rule in rules:
        mask = _matches(series, rule, result)
        if not mask.any():
            continue
        if rule.new_value is None:
            continue
        result[mask] = rule.new_value
    return result


def run_recode(command: RecodeCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    source_series = dataset.frame[command.source]
    recoded = apply_recode(source_series, command.rules)

    # Определяем тип результата: числа остаются числами, иначе строки.
    numeric = pd.to_numeric(recoded, errors="coerce")
    is_numeric = numeric.notna().sum() >= recoded.notna().sum() * 0.5
    values = numeric if is_numeric else recoded

    converted = int(recoded.notna().sum())
    uncovered = int(recoded.isna().sum() - source_series.isna().sum())

    if command.target in dataset.variables and command.overwrite:
        dataset.frame[command.target] = values
        variable = dataset.var(command.target)
    else:
        dataset.add_variable(command.target, values)
        variable = dataset.var(command.target)

    variable.var_type = VarType.NUMERIC if is_numeric else VarType.STRING
    variable.label = command.label or f"Перекодированная: {dataset.var(command.source).display_name}"
    if is_numeric:
        variable.measure = Measure.SCALE

    # Метки значений собираются из правил: пользователь уже их описал.
    labels: dict[Any, str] = {}
    for rule in command.rules:
        if rule.new_value is None:
            continue
        key = rule.new_value
        if is_numeric:
            try:
                number = float(key)
                key = int(number) if number.is_integer() else number
            except (TypeError, ValueError):
                continue
        if rule.new_label:
            labels[key] = rule.new_label
    if labels:
        variable.value_labels = labels

    table = Table(
        title=f"Результат перекодирования: {command.target}",
        columns=[
            Column("Правило", align="left", is_metric=False),
            Column("Новое значение", decimals=3),
            Column("Кейсов", decimals=0),
        ],
        footnotes=[
            "Правила применяются по порядку: если кейс подходит под несколько, "
            "действует последнее.",
            "В колонке «Кейсов» указано, сколько кейсов попало под правило с "
            "учётом уже присвоенных значений; для правила «все остальные» это "
            "только непокрытые кейсы.",
            "Не подошедшие ни под одно правило кейсы получают пропущенное значение; "
            "для них можно добавить правило «все остальные».",
        ],
    )
    current = pd.Series(None, index=source_series.index, dtype=object)
    for rule in command.rules:
        mask = _matches(source_series, rule, current)
        if rule.new_value is not None:
            current[mask] = rule.new_value
        table.add_row(
            [
                _describe_rule(rule, dataset.var(command.source)),
                rule.new_value,
                int(mask.sum()),
            ]
        )
    result.add_table(table)

    summary = Table(
        title="Сводка по переменным",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Значение", align="left", is_metric=False),
        ],
    )
    summary.add_row(["Исходная переменная", dataset.var(command.source).display_name])
    summary.add_row(["Новая переменная", variable.display_name])
    summary.add_row(["Тип результата", "числовой" if is_numeric else "строковый"])
    summary.add_row(["Получили значение", str(converted)])
    summary.add_row(["Остались без значения", str(uncovered)])
    result.add_table(summary)

    if uncovered > 0:
        result.warn(
            f"{uncovered} кейсов не попали ни под одно правило и получили пропуск. "
            "Добавьте правило «все остальные», если это не задумано."
        )
    if converted == 0:
        result.warn("Ни один кейс не попал под правила - проверьте границы и значения")
    return result


def _describe_rule(rule, source_variable) -> str:
    """Человекочитаемое описание правила для отчёта."""
    if rule.kind == "value":
        return f"{source_variable.label_for(rule.value)} = {rule.new_value}"
    if rule.kind == "range":
        return f"[{rule.low:g}; {rule.high:g}) = {rule.new_value}"
    if rule.kind == "system_missing":
        return f"пропущенные = {rule.new_value}"
    return f"все остальные = {rule.new_value}"


__all__ = ["apply_recode", "run_compute", "run_recode"]
