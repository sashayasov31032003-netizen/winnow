"""Дерево вывода: навигатор по результатам в левой части панели.

Зачем дерево, а не просто «лента» результатов: в реальном анализе результатов
накапливается десятки, и найти нужную таблицу в сплошном свитке невозможно.
Дерево даёт оглавление, по которому видно структуру выполненного анализа -
именно так это устроено в SPSS, и это один из элементов, которых не хватает PSPP.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from winnow.stats.result import Result


class OutputTree(QTreeWidget):
    """Дерево процедур и их таблиц. Испускает сигнал при выборе элемента."""

    nodeSelected = Signal(int, int)  # (индекс процедуры, индекс таблицы или -1)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setIndentation(14)
        self.itemSelectionChanged.connect(self._on_selection)

    def add_result(self, result: Result) -> QTreeWidgetItem:
        """Добавляет процедуру с вложенными таблицами."""
        index = self.topLevelItemCount()
        title = result.title or result.procedure
        root = QTreeWidgetItem([f"{index + 1}. {title}"])
        root.setData(0, Qt.ItemDataRole.UserRole, (index, -1))
        root.setToolTip(0, f"{result.procedure}: таблиц {len(result.tables)}")

        for table_index, table in enumerate(result.tables):
            child = QTreeWidgetItem([table.title])
            child.setData(0, Qt.ItemDataRole.UserRole, (index, table_index))
            child.setToolTip(0, table.title)
            root.addChild(child)

        self.addTopLevelItem(root)
        root.setExpanded(True)
        self.setCurrentItem(root)
        self.scrollToItem(root)
        return root

    def clear_all(self) -> None:
        self.clear()

    def _on_selection(self) -> None:
        items = self.selectedItems()
        if not items:
            return
        payload = items[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(payload, tuple) and len(payload) == 2:
            self.nodeSelected.emit(int(payload[0]), int(payload[1]))


__all__ = ["OutputTree"]
