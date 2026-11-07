"""Qt-модели таблиц: Data View и Variable View.

Использование QAbstractTableModel (а не QTableWidget) - принципиальное решение:
на 100 000 кейсов QTableWidget создаёт 100 000 виджетов и программа умирает.
Модель же отдаёт Qt только те строки, которые видны на экране.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec, VarType


class DataTableModel(QAbstractTableModel):
    """Таблица кейсов. Для категориальных переменных показываются метки значений."""

    def __init__(self, dataset: Dataset | None = None) -> None:
        super().__init__()
        self._dataset = dataset

    def set_dataset(self, dataset: Dataset | None) -> None:
        self.beginResetModel()
        self._dataset = dataset
        self.endResetModel()

    @property
    def dataset(self) -> Dataset | None:
        return self._dataset

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._dataset is None:
            return 0
        return self._dataset.n_cases

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._dataset is None:
            return 0
        return self._dataset.n_vars

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if self._dataset is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self._dataset.names()[section]
            return section + 1
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            variable = self._dataset.var(self._dataset.names()[section])
            if variable.label:
                return variable.label
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or self._dataset is None:
            return None
        name = self._dataset.names()[index.column()]
        variable = self._dataset.var(name)
        value = self._dataset.frame.iat[index.row(), index.column()]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return ""
            if variable.value_labels:
                label = variable.label_for(value)
                if label and label != str(value):
                    return label
            if isinstance(value, float):
                return f"{value:.{variable.decimals}f}"
            return str(value)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if variable.is_numeric:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.BackgroundRole:
            # Пропущенные значения подсвечиваются: пользователь должен видеть,
            # что именно исключается из анализа.
            if variable.missing.contains(value):
                return QColor("#ffe0e0")
        return None


class VariableTableModel(QAbstractTableModel):
    """Паспорта переменных - аналог Variable View в SPSS.

    Колонки "Метка", "Уровень", "Метки значений", "Пропущенные" редактируемы:
    без этого пользователь не сможет описать свои данные, а без описания
    статистика будет считаться "неизвестно по чему".
    """

    HEADERS = [
        "Имя",
        "Метка",
        "Тип",
        "Уровень измерения",
        "Знаков",
        "Метки значений",
        "Пропущенные",
    ]

    def __init__(self, dataset: Dataset | None = None) -> None:
        super().__init__()
        self._dataset = dataset

    def set_dataset(self, dataset: Dataset | None) -> None:
        self.beginResetModel()
        self._dataset = dataset
        self.endResetModel()

    def _variable(self, row: int):
        if self._dataset is None:
            return None
        names = self._dataset.names()
        if not 0 <= row < len(names):
            return None
        return self._dataset.var(names[row])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._dataset is None:
            return 0
        return self._dataset.n_vars

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.HEADERS[section]
            return section + 1
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if not index.isValid():
            return base
        # Имя и тип переменной здесь не редактируются: переименование колонки -
        # отдельная операция, которую мы пока не поддерживаем.
        if index.column() in (0, 2):
            return base
        return base | Qt.ItemFlag.ItemIsEditable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        variable = self._variable(index.row())
        if variable is None:
            return None
        column = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if column == 0:
                return variable.name
            if column == 1:
                return variable.label
            if column == 2:
                return variable.var_type.value
            if column == 3:
                return variable.measure.value
            if column == 4:
                return variable.decimals
            if column == 5:
                return "; ".join(f"{k} = {v}" for k, v in variable.value_labels.items())
            if column == 6:
                return variable.missing.summary()

        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                "Двойной щелчок - редактирование.\n"
                "Уровень измерения: nominal / ordinal / scale.\n"
                "Метки значений: 1 = мужской; 2 = женский.\n"
                "Пропущенные: -99 или -99..-90 или -99, -98."
            )
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        variable = self._variable(index.row())
        if variable is None or role != Qt.ItemDataRole.EditRole:
            return False

        text = str(value).strip()
        column = index.column()
        try:
            if column == 1:
                variable.label = text
            elif column == 3:
                measure = text.lower()
                if measure not in {m.value for m in Measure}:
                    return False
                variable.measure = Measure(measure)
            elif column == 4:
                decimals = int(text)
                if decimals < 0 or decimals > 10:
                    return False
                variable.decimals = decimals
            elif column == 5:
                variable.value_labels = _parse_labels(text)
            elif column == 6:
                variable.missing = _parse_missing(text)
            else:
                return False
        except (ValueError, TypeError):
            return False

        self.dataChanged.emit(
            index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole]
        )
        return True

    def refresh(self) -> None:
        self.beginResetModel()
        self.endResetModel()


def _parse_labels(text: str) -> dict[Any, str]:
    """Разбирает строку "1 = мужской; 2 = женский" в словарь меток."""
    labels: dict[Any, str] = {}
    if not text:
        return labels
    for chunk in text.replace("\n", ";").split(";"):
        if "=" not in chunk:
            continue
        key, _, label = chunk.partition("=")
        key, label = key.strip(), label.strip()
        if not key:
            continue
        try:
            number = float(key)
            labels[int(number) if number.is_integer() else number] = label
        except ValueError:
            labels[key] = label
    return labels


def _parse_missing(text: str) -> MissingSpec:
    """Разбирает описание пропущенных: "-99", "-99, -98", "-99..-90"."""
    spec = MissingSpec()
    if not text or text.strip().lower() in ("нет", "-", "—"):
        return spec

    for chunk in text.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ".." in chunk:
            low, _, high = chunk.partition("..")
            spec.lo = float(low.strip())
            spec.hi = float(high.strip())
        else:
            spec.discrete.add(float(chunk))
    return spec


__all__ = ["DataTableModel", "VariableTableModel"]
