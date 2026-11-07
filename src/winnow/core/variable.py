"""Паспорт переменной - то, чем Winnow отличается от "просто pandas".

В SPSS у переменной есть не только данные, но и метаданные: метка, уровень
измерения, метки значений, пропуски, формат отображения. Статистика обязана
брать эти сведения из паспорта, а не угадывать их по данным, - иначе вывод
получается "примерно верным", а это худший вид ошибки в статистическом пакете.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd


class Measure(Enum):
    """Уровень измерения. Влияет на список доступных процедур и вид отчёта."""

    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    SCALE = "scale"

    @property
    def ru(self) -> str:
        return {"nominal": "Номинальная", "ordinal": "Порядковая", "scale": "Количественная"}[
            self.value
        ]

    @property
    def is_categorical(self) -> bool:
        return self in (Measure.NOMINAL, Measure.ORDINAL)

    @property
    def is_nominal(self) -> bool:
        """Номинальная шкала: значения — только метки, порядка между ними нет.

        Различие с порядковой принципиально для вывода: у номинальной переменной
        значения являются кодами ответов, и среднее по ним («пол в среднем 1,56»)
        не значит ничего. У порядковой порядок категорий осмыслен, и среднее по
        баллам считается, хотя распределение всё равно информативнее.
        """
        return self is Measure.NOMINAL


class VarType(Enum):
    NUMERIC = "numeric"
    STRING = "string"
    DATE = "date"


@dataclass
class ValueLabel:
    """Метка отдельного значения: 1 -> "мужской"."""

    value: Any
    label: str


@dataclass
class MissingSpec:
    """Пропущенные значения SPSS: дискретные коды и/или диапазон.

    Важно: диапазон и дискретные значения - разные вещи. Код -99 и диапазон
    [-99, -90] могут сосуществовать, и это не ошибка пользователя.
    """

    discrete: set[float] = field(default_factory=set)
    lo: float | None = None
    hi: float | None = None

    @property
    def is_empty(self) -> bool:
        return not self.discrete and self.lo is None and self.hi is None

    def contains(self, value: Any) -> bool:
        if value is None or isinstance(value, str):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if number != number:  # NaN
            return True
        if number in self.discrete:
            return True
        if self.lo is not None and self.hi is not None:
            return self.lo <= number <= self.hi
        return False

    def summary(self) -> str:
        if self.is_empty:
            return "нет"
        parts = [str(int(v)) if float(v).is_integer() else str(v) for v in sorted(self.discrete)]
        if self.lo is not None and self.hi is not None:
            parts.append(f"{self.lo:g}..{self.hi:g}")
        return ", ".join(parts)


def _guess_measure(series: pd.Series) -> Measure:
    """Угадывает уровень измерения числовой переменной.

    Решение принимает пользователь в окне переменных, поэтому правило должно
    быть предсказуемым и объяснимым. Оно такое:

    * **два различных значения** - это код (пол, да/нет), то есть номинальная
      шкала. Порядка между «мужчина» и «женщина» нет, и объявлять такую
      переменную порядковой неверно;
    * **одно значение** - переменная-константа; измерять в ней нечего, и
      номинальная шкала здесь честнее количественной;
    * **целые числа в узком диапазоне** (1..5, 0..10, баллы и пункты анкет) -
      порядковая шкала;
    * **всё остальное** - количественная.

    Раньше правило звучало как «целые и не больше десяти различных значений -
    порядковая», и на маленькой выборке количественными переставали быть возраст
    и стаж: у шести человек шесть различных значений возраста, и он объявлялся
    порядковым. Диапазон значений разделяет эти случаи надёжнее, чем число
    градаций: у возраста он десятки, у пункта анкеты - единицы.
    """
    values = series.dropna()
    if len(values) == 0:
        return Measure.SCALE

    unique = values.unique()
    count = len(unique)
    if count <= 2:
        return Measure.NOMINAL

    try:
        numbers = [float(value) for value in unique]
    except (TypeError, ValueError):
        return Measure.NOMINAL

    # Дробные значения - это измерение, а не градации.
    if not all(number.is_integer() for number in numbers):
        return Measure.SCALE

    span = max(numbers) - min(numbers)
    if count <= 10 and span <= 10 and min(numbers) >= 0:
        return Measure.ORDINAL
    return Measure.SCALE


@dataclass
class Variable:
    """Описание одной переменной: имя, метка, тип, уровень, метки значений, пропуски."""

    name: str
    label: str = ""
    measure: Measure = Measure.SCALE
    var_type: VarType = VarType.NUMERIC
    width: int = 8
    decimals: int = 2
    value_labels: dict[Any, str] = field(default_factory=dict)
    missing: MissingSpec = field(default_factory=MissingSpec)
    columns: int = 0  # для строковых переменных: сколько символов показывать

    @property
    def display_name(self) -> str:
        """"Возраст [age]" - как в дереве переменных SPSS.

        Если метка совпадает с именем (так бывает, когда переменная названа
        текстом вопроса), второй раз её не повторяем: «Ваш пол [Ваш пол]»
        читать незачем.
        """
        if not self.label or self.label == self.name:
            return self.name
        return f"{self.label} [{self.name}]"

    @property
    def is_numeric(self) -> bool:
        return self.var_type == VarType.NUMERIC

    def label_for(self, value: Any) -> str:
        if value in self.value_labels:
            return self.value_labels[value]
        if isinstance(value, float) and value.is_integer() and int(value) in self.value_labels:
            return self.value_labels[int(value)]
        return "" if value is None else str(value)

    @classmethod
    def from_series(cls, name: str, series: pd.Series) -> Variable:
        """Выводит паспорт из данных - разумные значения по умолчанию.

        Уровень измерения здесь угадывается: числовая с малым числом уникальных
        значений помечается порядковой. Это эвристика, и пользователь должен
        иметь возможность её исправить в Variable View - что и есть смысл
        отдельного окна метаданных.
        """
        dtype = series.dtype
        if pd.api.types.is_bool_dtype(dtype):
            var_type, measure = VarType.NUMERIC, Measure.NOMINAL
        elif pd.api.types.is_numeric_dtype(dtype):
            var_type = VarType.NUMERIC
            measure = _guess_measure(series)
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            var_type, measure = VarType.DATE, Measure.SCALE
        else:
            var_type, measure = VarType.STRING, Measure.NOMINAL

        columns = 0
        if var_type == VarType.STRING:
            lengths = series.dropna().astype(str).str.len()
            columns = int(lengths.max()) if len(lengths) else 8

        return cls(
            name=name,
            var_type=var_type,
            measure=measure,
            columns=columns,
        )
