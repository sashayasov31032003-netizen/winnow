"""Диалог разбиения файла.

Разбиение (в SPSS - «Split File») заставляет все процедуры считаться отдельно
по каждой категории выбранной переменной. Это одна из тех возможностей, ради
которых вообще нужен статистический пакет: вручную делать десяток отчётов по
подгруппам быстро надоедает.

Диалог намеренно объясняет разницу между разбиением и отбором кейсов: их часто
путают, а последствия разные.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from winnow.core.dataset import Dataset
from winnow.ui.components import action_button_box, hint_label
from winnow.ui.theme import design_system


class SplitFileDialog(QDialog):
    """Выбор переменной разбиения и её категорий."""

    def __init__(
        self, dataset: Dataset, theme: str = "light", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.dataset = dataset
        self.theme_name = theme
        self.setWindowTitle("Разбиение файла")
        self.setMinimumWidth(520)

        ds = design_system(theme)
        outer = QVBoxLayout(self)

        outer.addWidget(
            hint_label(
                "Все процедуры будут выполняться отдельно для каждой категории "
                "выбранной переменной. Например, t-критерий посчитается отдельно "
                "для каждого города."
            )
        )
        outer.addWidget(
            hint_label(
                "Это не то же самое, что отбор кейсов: отбор оставляет часть данных "
                "и считает один результат, а разбиение считает каждую группу отдельно."
            )
        )
        outer.addSpacing(ds.spacing.sm)

        row = QHBoxLayout()
        row.addWidget(QLabel("Группировать по:"))
        self.variable_combo = QComboBox()
        self.variable_combo.addItem("(разбиение выключено)", None)
        for name in dataset.names():
            variable = dataset.var(name)
            if variable.is_numeric and not variable.measure.is_categorical:
                # Разбивать по количественной переменной почти всегда ошибка:
                # групп получится столько же, сколько уникальных значений.
                continue
            self.variable_combo.addItem(variable.display_name, name)
        if dataset.split_var:
            index = self.variable_combo.findData(dataset.split_var)
            if index >= 0:
                self.variable_combo.setCurrentIndex(index)
        row.addWidget(self.variable_combo, 1)
        outer.addLayout(row)

        outer.addWidget(QLabel("Категории, по которым считать:"))
        self.values_list = QListWidget()
        self.values_list.setMinimumHeight(160)
        outer.addWidget(self.values_list)

        buttons_row = QHBoxLayout()
        select_all = QPushButton("Выбрать все")
        select_all.clicked.connect(self._select_all)
        clear_all = QPushButton("Снять выделение")
        clear_all.clicked.connect(self.values_list.clearSelection)
        buttons_row.addWidget(select_all)
        buttons_row.addWidget(clear_all)
        buttons_row.addStretch(1)
        outer.addLayout(buttons_row)

        self.variable_combo.currentIndexChanged.connect(self._reload_values)
        self._reload_values()

        outer.addSpacing(ds.spacing.sm)
        buttons, _ok, _cancel = action_button_box(theme, self, ok_text="Применить")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------ поля

    def _reload_values(self) -> None:
        """Показывает категории выбранной переменной."""
        self.values_list.clear()
        name = self.variable_combo.currentData()
        if not name:
            self.values_list.setEnabled(False)
            return
        self.values_list.setEnabled(True)

        variable = self.dataset.var(name)
        try:
            observed = self.dataset._observed_split_values(name)
        except Exception:  # noqa: BLE001 - переменная могла испортиться
            observed = []
        for value in observed:
            item = QListWidgetItem(variable.label_for(value))
            item.setData(1, value)
            item.setSelected(True)
            self.values_list.addItem(item)

    def _select_all(self) -> None:
        for index in range(self.values_list.count()):
            self.values_list.item(index).setSelected(True)

    # ------------------------------------------------------------ результат

    def selected_values(self) -> list[Any]:
        return [
            self.values_list.item(index).data(1)
            for index in range(self.values_list.count())
            if self.values_list.item(index).isSelected()
        ]

    def apply(self) -> None:
        """Применяет разбиение к набору данных."""
        name = self.variable_combo.currentData()
        if not name:
            self.dataset.clear_split()
            return
        values = self.selected_values()
        if not values:
            raise ValueError("Выберите хотя бы одну категорию для разбиения")
        self.dataset.set_split(name, values)


__all__ = ["SplitFileDialog"]
