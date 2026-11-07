"""Веса кейсов: развёртывание данных по весам.

Почему так, а не «взвешенные формулы везде». В SPSS веса — это частотные веса:
случай с весом 3 влияет на результат так же, как три таких случая. Для сумм
квадратов, средних и степеней свободы это в точности совпадает с развёртыванием
набора, поэтому уже выверенные процедуры можно не переписывать: достаточно
подставить развёрнутые данные.

Ограничение честное: SPSS при нецелых весах округляет их для таких процедур,
поэтому и здесь веса округляются. Дробные веса - это уже другой вид взвешивания
(аналитические веса), и для него нужны отдельные формулы.
"""

from __future__ import annotations

import numpy as np

from winnow.core.dataset import Dataset


def expansion_counts(dataset: Dataset) -> np.ndarray | None:
    """Сколько раз повторить каждую строку. None - веса не заданы."""
    values = dataset.weight_values()
    if values is None:
        return None
    weights = np.asarray(values, dtype=float)
    if weights.size != len(dataset.frame):
        return None
    # Пропуск в весе означает «не учитывать строку»; отрицательные невозможны.
    weights = np.where(np.isfinite(weights), weights, 0.0)
    return np.clip(np.rint(weights), 0, None).astype(int)


def expand_by_weights(dataset: Dataset) -> Dataset:
    """Возвращает набор, где каждая строка повторена по своему весу.

    Паспорт переменных (метки, уровни измерения, метки значений, пропуски)
    переносится: без него отчёт потерял бы названия переменных.
    """
    counts = expansion_counts(dataset)
    if counts is None or counts.sum() == 0:
        return dataset

    frame = dataset.frame
    index = np.repeat(np.arange(len(frame)), counts)
    expanded = frame.iloc[index].reset_index(drop=True)
    result = Dataset.from_dataframe(expanded, name=dataset.name)

    for name in dataset.names():
        if name not in result.names():
            continue
        variable = dataset.var(name)
        try:
            result.set_label(name, variable.label)
            result.set_measure(name, variable.measure)
            result.set_value_labels(name, dict(variable.value_labels))
            result.set_missing(name, variable.missing)
        except (AttributeError, TypeError, ValueError):
            # Паспорт не перенёсся - это не повод падать: числа важнее меток.
            continue
    return result


__all__ = ["expand_by_weights", "expansion_counts"]
