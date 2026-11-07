"""Переиспользуемые компоненты интерфейса.

Правило: внешний вид задаётся здесь один раз, а не в каждом окне. Новые окна
собираются из этих элементов, поэтому добавление процедуры не приводит к
появлению очередного «немного другого» дизайна.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from winnow.ui.theme import DesignSystem, design_system


# --------------------------------------------------------------------- простые


def hint_label(text: str) -> QLabel:
    """Второстепенная подпись: пояснение под заголовком или рядом с полем."""
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "title")
    return label


def subtitle_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    return label


# ---------------------------------------------------------------- контейнеры


class Card(QFrame):
    """Карточка: белая поверхность с рамкой и скруглением.

    Основной строительный блок для пустых состояний и сводок. Даёт интерфейсу
    «воздух» вместо сплошной серой формы.
    """

    def __init__(self, title: str = "", theme: str = "light", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ds = design_system(theme)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"""
            QFrame#Card {{
                background: {ds.palette.surface};
                border: 1px solid {ds.palette.border};
                border-radius: {ds.radii.lg}px;
            }}
            """
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            ds.spacing.lg, ds.spacing.lg, ds.spacing.lg, ds.spacing.lg
        )
        self._layout.setSpacing(ds.spacing.sm)

        if title:
            heading = QLabel(title)
            heading.setProperty("role", "cardTitle")
            self._layout.addWidget(heading)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget


class SectionHeader(QWidget):
    """Заголовок раздела с необязательной подписью справа."""

    def __init__(
        self,
        title: str,
        trailing: str = "",
        theme: str = "light",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        ds = design_system(theme)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ds.spacing.sm)

        heading = QLabel(title)
        heading.setProperty("role", "cardTitle")
        layout.addWidget(heading)
        layout.addStretch(1)

        if trailing:
            layout.addWidget(hint_label(trailing))


# --------------------------------------------------------- действия и подсказки


class QuickAction(QPushButton):
    """Крупная кнопка быстрого действия с пояснением - для пустого состояния."""

    def __init__(
        self,
        title: str,
        description: str = "",
        theme: str = "light",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        ds = design_system(theme)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(64)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: {ds.palette.surface_alt};
                border: 1px solid {ds.palette.border};
                border-radius: {ds.radii.md}px;
                padding: {ds.spacing.sm}px {ds.spacing.md}px;
                text-align: left;
                font-size: {ds.typography.pt(ds.typography.size_medium)};
                font-weight: 600;
                color: {ds.palette.text};
            }}
            QPushButton:hover {{
                border-color: {ds.palette.accent};
                background: {ds.palette.accent_soft};
                color: {ds.palette.accent};
            }}
            QPushButton:pressed {{
                background: {ds.palette.surface_sunken};
            }}
            """
        )
        self.setText(title if not description else f"{title}\n{description}")
        if description:
            self.setToolTip(description)


class FormulaBar(QFrame):
    """Строка с координатами ячейки и её содержимым - как в SPSS и Excel.

    Пользователи, привыкшие к таблицам, ждут возможности увидеть и править
    значение в одном месте, а не только в мелкой ячейке.
    """

    valueEdited = Signal(str)

    def __init__(self, theme: str = "light", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit

        ds = design_system(theme)
        self.setObjectName("FormulaBar")
        self.setStyleSheet(
            f"""
            QFrame#FormulaBar {{
                background: {ds.palette.surface};
                border-bottom: 1px solid {ds.palette.border};
            }}
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(ds.spacing.sm, ds.spacing.xs, ds.spacing.sm, ds.spacing.xs)
        layout.setSpacing(ds.spacing.sm)

        self.reference = QLabel("—")
        self.reference.setMinimumWidth(90)
        self.reference.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reference.setStyleSheet(
            f"""
            background: {ds.palette.surface_sunken};
            border: 1px solid {ds.palette.border};
            border-radius: {ds.radii.sm}px;
            padding: {ds.spacing.xxs}px {ds.spacing.xs}px;
            color: {ds.palette.text_muted};
            font-weight: 600;
            """
        )
        layout.addWidget(self.reference)

        self.editor = QLineEdit()
        self.editor.setPlaceholderText("Значение ячейки")
        self.editor.setEnabled(False)
        self.editor.returnPressed.connect(self._emit_value)
        layout.addWidget(self.editor, 1)

    def set_reference(self, text: str) -> None:
        self.reference.setText(text)

    def set_value(self, text: str) -> None:
        self.editor.setEnabled(True)
        self.editor.setText(text)

    def clear_value(self) -> None:
        self.editor.setEnabled(False)
        self.editor.clear()

    def _emit_value(self) -> None:
        self.valueEdited.emit(self.editor.text())


# -------------------------------------------------------------- пустое состояние


class EmptyState(QWidget):
    """Экран-приглашение, когда данных ещё нет.

    Это первое, что видит человек, открывший программу, поэтому здесь важны и
    крупный заголовок, и понятные следующие шаги.
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        actions: Iterable[tuple[str, str, object]] = (),
        theme: str = "light",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        ds = design_system(theme)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ds.spacing.xxl, ds.spacing.xxl, ds.spacing.xxl, ds.spacing.xxl)
        layout.setSpacing(ds.spacing.md)
        layout.addStretch(1)

        heading = title_label(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(heading)

        caption = subtitle_label(subtitle)
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(caption)

        layout.addSpacing(ds.spacing.lg)

        for label, description, callback in actions:
            button = QuickAction(label, description, theme=theme)
            if callable(callback):
                button.clicked.connect(callback)
            wrapper = QHBoxLayout()
            wrapper.addStretch(1)
            wrapper.addWidget(button, 3)
            wrapper.addStretch(1)
            layout.addLayout(wrapper)

        layout.addStretch(2)


def action_button_box(
    theme: str = "light",
    parent: QWidget | None = None,
    ok_text: str = "Выполнить",
    cancel_text: str = "Отмена",
):
    """Кнопки подтверждения и отмены с гарантированным запасом под текст.

    Одной таблицы стилей здесь недостаточно. Отступы из QSS зависят от того, как
    Qt посчитает содержимое кнопки для конкретного шрифта, и при жирном шрифте
    акцентной кнопки первая буква подписи упирается в край и выглядит обрезанной.
    Поэтому ширина задаётся программно, по реальным метрикам шрифта.
    """
    from PySide6.QtWidgets import QDialogButtonBox

    ds = design_system(theme)
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent,
    )
    ok_button = box.button(QDialogButtonBox.StandardButton.Ok)
    cancel_button = box.button(QDialogButtonBox.StandardButton.Cancel)
    ok_button.setText(ok_text)
    cancel_button.setText(cancel_text)

    for button in (ok_button, cancel_button):
        button.ensurePolished()
        # Запас намеренно щедрый: 48 точек суммарно. Метрики шрифта, которыми
        # пользуется Qt, не всегда совпадают с тем, как шрифт отрисует система
        # (подмена шрифта, другой рендерер), и скупой запас приводил к тому, что
        # у подписи срезалась первая буква.
        needed = button.fontMetrics().horizontalAdvance(button.text()) + 48
        button.setMinimumWidth(needed)
        button.setMinimumHeight(
            max(button.fontMetrics().height() + 14, ds.spacing.xl + 6)
        )
        # Отступы задаются и в коде, а не только в таблице стилей: QSS-отступы
        # применяются не во всех сочетаниях версии Qt и системного стиля, и тогда
        # текст упирается прямо в край кнопки.
        button.setStyleSheet(
            f"QPushButton {{ padding-left: {ds.spacing.lg}px; "
            f"padding-right: {ds.spacing.lg}px; }}"
        )
    return box, ok_button, cancel_button


__all__ = [
    "Card",
    "EmptyState",
    "FormulaBar",
    "QuickAction",
    "SectionHeader",
    "action_button_box",
    "hint_label",
    "subtitle_label",
    "title_label",
]
