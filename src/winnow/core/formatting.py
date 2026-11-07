"""Числовое форматирование для таблиц вывода.

Отдельный модуль, потому что правила отображения чисел - это часть контракта
вывода: SPSS-подобные таблицы печатают "p" с тремя знаками и помечают
значимость звёздочками, и это ровно то, чего ждут пользователи.
"""

from __future__ import annotations

import math
from typing import Any

# Порог, ниже которого p-value печатается как "< .001" (как в SPSS).
P_FLOOR = 0.001

# Соответствие: сколько знаков после запятой нужно, чтобы значение было читаемым.
_DECIMALS_FOR_MAGNITUDE = {0.1: 4, 0.01: 3, 0.001: 2}


def is_number(value: Any) -> bool:
    """True для чисел, но не для bool (bool - подкласс int, а нам это не нужно)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def decimals_for(value: float) -> int:
    """Сколько знаков после запятой показывать, чтобы значение было информативным."""
    if value == 0 or math.isnan(value):
        return 2
    magnitude = abs(value)
    for threshold, decimals in _DECIMALS_FOR_MAGNITUDE.items():
        if magnitude < threshold:
            return decimals
    return 2


def num(value: Any, decimals: int | None = None) -> str:
    """Форматирует число для ячейки таблицы.

    Мягко относится к "нечислу": None и NaN становятся точкой-заполнителем,
    потому что пустая ячейка в отчёте читается лучше, чем "nan".
    """
    if value is None:
        return "."
    if is_number(value) and math.isnan(float(value)):
        return "."
    if not is_number(value):
        return str(value)

    number = float(value)
    if decimals is None:
        decimals = decimals_for(number)
    if number == 0:
        # Убирает "-0.00" и приводит ноль к единому виду.
        number = 0.0
    return f"{number:.{decimals}f}"


def fmt_int(value: Any) -> str:
    if value is None:
        return "."
    if is_number(value) and math.isnan(float(value)):
        return "."
    if not is_number(value):
        return str(value)
    return str(int(round(float(value))))


def p_value(p: float | None) -> str:
    """p-value по правилам научных отчётов: никогда не печатаем "0.000"."""
    if p is None or (is_number(p) and math.isnan(float(p))):
        return "."
    p = float(p)
    if p < 0:
        return "."
    if p < P_FLOOR:
        return "< .001"
    return f"{p:.3f}"


def stars(p: float | None) -> str:
    """Звёздочки значимости - привычная нотация, её ждут в статьях."""
    if p is None or (is_number(p) and math.isnan(float(p))):
        return ""
    p = float(p)
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return ""


def sig_with_stars(p: float | None) -> str:
    """Компактная запись p со звёздочками, как в публикациях: ".032*"."""
    text = p_value(p)
    return f"{text}{stars(p)}" if stars(p) else text


def signed(value: float | None, decimals: int = 3) -> str:
    """Число со знаком: для разностей и коэффициентов удобно видеть направление."""
    if value is None or (is_number(value) and math.isnan(float(value))):
        return "."
    return num(float(value), decimals)


def label_for(code: Any, value_labels: dict[Any, str] | None) -> str:
    """Текстовая метка значения, если она задана в паспорте переменной."""
    if not value_labels:
        return "" if code is None else str(code)
    if code in value_labels:
        return value_labels[code]
    # Коды могут быть прочитаны как float (1.0), а метки заданы как int (1).
    if is_number(code):
        as_int = int(float(code))
        if as_int in value_labels:
            return value_labels[as_int]
        if float(code) in value_labels:
            return value_labels[float(code)]
    return str(code)
