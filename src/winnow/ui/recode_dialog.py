"""Диалог перекодирования переменной.

Устроен сложнее остальных окон: вместо набора полей здесь таблица правил
(«значение → новое значение», «диапазон → новое значение»). Поэтому у него
отдельный класс, а не декларативное описание.

Диалог сразу показывает, сколько кейсов попадёт под каждое правило: пользователь
видит результат до нажатия кнопки, а не после.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from winnow.core.dataset import Dataset
from winnow.stats.command import RecodeCommand, RecodeRule
from winnow.ui.components import action_button_box, hint_label
from winnow.ui.theme import design_system

RULE_KINDS: list[tuple[str, str]] = [
    ("Значение равно", "value"),
    ("Диапазон [a; b)", "range"),
    ("Пропущенные значения", "system_missing"),
    ("Все остальные", "else"),
]


class RecodeDialog(QDialog):
    """Перекодирование значений исходной переменной в новую."""

    def __init__(
        self, dataset: Dataset, theme: str = "light", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.dataset = dataset
        self.theme_name = theme
        self.setWindowTitle("Перекодировать в новую переменную")
        self.setMinimumWidth(820)

        ds = design_system(theme)
        outer = QVBoxLayout(self)

        outer.addWidget(
            hint_label(
                "Правила применяются по порядку: если кейс подходит под несколько, "
                "действует последнее. Кейсы, не попавшие ни под одно правило, "
                "получат пропущенное значение."
            )
        )
        outer.addSpacing(ds.spacing.sm)

        # ------------------------------------------------------ источник
        header = QHBoxLayout()
        header.addWidget(QLabel("Перекодировать:"))
        self.source_combo = QComboBox()
        for name in dataset.names():
            self.source_combo.addItem(dataset.var(name).display_name, name)
        header.addWidget(self.source_combo, 1)
        outer.addLayout(header)

        header2 = QHBoxLayout()
        header2.addWidget(QLabel("Имя новой переменной:"))
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("например age_group")
        header2.addWidget(self.target_edit, 1)
        header2.addWidget(QLabel("Метка:"))
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("необязательно")
        header2.addWidget(self.label_edit, 1)
        outer.addLayout(header2)

        # -------------------------------------------------------- правила
        outer.addWidget(QLabel("Правила:"))
        self.rules_table = QTableWidget(0, 5)
        self.rules_table.setHorizontalHeaderLabels(
            ["Условие", "Значение / от", "до", "Новое значение", "Кейсов"]
        )
        table_header = self.rules_table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rules_table.setMinimumHeight(200)
        self.rules_table.itemChanged.connect(self._update_counts)
        outer.addWidget(self.rules_table, 1)

        buttons_row = QHBoxLayout()
        add_button = QPushButton("Добавить правило")
        add_button.clicked.connect(lambda: self._add_row("value"))
        remove_button = QPushButton("Удалить правило")
        remove_button.clicked.connect(self._remove_selected)
        buttons_row.addWidget(add_button)
        buttons_row.addWidget(remove_button)
        buttons_row.addStretch(1)
        outer.addLayout(buttons_row)

        self.source_combo.currentIndexChanged.connect(self._update_counts)

        # Полезные значения: сразу подставляем коды из меток, чтобы не набирать руками.
        self._add_row("value")
        self._update_counts()

        outer.addSpacing(ds.spacing.sm)
        box, _ok, _cancel = action_button_box(theme, self, ok_text="Выполнить")
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        outer.addWidget(box)

    # -------------------------------------------------------------- правила

    def _add_row(self, kind: str) -> None:
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)

        combo = QComboBox()
        for title, key in RULE_KINDS:
            combo.addItem(title, key)
        index = combo.findData(kind)
        combo.setCurrentIndex(max(index, 0))
        combo.currentIndexChanged.connect(self._update_counts)
        self.rules_table.setCellWidget(row, 0, combo)

        for column in (1, 2, 3):
            self.rules_table.setItem(row, column, QTableWidgetItem(""))
        counted = QTableWidgetItem("")
        counted.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.rules_table.setItem(row, 4, counted)
        self._update_counts()

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.rules_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.rules_table.removeRow(row)
        self._update_counts()

    def _kind_of(self, row: int) -> str:
        widget = self.rules_table.cellWidget(row, 0)
        return widget.currentData() if isinstance(widget, QComboBox) else "value"

    def _text(self, row: int, column: int) -> str:
        item = self.rules_table.item(row, column)
        return item.text().strip() if item else ""

    def _parse_number(self, text: str) -> float | None:
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None

    def rules(self) -> list[RecodeRule]:
        """Собирает правила из таблицы. Пустые строки пропускаются."""
        rules: list[RecodeRule] = []
        for row in range(self.rules_table.rowCount()):
            kind = self._kind_of(row)
            new_text = self._text(row, 3)
            if kind in ("value", "range") and not new_text:
                continue
            if kind == "value":
                raw_value = self._text(row, 1)
                if not raw_value:
                    continue
                number = self._parse_number(raw_value)
                rules.append(
                    RecodeRule(
                        kind="value",
                        value=number if number is not None else raw_value,
                        new_value=self._parse_number(new_text) if self._parse_number(new_text) is not None else new_text,
                    )
                )
            elif kind == "range":
                low = self._parse_number(self._text(row, 1))
                high = self._parse_number(self._text(row, 2))
                if low is None or high is None:
                    continue
                rules.append(
                    RecodeRule(
                        kind="range",
                        low=low,
                        high=high,
                        new_value=self._parse_number(new_text) if self._parse_number(new_text) is not None else new_text,
                    )
                )
            elif kind == "system_missing":
                rules.append(
                    RecodeRule(
                        kind="system_missing",
                        new_value=self._parse_number(new_text) if self._parse_number(new_text) is not None else new_text,
                    )
                )
            else:  # else
                rules.append(
                    RecodeRule(
                        kind="else",
                        new_value=self._parse_number(new_text) if self._parse_number(new_text) is not None else new_text,
                    )
                )
        return rules

    def _update_counts(self) -> None:
        """Показывает, сколько кейсов попадает под каждое правило.

        Счёт обновляется при каждом изменении таблицы, чтобы пользователь видел
        последствия правила до нажатия кнопки.
        """
        name = self.source_combo.currentData()
        if not name:
            return
        series = self.dataset.frame[name]
        from winnow.stats.transform import _matches

        # Считаем по строкам таблицы, а не по собранным правилам: пустые строки
        # в правила не попадают, а показать их количество всё равно полезно.
        for row in range(self.rules_table.rowCount()):
            item = self.rules_table.item(row, 4)
            if item is None:
                continue
            kind = self._kind_of(row)
            raw_first = self._text(row, 1)
            number = self._parse_number(raw_first)
            rule = RecodeRule(
                kind=kind,
                value=number if number is not None else (raw_first or None),
                low=number,
                high=self._parse_number(self._text(row, 2)),
                new_value=self._text(row, 3) or None,
            )
            try:
                item.setText(str(int(_matches(series, rule).sum())))
            except Exception:  # noqa: BLE001 - незаполненное правило не должно ломать счёт
                item.setText("—")

    # ------------------------------------------------------------- результат

    def _on_accept(self) -> None:
        try:
            rules = self.rules()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Проверьте правила", str(exc))
            return
        if not rules:
            QMessageBox.warning(
                self, "Нет правил", "Заполните хотя бы одно правило перекодирования."
            )
            return
        self.accept()

    def build_command(self) -> RecodeCommand:
        return RecodeCommand(
            dataset=self.dataset,
            source=self.source_combo.currentData(),
            target=self.target_edit.text().strip(),
            label=self.label_edit.text().strip(),
            rules=self.rules(),
        )


__all__ = ["RULE_KINDS", "RecodeDialog"]
