"""Диалог свойств переменной: метка, метки значений, пропущенные, уровень измерения.

В SPSS это отдельное окно «Variable View / Define Variable Properties», и без него
данные невозможно описать: останутся «голые» коды без имён категорий, а значит
любой отчёт будет непонятен читателю. Поэтому диалог живой: он показывает, как
значения будут выглядеть в выводе, пока пользователь их описывает.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from winnow.core.variable import Measure, MissingSpec, Variable
from winnow.ui.components import action_button_box, hint_label
from winnow.ui.theme import design_system

MEASURE_LABELS: list[tuple[str, Measure]] = [
    ("Номинальная — категории без порядка", Measure.NOMINAL),
    ("Порядковая — категории с порядком", Measure.ORDINAL),
    ("Количественная — числа", Measure.SCALE),
]


class VariableDialog(QDialog):
    """Редактор свойств одной переменной. Изменения применяются методом apply()."""

    def __init__(
        self, variable: Variable, theme: str = "light", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.variable = variable
        self.theme_name = theme
        self.setWindowTitle(f"Свойства переменной — {variable.name}")
        self.setMinimumWidth(620)

        ds = design_system(theme)
        outer = QVBoxLayout(self)

        header = QLabel(f"<b>{variable.name}</b>")
        header.setStyleSheet(f"font-size: {ds.typography.pt(ds.typography.size_large)};")
        outer.addWidget(header)
        outer.addWidget(
            hint_label(
                "Метка и метки значений попадают в отчёты вместо кодов — именно они "
                "делают вывод понятным."
            )
        )
        outer.addSpacing(ds.spacing.sm)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.label_edit = QLineEdit(variable.label)
        self.label_edit.setPlaceholderText("Например: Возраст респондента")
        form.addRow("Метка переменной:", self.label_edit)

        self.measure_combo = QComboBox()
        for title, measure in MEASURE_LABELS:
            self.measure_combo.addItem(title, measure)
        index = self.measure_combo.findData(variable.measure)
        if index >= 0:
            self.measure_combo.setCurrentIndex(index)
        form.addRow("Уровень измерения:", self.measure_combo)

        self.type_label = QLabel(variable.var_type.value)
        self.type_label.setEnabled(False)
        form.addRow("Тип данных:", self.type_label)

        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 10)
        self.decimals_spin.setValue(variable.decimals)
        form.addRow("Знаков после запятой:", self.decimals_spin)

        self.missing_edit = QLineEdit(variable.missing.summary() if not variable.missing.is_empty else "")
        self.missing_edit.setPlaceholderText("Например: -99 или -99, -98 или -99..-90")
        form.addRow("Пропущенные значения:", self.missing_edit)

        outer.addLayout(form)

        # ------------------------------------------------------ метки значений
        labels_box = QGroupBox("Метки значений")
        labels_layout = QVBoxLayout(labels_box)

        self.labels_table = QTableWidget(0, 2)
        self.labels_table.setHorizontalHeaderLabels(["Значение", "Метка"])
        self.labels_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.labels_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.labels_table.verticalHeader().setVisible(False)
        self.labels_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.labels_table.setMinimumHeight(150)

        for value, label in variable.value_labels.items():
            self._append_label_row(str(value), label)

        labels_layout.addWidget(self.labels_table)

        buttons_row = QHBoxLayout()
        add_button = QPushButton("Добавить метку")
        add_button.clicked.connect(lambda: self._append_label_row("", ""))
        remove_button = QPushButton("Удалить метку")
        remove_button.clicked.connect(self._remove_label_row)
        buttons_row.addWidget(add_button)
        buttons_row.addWidget(remove_button)
        buttons_row.addStretch(1)
        labels_layout.addLayout(buttons_row)

        labels_layout.addWidget(
            hint_label(
                "Метка показывается рядом с кодом: «1 (Мужской)». Если метка не "
                "задана, в отчёте будет только код."
            )
        )
        outer.addWidget(labels_box)

        # --------------------------------------------------------------- низ
        buttons, _ok, _cancel = action_button_box(
            theme, self, ok_text="Применить"
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------ метки

    def _append_label_row(self, value: str, label: str) -> None:
        row = self.labels_table.rowCount()
        self.labels_table.insertRow(row)
        self.labels_table.setItem(row, 0, QTableWidgetItem(value))
        self.labels_table.setItem(row, 1, QTableWidgetItem(label))

    def _remove_label_row(self) -> None:
        rows = sorted({index.row() for index in self.labels_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.labels_table.removeRow(row)

    def _collect_value_labels(self) -> dict[Any, str]:
        labels: dict[Any, str] = {}
        for row in range(self.labels_table.rowCount()):
            value_item = self.labels_table.item(row, 0)
            label_item = self.labels_table.item(row, 1)
            value_text = (value_item.text() if value_item else "").strip()
            label_text = (label_item.text() if label_item else "").strip()
            if not value_text:
                continue
            try:
                number = float(value_text.replace(",", "."))
                key: Any = int(number) if number.is_integer() else number
            except ValueError:
                key = value_text
            labels[key] = label_text
        return labels

    # ---------------------------------------------------------- применение

    def _collect_missing(self) -> MissingSpec:
        """Разбирает строку с пропущенными значениями.

        Поддерживаются три формы: отдельные коды («-99, -98»), диапазон
        («-99..-90») и их сочетание — как в SPSS.
        """
        text = self.missing_edit.text().strip()
        spec = MissingSpec()
        if not text or text.lower() in ("нет", "-", "—"):
            return spec

        for chunk in text.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ".." in chunk:
                low, _, high = chunk.partition("..")
                try:
                    spec.lo = float(low.strip().replace(",", "."))
                    spec.hi = float(high.strip().replace(",", "."))
                except ValueError:
                    raise ValueError(f"Не удалось разобрать диапазон: {chunk!r}") from None
            else:
                try:
                    spec.discrete.add(float(chunk.replace(",", ".")))
                except ValueError:
                    raise ValueError(
                        f"Пропущенные значения задаются числами: {chunk!r}"
                    ) from None
        return spec

    def _on_accept(self) -> None:
        try:
            self._collect_missing()
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте пропущенные значения", str(exc))
            return
        self.accept()

    def apply(self) -> None:
        """Переносит значения из полей в объект переменной."""
        self.variable.label = self.label_edit.text().strip()
        measure = self.measure_combo.currentData()
        if isinstance(measure, Measure):
            self.variable.measure = measure
        self.variable.decimals = self.decimals_spin.value()
        self.variable.value_labels = self._collect_value_labels()
        self.variable.missing = self._collect_missing()

        # Строковая переменная не может быть количественной.
        if not self.variable.is_numeric and self.variable.measure is Measure.SCALE:
            self.variable.measure = Measure.NOMINAL


__all__ = ["MEASURE_LABELS", "VariableDialog"]
