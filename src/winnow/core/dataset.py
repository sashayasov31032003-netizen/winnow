"""Dataset - данные плюс паспорта переменных.

Ключевая идея: процедуры никогда не работают с DataFrame напрямую. Они получают
готовый "аналитический" срез, в котором уже применены коды пропусков, отбор
кейсов и веса. Это гарантирует, что все процедуры трактуют пропуски одинаково, -
иначе каждая новая процедура будет обрабатывать их по-своему, и отчёт начнёт
противоречить сам себе.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

import numpy as np
import pandas as pd

from winnow.core.variable import Measure, MissingSpec, Variable


@dataclass
class Dataset:
    """Набор данных: таблица кейсов + метаданные переменных."""

    frame: pd.DataFrame
    variables: OrderedDict[str, Variable] = field(default_factory=OrderedDict)
    name: str = "Набор1"
    weight_var: str | None = None
    filter_expr: str | None = None
    # Переменная разбиения: все процедуры выполняются отдельно по её категориям,
    # как «Split File» в SPSS. Это не то же самое, что отбор кейсов: отбор
    # оставляет часть данных, а разбиение - считает каждую часть отдельно.
    split_var: str | None = None
    split_values: list[Any] = field(default_factory=list)
    _filter_mask: pd.Series | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.variables:
            self.sync_variables()
        else:
            for column in self.frame.columns:
                if column not in self.variables:
                    self.variables[column] = Variable.from_series(column, self.frame[column])

    # ---------- состав ----------

    @property
    def n_cases(self) -> int:
        return int(len(self.frame))

    @property
    def n_vars(self) -> int:
        return len(self.variables)

    def var(self, name: str) -> Variable:
        try:
            return self.variables[name]
        except KeyError:
            raise KeyError(f"Переменная не найдена: {name!r}") from None

    def names(self) -> list[str]:
        return list(self.variables.keys())

    def sync_variables(self) -> None:
        """Приводит паспорта в соответствие с колонками таблицы."""
        for column in self.frame.columns:
            if column not in self.variables:
                self.variables[column] = Variable.from_series(column, self.frame[column])
        for name in list(self.variables):
            if name not in self.frame.columns:
                del self.variables[name]

    # ---------- паспорта ----------

    def set_label(self, name: str, label: str) -> None:
        self.var(name).label = label

    def set_measure(self, name: str, measure: Measure) -> None:
        self.var(name).measure = measure

    def set_value_labels(self, name: str, labels: dict[Any, str]) -> None:
        self.var(name).value_labels = dict(labels)

    def add_value_label(self, name: str, value: Any, label: str) -> None:
        self.var(name).value_labels[value] = label

    def set_missing(self, name: str, spec: MissingSpec) -> None:
        self.var(name).missing = spec

    # ---------- отбор кейсов и веса ----------

    def set_filter(self, mask: pd.Series | None) -> None:
        """Отбор кейсов. None означает "использовать все кейсы"."""
        if mask is None:
            self._filter_mask = None
            return
        if len(mask) != len(self.frame):
            raise ValueError("Маска отбора должна совпадать по длине с числом кейсов")
        if not mask.any():
            # Пустой отбор оставил бы все процедуры без данных и без объяснения.
            raise ValueError("Отбор не оставил ни одного кейса")
        self._filter_mask = mask.astype(bool)

    @property
    def has_filter(self) -> bool:
        return self._filter_mask is not None

    # ---------- разбиение файла (Split File) ----------

    @property
    def has_split(self) -> bool:
        return bool(self.split_var)

    def set_split(self, variable: str | None, values: list[Any] | None = None) -> None:
        """Включает разбиение файла по переменной.

        Если конкретные значения не заданы, берутся все категории переменной в
        том порядке, в котором они встречаются в данных. Значения нужны, чтобы
        процедура знала, по каким группам считать: без этого невозможно
        сформировать отдельный результат на каждую группу.
        """
        if not variable:
            self.split_var = None
            self.split_values = []
            return
        if variable not in self.variables:
            raise KeyError(f"Переменная разбиения не найдена: {variable!r}")
        self.split_var = variable
        self.split_values = list(values) if values else self._observed_split_values(variable)
        if not self.split_values:
            self.split_var = None
            raise ValueError(f"Переменная {variable!r} не содержит значений для разбиения")

    def clear_split(self) -> None:
        self.split_var = None
        self.split_values = []

    def _observed_split_values(self, variable: str) -> list[Any]:
        series = self.analysis_frame([variable])[variable].dropna()
        values = list(pd.unique(series))
        numeric = [value for value in values if isinstance(value, (int, float, np.integer, np.floating))]
        if len(numeric) == len(values):
            return sorted(values, key=float)
        return sorted(values, key=lambda value: str(value))

    def split_label(self, value: Any) -> str:
        """Подпись группы разбиения: «Пол респондента = Женский»."""
        variable = self.var(self.split_var) if self.split_var else None
        if variable is None:
            return str(value)
        name = variable.label or variable.name
        return f"{name} = {variable.label_for(value)}"

    def split_mask(self, value: Any) -> pd.Series:
        """Маска кейсов одной группы разбиения (с учётом общего отбора)."""
        if not self.split_var:
            raise ValueError("Разбиение файла не задано")
        series = self.frame[self.split_var]
        mask = (series == value) & series.notna()
        if self._filter_mask is not None:
            mask &= self._filter_mask
        result = mask.astype(bool)
        if not result.any():
            raise ValueError(f"В группе разбиения {value!r} не осталось кейсов")
        return result

    def weight_values(self) -> np.ndarray | None:
        """Веса кейсов. Отрицательные и пропущенные веса исключаются из анализа."""
        if not self.weight_var:
            return None
        weights = pd.to_numeric(self.frame[self.weight_var], errors="coerce").to_numpy(dtype=float)
        base = (
            self._filter_mask.to_numpy()
            if self._filter_mask is not None
            else np.ones(len(self.frame), bool)
        )
        return np.where(base & np.isfinite(weights) & (weights > 0), weights, 0.0)

    # ---------- аналитический срез ----------

    def analysis_frame(self, names: Iterable[str] | None = None) -> pd.DataFrame:
        """Срез для расчётов: отобранные кейсы, коды пропусков -> NaN.

        Возвращает копию, поэтому процедуры могут свободно её менять, не портя
        исходные данные пользователя.
        """
        selected = list(names) if names is not None else self.names()
        unknown = [n for n in selected if n not in self.frame.columns]
        if unknown:
            raise KeyError(f"Неизвестные переменные: {', '.join(unknown)}")

        out = self.frame.loc[:, selected].copy()
        if self._filter_mask is not None:
            out = out.loc[self._filter_mask.to_numpy()]

        for name in selected:
            variable = self.var(name)
            if not variable.missing.is_empty and pd.api.types.is_numeric_dtype(out[name]):
                masked = out[name].map(variable.missing.contains, na_action="ignore")
                if masked.dtype != bool:
                    masked = masked.astype("boolean").fillna(False).astype(bool)
                out[name] = out[name].mask(masked.to_numpy())
        return out

    def analysis_series(self, name: str) -> pd.Series:
        """Числовой ряд одной переменной, готовый к расчёту."""
        variable = self.var(name)
        if not variable.is_numeric:
            raise TypeError(f"Переменная {name!r} не является числовой")
        return pd.to_numeric(self.analysis_frame([name])[name], errors="coerce")

    def categorical_series(self, name: str) -> pd.Series:
        """Ряд для категориального анализа: строки остаются строками."""
        return self.analysis_frame([name])[name]

    # ---------- изменение состава ----------

    def add_variable(self, name: str, values: pd.Series | list[Any], **meta: Any) -> None:
        if name in self.frame.columns:
            raise ValueError(f"Переменная {name!r} уже существует")
        self.frame[name] = pd.Series(values).reset_index(drop=True)
        variable = Variable.from_series(name, self.frame[name])
        for key, value in meta.items():
            setattr(variable, key, value)
        self.variables[name] = variable

    def drop_variable(self, name: str) -> None:
        if name not in self.frame.columns:
            raise KeyError(f"Переменная не найдена: {name!r}")
        self.frame = self.frame.drop(columns=[name])
        self.variables.pop(name, None)
        if self.weight_var == name:
            self.weight_var = None

    def copy(self) -> Dataset:
        return replace(
            self,
            frame=self.frame.copy(),
            variables=OrderedDict(
                (key, replace(value, value_labels=dict(value.value_labels)))
                for key, value in self.variables.items()
            ),
        )

    # ---------- удобные конструкторы ----------

    @classmethod
    def from_dataframe(cls, frame: pd.DataFrame, name: str = "Набор1") -> Dataset:
        return cls(frame=pd.DataFrame(frame).reset_index(drop=True), name=name)

    @classmethod
    def from_records(
        cls,
        records: dict[str, list[Any]],
        name: str = "Набор1",
        measures: dict[str, Measure] | None = None,
    ) -> Dataset:
        dataset = cls(frame=pd.DataFrame(records), name=name)
        for var_name, measure in (measures or {}).items():
            dataset.var(var_name).measure = measure
        return dataset

    def summary(self) -> str:
        """Одна строка для строки состояния в окне."""
        parts = [f"Кейсов: {self.n_cases}", f"Переменных: {self.n_vars}"]
        if self.has_filter and self._filter_mask is not None:
            parts.append(f"Отобрано: {int(self._filter_mask.sum())} из {self.n_cases}")
        if self.has_split:
            parts.append(
                f"Разбиение: {self.split_var} ({len(self.split_values)} групп)"
            )
        if self.weight_var:
            parts.append(f"Веса: {self.weight_var}")
        return " | ".join(parts)


__all__ = ["Dataset", "Measure", "MissingSpec", "Variable"]
