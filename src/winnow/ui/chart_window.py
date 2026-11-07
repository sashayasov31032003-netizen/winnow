"""Окно просмотра графика с экспортом.

График показывается в отдельном окне, как в SPSS: пользователь может его
рассмотреть, изменить размер окна и сохранить. Экспорт идёт в двух форматах:
PNG для вставки в презентацию и SVG для отчёта - вектор не расплывается при
печати, а растровый рисунок расплывается.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from winnow.stats.charts import ChartData, chart_caption
from winnow.ui.chart_widget import EXPORT_HEIGHT, EXPORT_WIDTH, ChartRenderer, render_chart
from winnow.ui.components import hint_label
from winnow.ui.theme import design_system


class ChartCanvas(QWidget):
    """Холст, который рисует график в своих текущих размерах.

    И экран, и экспорт используют одну и ту же функцию рисования, поэтому
    сохранённая картинка не отличается от того, что видно в окне.
    """

    def __init__(self, data: ChartData, theme: str = "light", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data = data
        self.theme_name = theme
        self.setMinimumSize(520, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_theme(self, theme: str) -> None:
        self.theme_name = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - имя задано Qt
        ds = design_system(self.theme_name)
        painter = QPainter(self)
        try:
            ChartRenderer(self.data, ds.palette).render(
                painter, float(self.width()), float(self.height())
            )
        finally:
            painter.end()

    def pixmap(self, width: int = EXPORT_WIDTH, height: int = EXPORT_HEIGHT) -> QPixmap:
        return QPixmap.fromImage(render_chart(self.data, self.theme_name, width, height))


class ChartWindow(QDialog):
    """Отдельное окно с графиком и кнопками экспорта."""

    def __init__(self, data: ChartData, theme: str = "light", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data = data
        self.theme_name = theme
        self.saved_path: str | None = None
        self.setWindowTitle(f"График — {data.title}")
        self.resize(960, 660)
        # Окно не модальное: пользователь может сравнить несколько графиков.
        self.setModal(False)

        ds = design_system(theme)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ds.spacing.lg, ds.spacing.lg, ds.spacing.lg, ds.spacing.lg)
        layout.setSpacing(ds.spacing.sm)

        caption = chart_caption(data)
        if caption:
            layout.addWidget(hint_label(caption))
        for note in data.notes:
            layout.addWidget(hint_label(note))

        self.canvas = ChartCanvas(data, theme, self)
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        for text, handler, tip in (
            ("Сохранить PNG…", self.export_png, "Растровый рисунок для презентации"),
            ("Сохранить SVG…", self.export_svg, "Векторный рисунок для отчёта и печати"),
            ("Копировать", self.copy_to_clipboard, "Скопировать для вставки в Word"),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            # Кнопки с текстом требуют запаса, иначе подпись упирается в край.
            button.ensurePolished()
            button.setMinimumWidth(
                button.fontMetrics().horizontalAdvance(text) + ds.spacing.xxl + 8
            )
            button.setMinimumHeight(max(button.fontMetrics().height() + 14, ds.spacing.xl + 6))
            button.setStyleSheet(
                f"QPushButton {{ padding-left: {ds.spacing.lg}px; "
                f"padding-right: {ds.spacing.lg}px; }}"
            )
            row.addWidget(button)
        row.addStretch(1)

        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.close)
        close_button.ensurePolished()
        close_button.setMinimumWidth(
            close_button.fontMetrics().horizontalAdvance("Закрыть") + ds.spacing.xxl + 8
        )
        close_button.setMinimumHeight(
            max(close_button.fontMetrics().height() + 14, ds.spacing.xl + 6)
        )
        row.addWidget(close_button)
        layout.addLayout(row)

    # ------------------------------------------------------------- экспорт

    def apply_theme(self, theme: str) -> None:
        """Переключает тему графика без пересоздания окна."""
        self.theme_name = theme
        self.canvas.set_theme(theme)

    def _default_stem(self) -> str:
        """Имя файла по заголовку графика, без недопустимых символов."""
        safe = "".join(
            character if character.isalnum() or character in " -_" else "_"
            for character in self.data.title
        ).strip()
        return safe or "chart"

    def export_png(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Сохранить график", f"{self._default_stem()}.png", "Изображение PNG (*.png)"
        )
        if not path:
            return
        image = render_chart(self.data, self.theme_name, EXPORT_WIDTH, EXPORT_HEIGHT)
        if not image.save(path, "PNG"):
            QMessageBox.warning(self, "Не удалось сохранить", f"Файл не записан:\n{path}")
            return
        self.saved_path = path
        QMessageBox.information(self, "Готово", f"График сохранён:\n{path}")

    def export_svg(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Сохранить график", f"{self._default_stem()}.svg",
            "Векторный рисунок SVG (*.svg)",
        )
        if not path:
            return
        # Размер берётся из холста: вектор сохраняет пропорции окна.
        width = max(self.canvas.width(), 320)
        height = max(self.canvas.height(), 240)
        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(self.canvas.size())
        generator.setViewBox(QRectF(0, 0, width, height))
        generator.setTitle(self.data.title)
        generator.setDescription(chart_caption(self.data))
        ds = design_system(self.theme_name)
        painter = QPainter(generator)
        try:
            ChartRenderer(self.data, ds.palette).render(painter, float(width), float(height))
        finally:
            painter.end()
        if not Path(path).exists():
            QMessageBox.warning(self, "Не удалось сохранить", f"Файл не записан:\n{path}")
            return
        self.saved_path = path
        QMessageBox.information(self, "Готово", f"График сохранён:\n{path}")

    def copy_to_clipboard(self) -> None:
        """Копирует график в буфер обмена - для вставки в Word или PowerPoint."""
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setPixmap(self.canvas.pixmap())
        QMessageBox.information(
            self, "Готово", "График скопирован. Вставьте его в Word или PowerPoint."
        )


__all__ = ["ChartCanvas", "ChartWindow"]
