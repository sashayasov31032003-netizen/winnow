"""Рисование графиков и экспорт.

Графики рисуются вручную через QPainter, а не берутся из готовой библиотеки.
Причина: нужен полный контроль над оформлением, чтобы графики совпадали с
дизайн-системой и корректно выглядели в обеих темах. Библиотека навязала бы свои
цвета, и тёмная тема получила бы белые прямоугольники - ровно та проблема,
которая уже была с диалогами.

Рендеринг отделён от виджета: одна и та же функция `render_chart` рисует и на
экране, и в файл при экспорте, поэтому экспортированная картинка не отличается
от того, что видно в окне.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

from winnow.stats.charts import ChartData
from winnow.ui.theme import Palette, design_system, series_color

EXPORT_WIDTH = 1400
EXPORT_HEIGHT = 900
MIN_WIDTH = 480
MIN_HEIGHT = 320


def nice_ticks(low: float, high: float, count: int = 6) -> list[float]:
    """Подбирает «круглые» отметки оси, покрывающие весь диапазон.

    Шаг берётся из ряда 1, 2, 5, умноженного на степень десяти, а обе границы
    округляются до кратных шагу: нижняя - вниз, верхняя - вверх. Без округления
    вверх последняя отметка оказывалась ниже максимума (например, 25 при
    максимуме 27), и крайние столбцы выходили за область построения.
    """
    if not math.isfinite(low) or not math.isfinite(high):
        return [0.0]
    if high <= low:
        # Вырожденный случай: все значения одинаковые. Показываем одну отметку.
        return [low]
    span = high - low
    raw_step = span / max(count, 1)
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    normalized = raw_step / magnitude
    if normalized <= 1.0:
        step = 1.0
    elif normalized <= 2.0:
        step = 2.0
    elif normalized <= 5.0:
        step = 5.0
    else:
        step = 10.0
    step *= magnitude
    if step <= 0 or not math.isfinite(step):
        return [low, high]

    start = math.floor(low / step) * step
    end = math.ceil(high / step) * step
    if end <= start:
        return [low, high]

    ticks: list[float] = []
    value = start
    # Ограничение на число отметок: при экстремальном диапазоне шаг может
    # оказаться слишком мелким, и ось превратилась бы в сплошную линию.
    while value <= end + step * 1e-9 and len(ticks) <= 200:
        ticks.append(0.0 if abs(value) < step * 1e-9 else value)
        value += step
    if not ticks:
        return [low, high]
    return ticks


def format_number(value: float, decimals: int = 3) -> str:
    """Компактная подпись числа: без хвостовых нулей."""
    if not math.isfinite(value):
        return ""
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1_000_000 or magnitude < 0.001:
        return f"{value:.2e}"
    if float(value).is_integer() and magnitude < 1e6:
        return f"{int(value)}"
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text or "0"


def _color(value: str, alpha: int = 255) -> QColor:
    color = QColor(value)
    color.setAlpha(alpha)
    return color


def _lighten(value: str, factor: float = 0.35) -> QColor:
    """Осветлённый вариант цвета для заливки столбцов."""
    color = QColor(value)
    return color.lighter(int(100 + factor * 100))


class ChartRenderer:
    """Рисует график на любом QPainter.

    Один экземпляр хранит данные графика и палитру, чтобы и экран, и экспорт
    рисовались одним кодом.
    """

    def __init__(self, data: ChartData, palette: Palette) -> None:
        self.data = data
        self.palette = palette
        self.p = palette

    # ------------------------------------------------------------------ вход

    def render(self, painter: QPainter, width: float, height: float) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(QRectF(0, 0, width, height), _color(self.p.surface))

        title_font = QFont()
        title_font.setPointSizeF(13.0)
        title_font.setBold(True)
        title_metrics = QFontMetricsF(title_font)

        label_font = QFont()
        label_font.setPointSizeF(9.5)
        label_metrics = QFontMetricsF(label_font)

        margin = 18.0
        title_height = 0.0
        if self.data.title:
            title_height = title_metrics.height() + 12.0

        # Подпись под графиком: поясняет, что именно показано.
        caption = self._caption()
        caption_height = 0.0
        if caption:
            caption_height = label_metrics.height() + 10.0

        plot = QRectF(
            margin + 60.0,
            margin + title_height + 10.0,
            max(width - (margin * 2 + 80.0), 10.0),
            # Нижний запас: подписи категорий (могут быть в две строки), затем
            # подпись оси X и только потом подпись под графиком. Раньше подпись
            # оси X рисовалась в той же полосе, что и подписи категорий, и они
            # накладывались друг на друга.
            max(height - (margin * 2 + title_height + caption_height + 66.0), 10.0),
        )

        if self.data.title:
            painter.setFont(title_font)
            painter.setPen(_color(self.p.text))
            painter.drawText(
                QRectF(margin, margin, width - margin * 2, title_metrics.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.data.title,
            )

        painter.setFont(label_font)
        dispatch = {
            "histogram": self._histogram,
            "boxplot": self._boxplot,
            "scatter": self._scatter,
            "bar": self._bars,
            "pie": self._pie,
            "line": self._line,
        }
        drawer = dispatch.get(self.data.kind)
        if drawer is None:
            painter.setPen(_color(self.p.text_muted))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Нет данных для графика")
        elif not self._has_data():
            painter.setPen(_color(self.p.text_muted))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Нет данных для графика")
        else:
            drawer(painter, plot, label_metrics)

        if caption:
            painter.setPen(_color(self.p.text_muted))
            painter.drawText(
                QRectF(margin, height - margin - label_metrics.height(),
                       width - margin * 2, label_metrics.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                caption,
            )

    # -------------------------------------------------------------- служебное

    def _caption(self) -> str:
        from winnow.stats.charts import chart_caption

        return chart_caption(self.data)

    def _has_data(self) -> bool:
        data = self.data
        if data.kind == "histogram":
            return bool(data.bin_counts)
        if data.kind == "boxplot":
            return bool(data.boxes)
        if data.kind == "scatter":
            return bool(data.points)
        if data.kind in ("bar", "pie"):
            return bool(data.values)
        return bool(data.line_y)

    def _draw_axes(
        self,
        painter: QPainter,
        plot: QRectF,
        y_low: float,
        y_high: float,
        label_metrics: QFontMetricsF,
        x_title: str = "",
        y_title: str = "",
    ) -> tuple[float, float]:
        """Рисует рамку, горизонтальную сетку и подписи оси Y.

        Возвращает границы по Y после «округления» до отметок: иначе столбцы
        упирались бы в верхнюю границу области.
        """
        ticks = nice_ticks(y_low, y_high)
        if len(ticks) < 2:
            ticks = [y_low, y_high if y_high > y_low else y_low + 1.0]
        low, high = ticks[0], ticks[-1]
        if high <= low:
            high = low + 1.0
        span = high - low

        def y_of(value: float) -> float:
            return plot.bottom() - (value - low) / span * plot.height()

        # Сетка: тонкие линии, чтобы не спорить с данными.
        painter.setPen(QPen(_color(self.p.border), 1.0))
        for tick in ticks:
            y = y_of(tick)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        # Рамка области построения.
        painter.setPen(QPen(_color(self.p.border_strong), 1.2))
        painter.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))
        painter.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

        # Подписи оси Y.
        painter.setPen(_color(self.p.text_muted))
        for tick in ticks:
            y = y_of(tick)
            painter.drawText(
                QRectF(plot.left() - 58.0, y - label_metrics.height() / 2, 52.0, label_metrics.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_number(tick),
            )

        if y_title:
            painter.save()
            painter.translate(14.0, plot.center().y())
            painter.rotate(-90.0)
            painter.setPen(_color(self.p.text_muted))
            painter.drawText(
                QRectF(-plot.height() / 2, -label_metrics.height() / 2, plot.height(), label_metrics.height()),
                Qt.AlignmentFlag.AlignCenter,
                y_title,
            )
            painter.restore()

        if x_title:
            # Подпись оси X ставится НИЖЕ подписей категорий, а не в той же
            # полосе: подписи категорий занимают до двух строк.
            painter.setPen(_color(self.p.text_muted))
            painter.drawText(
                QRectF(
                    plot.left(),
                    plot.bottom() + label_metrics.height() * 2.6,
                    plot.width(),
                    label_metrics.height(),
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                x_title,
            )
        return low, high

    # ------------------------------------------------------------ гистограмма

    def _histogram(self, painter: QPainter, plot: QRectF, label_metrics: QFontMetricsF) -> None:
        data = self.data
        top = max(data.bin_counts) * 1.12 if data.bin_counts else 1.0
        low, high = self._draw_axes(
            painter, plot, 0.0, top, label_metrics, data.x_label, data.y_label
        )
        span = high - low or 1.0
        count = len(data.bin_counts)
        width = plot.width() / max(count, 1)

        painter.setPen(QPen(_color(self.p.accent_pressed), 1.0))
        painter.setBrush(QBrush(_color(self.p.accent, 190)))
        for index, value in enumerate(data.bin_counts):
            height = (value - low) / span * plot.height()
            if height <= 0:
                continue
            bar = QRectF(
                plot.left() + index * width + 1.0,
                plot.bottom() - height,
                max(width - 2.0, 1.0),
                height,
            )
            painter.drawRect(bar)

        # Кривая нормального распределения поверх столбцов.
        if data.normal_curve:
            xs, ys = data.normal_curve
            if xs:
                x_low, x_high = data.bin_edges[0], data.bin_edges[-1]
                x_span = (x_high - x_low) or 1.0
                polygon = QPolygonF()
                for x, y in zip(xs, ys):
                    px = plot.left() + (x - x_low) / x_span * plot.width()
                    py = plot.bottom() - (y - low) / span * plot.height()
                    polygon.append(QPointF(px, py))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_color(self.p.danger), 2.0))
                painter.drawPolyline(polygon)

        self._draw_center_lines(painter, plot, low, high, label_metrics, data.bin_edges)

        # Подписи границ интервалов: только крайние и середина, иначе нечитаемо.
        painter.setPen(_color(self.p.text_muted))
        positions = [0, count // 2, count]
        for position in positions:
            if position >= len(data.bin_edges):
                continue
            value = data.bin_edges[position]
            x = plot.left() + (value - data.bin_edges[0]) / (
                (data.bin_edges[-1] - data.bin_edges[0]) or 1.0
            ) * plot.width()
            painter.drawText(
                QRectF(x - 40.0, plot.bottom() + 4.0, 80.0, label_metrics.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                format_number(value, 2),
            )

    def _draw_center_lines(
        self,
        painter: QPainter,
        plot: QRectF,
        low: float,
        high: float,
        label_metrics: QFontMetricsF,
        edges: list[float],
    ) -> None:
        """Показывает среднее и медиану вертикальными линиями."""
        if not edges or (self.data.mean_value is None and self.data.median_value is None):
            return
        span = (high - low) or 1.0
        x_low, x_high = edges[0], edges[-1]
        x_span = (x_high - x_low) or 1.0

        marks = [
            (self.data.mean_value, self.p.success, "Среднее"),
            (self.data.median_value, self.p.warning, "Медиана"),
        ]
        row = 0
        previous_x: list[float] = []
        for value, color, label in marks:
            if value is None:
                continue
            x = plot.left() + (value - x_low) / x_span * plot.width()
            painter.setPen(QPen(_color(color), 1.8, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

            text = f"{label}: {format_number(value, 2)}"
            # Ширина подписи считается по метрикам шрифта: фиксированные 90 точек
            # обрезали длинные числа вроде «среднее: 47571».
            text_width = label_metrics.horizontalAdvance(text) + 8.0
            # Если подпись не помещается справа от линии, рисуем её слева.
            if x + 6.0 + text_width > plot.right():
                box_left = x - 6.0 - text_width
            else:
                box_left = x + 6.0
            box_left = max(box_left, plot.left() + 2.0)

            # Близкие линии (среднее и медиана почти совпали) получают разные
            # строки: иначе вторая подпись терялась бы.
            if any(abs(x - previous) < text_width for previous in previous_x):
                row += 1
            else:
                row = 0
            previous_x.append(x)

            painter.setPen(_color(self.p.text_muted))
            painter.drawText(
                QRectF(
                    box_left,
                    plot.top() + 2.0 + row * (label_metrics.height() + 1.0),
                    text_width,
                    label_metrics.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                text,
            )

    # ------------------------------------------------------------ ящик с усами

    def _boxplot(self, painter: QPainter, plot: QRectF, label_metrics: QFontMetricsF) -> None:
        data = self.data
        box = data.boxes[0]
        all_values = [box["minimum"], box["maximum"], box["mean"]] + data.outliers
        low = min(all_values)
        high = max(all_values)
        padding = (high - low) * 0.08 or 1.0
        low, high = self._draw_axes(
            painter, plot, low - padding, high + padding, label_metrics,
            self.data.x_label, self.data.y_label,
        )
        span = (high - low) or 1.0

        def y_of(value: float) -> float:
            return plot.bottom() - (value - low) / span * plot.height()

        center_x = plot.center().x()
        box_width = min(plot.width() * 0.18, 120.0)
        left = center_x - box_width / 2

        # Усы: вертикальная линия и поперечины на концах.
        painter.setPen(QPen(_color(self.p.accent_pressed), 1.6))
        painter.drawLine(QPointF(center_x, y_of(box["upper_whisker"])),
                         QPointF(center_x, y_of(box["lower_whisker"])))
        for value in (box["upper_whisker"], box["lower_whisker"]):
            y = y_of(value)
            painter.drawLine(QPointF(center_x - box_width * 0.3, y),
                             QPointF(center_x + box_width * 0.3, y))

        # Ящик: от Q1 до Q3, медиана внутри.
        painter.setBrush(QBrush(_color(self.p.accent, 70)))
        painter.setPen(QPen(_color(self.p.accent_pressed), 1.6))
        painter.drawRect(QRectF(left, y_of(box["q3"]), box_width,
                                y_of(box["q1"]) - y_of(box["q3"])))
        painter.setPen(QPen(_color(self.p.warning), 2.4))
        painter.drawLine(QPointF(left, y_of(box["median"])),
                         QPointF(left + box_width, y_of(box["median"])))

        # Среднее - отдельным знаком, чтобы отличать от медианы.
        mean_y = y_of(box["mean"])
        painter.setPen(QPen(_color(self.p.success), 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = 5.0
        painter.drawLine(QPointF(center_x - radius, mean_y), QPointF(center_x + radius, mean_y))
        painter.drawLine(QPointF(center_x, mean_y - radius), QPointF(center_x, mean_y + radius))

        # Выбросы: кружки, как в SPSS.
        painter.setPen(QPen(_color(self.p.danger), 1.2))
        painter.setBrush(QBrush(_color(self.p.danger, 90)))
        for value in data.outliers:
            painter.drawEllipse(QPointF(center_x, y_of(value)), 3.6, 3.6)

        # Пояснение обозначений: без него знаки неоднозначны.
        painter.setPen(_color(self.p.text_muted))
        legend = [
            ("Медиана", self.p.warning),
            ("Среднее", self.p.success),
            ("Выброс", self.p.danger),
        ]
        x = plot.left() + 6.0
        y = plot.top() + 4.0
        for label, color in legend:
            painter.setPen(QPen(_color(color), 2.4))
            painter.drawLine(QPointF(x, y + label_metrics.height() / 2),
                             QPointF(x + 16.0, y + label_metrics.height() / 2))
            painter.setPen(_color(self.p.text_muted))
            painter.drawText(
                QRectF(x + 20.0, y, 90.0, label_metrics.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            y += label_metrics.height() + 2.0

    # --------------------------------------------------------------- рассеяние

    def _scatter(self, painter: QPainter, plot: QRectF, label_metrics: QFontMetricsF) -> None:
        data = self.data
        xs = [point.x for point in data.points]
        ys = [point.y for point in data.points]
        x_low, x_high = min(xs), max(xs)
        y_low, y_high = min(ys), max(ys)
        x_pad = (x_high - x_low) * 0.05 or 1.0
        y_pad = (y_high - y_low) * 0.05 or 1.0

        low, high = self._draw_axes(
            painter, plot, y_low - y_pad, y_high + y_pad, label_metrics,
            data.x_label, data.y_label,
        )
        # По X сетку рисуем отдельно: _draw_axes отвечает только за Y.
        x_ticks = nice_ticks(x_low - x_pad, x_high + x_pad)
        x_min = x_ticks[0] if x_ticks else x_low - x_pad
        x_max = x_ticks[-1] if x_ticks else x_high + x_pad
        x_span = (x_max - x_min) or 1.0
        y_span = (high - low) or 1.0

        def px(value: float) -> float:
            return plot.left() + (value - x_min) / x_span * plot.width()

        def py(value: float) -> float:
            return plot.bottom() - (value - low) / y_span * plot.height()

        painter.setPen(QPen(_color(self.p.border), 1.0))
        for tick in x_ticks:
            x = px(tick)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(_color(self.p.text_muted))
            painter.drawText(
                QRectF(x - 40.0, plot.bottom() + 4.0, 80.0, label_metrics.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                format_number(tick, 2),
            )
            painter.setPen(QPen(_color(self.p.border), 1.0))

        # Линия регрессии под точками: точки важнее, они должны быть сверху.
        if data.regression is not None:
            slope, intercept = data.regression
            painter.setPen(QPen(_color(self.p.danger), 2.0))
            painter.drawLine(
                QPointF(px(x_min), py(slope * x_min + intercept)),
                QPointF(px(x_max), py(slope * x_max + intercept)),
            )

        painter.setPen(QPen(_color(self.p.accent_pressed), 1.0))
        painter.setBrush(QBrush(_color(self.p.accent, 150)))
        for point in data.points:
            painter.drawEllipse(QPointF(px(point.x), py(point.y)), 3.2, 3.2)

    # ------------------------------------------------------- столбцы и круг

    def _bars(self, painter: QPainter, plot: QRectF, label_metrics: QFontMetricsF) -> None:
        data = self.data
        top = max(data.values) * 1.12 if data.values else 1.0
        low, high = self._draw_axes(
            painter, plot, 0.0, top, label_metrics, data.x_label, data.y_label
        )
        span = (high - low) or 1.0
        count = len(data.values)
        slot = plot.width() / max(count, 1)
        width = min(slot * 0.72, 110.0)

        for index, value in enumerate(data.values):
            height = (value - low) / span * plot.height()
            center = plot.left() + slot * (index + 0.5)
            bar = QRectF(center - width / 2, plot.bottom() - height, width, max(height, 0.0))
            color = _color(series_color(index))
            painter.setPen(QPen(color.darker(115), 1.0))
            painter.setBrush(QBrush(color))
            painter.drawRect(bar)

            # Значение над столбцом: по графику число не прочитать, а в отчёте
            # оно нужно.
            painter.setPen(_color(self.p.text))
            painter.drawText(
                QRectF(center - slot / 2, bar.top() - label_metrics.height() - 2,
                       slot, label_metrics.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                format_number(value, 0),
            )

            # Подпись категории под осью, при необходимости - в две строки.
            painter.setPen(_color(self.p.text_muted))
            text = data.categories[index] if index < len(data.categories) else ""
            painter.drawText(
                QRectF(center - slot / 2, plot.bottom() + 6.0, slot, label_metrics.height() * 2.2),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                | int(Qt.TextFlag.TextWordWrap),
                text,
            )

    def _pie(self, painter: QPainter, plot: QRectF, label_metrics: QFontMetricsF) -> None:
        data = self.data
        total = sum(data.values)
        if total <= 0:
            return
        # Круг слева, легенда справа: так подписи не наезжают на секторы.
        size = min(plot.height(), plot.width() * 0.55)
        circle = QRectF(
            plot.left() + 10.0,
            plot.center().y() - size / 2,
            size,
            size,
        )
        start = 90 * 16  # начинаем сверху, по часовой стрелке

        for index, value in enumerate(data.values):
            span = int(round(360 * 16 * value / total))
            color = _color(series_color(index))
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(_color(self.p.surface), 1.5))
            painter.drawPie(circle, start, -span)

            # Доля внутри сектора, если сектор достаточно большой.
            percent = 100.0 * value / total
            if percent >= 6.0:
                middle = math.radians((start - span / 2) / 16.0)
                radius = size / 2 * 0.62
                center = circle.center()
                x = center.x() + math.cos(middle) * radius
                y = center.y() - math.sin(middle) * radius
                painter.setPen(_color("#ffffff"))
                painter.drawText(
                    QRectF(x - 40.0, y - label_metrics.height() / 2, 80.0, label_metrics.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{percent:.1f}%",
                )
            start -= span

        # Легенда с категориями и абсолютными частотами.
        legend_x = circle.right() + 26.0
        legend_y = circle.top() + 4.0
        line_height = label_metrics.height() + 4.0
        painter.setPen(_color(self.p.text))
        for index, (category, value) in enumerate(zip(data.categories, data.values)):
            if legend_y + line_height > plot.bottom():
                painter.setPen(_color(self.p.text_muted))
                painter.drawText(
                    QRectF(legend_x, legend_y, 160.0, line_height),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    "…",
                )
                break
            color = _color(series_color(index))
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(115), 1.0))
            painter.drawRect(QRectF(legend_x, legend_y + 3.0, 12.0, 12.0))
            painter.setPen(_color(self.p.text))
            painter.drawText(
                QRectF(legend_x + 20.0, legend_y, 240.0, line_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{category} — {format_number(value, 0)} ({100.0 * value / total:.1f}%)",
            )
            legend_y += line_height

    # ----------------------------------------------------------- линия средних

    def _line(self, painter: QPainter, plot: QRectF, label_metrics: QFontMetricsF) -> None:
        data = self.data
        values = list(data.line_y)
        errors = list(data.line_errors)
        low_value = min([value - error for value, error in zip(values, errors)] or [0.0])
        high_value = max([value + error for value, error in zip(values, errors)] or [1.0])
        padding = (high_value - low_value) * 0.12 or 1.0
        low, high = self._draw_axes(
            painter, plot, low_value - padding, high_value + padding, label_metrics,
            data.x_label, data.y_label,
        )
        span = (high - low) or 1.0
        count = len(values)
        slot = plot.width() / max(count - 1, 1) if count > 1 else plot.width()

        def px(index: int) -> float:
            return plot.left() + (index * slot if count > 1 else plot.width() / 2)

        def py(value: float) -> float:
            return plot.bottom() - (value - low) / span * plot.height()

        # Вертикальные отрезки - стандартные ошибки среднего.
        painter.setPen(QPen(_color(self.p.border_strong), 1.2))
        for index, (value, error) in enumerate(zip(values, errors)):
            x = px(index)
            painter.drawLine(QPointF(x, py(value - error)), QPointF(x, py(value + error)))
            painter.drawLine(QPointF(x - 5.0, py(value + error)), QPointF(x + 5.0, py(value + error)))
            painter.drawLine(QPointF(x - 5.0, py(value - error)), QPointF(x + 5.0, py(value - error)))

        polygon = QPolygonF([QPointF(px(index), py(value)) for index, value in enumerate(values)])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(self.p.accent), 2.2))
        painter.drawPolyline(polygon)

        painter.setPen(QPen(_color(self.p.accent_pressed), 1.0))
        painter.setBrush(QBrush(_color(self.p.accent)))
        for index, value in enumerate(values):
            painter.drawEllipse(QPointF(px(index), py(value)), 4.0, 4.0)

        painter.setPen(_color(self.p.text_muted))
        for index, category in enumerate(data.line_x):
            painter.drawText(
                QRectF(px(index) - slot / 2, plot.bottom() + 6.0, slot, label_metrics.height() * 2.2),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                | int(Qt.TextFlag.TextWordWrap),
                str(category),
            )


def render_chart(
    data: ChartData, theme: str, width: int, height: int
) -> QImage:
    """Рисует график в изображение заданного размера."""
    image = QImage(int(width), int(height), QImage.Format.Format_ARGB32_Premultiplied)
    ds = design_system(theme)
    image.fill(_color(ds.palette.surface))
    painter = QPainter(image)
    try:
        ChartRenderer(data, ds.palette).render(painter, width, height)
    finally:
        painter.end()
    return image


def render_chart_pixmap(data: ChartData, theme: str, width: float, height: float) -> QPixmap:
    """Рисует график в пиксмап для показа на экране."""
    if width <= 0 or height <= 0:
        width, height = MIN_WIDTH, MIN_HEIGHT
    image = render_chart(data, theme, int(width), int(height))
    return QPixmap.fromImage(image)


__all__ = [
    "EXPORT_HEIGHT",
    "EXPORT_WIDTH",
    "ChartRenderer",
    "format_number",
    "nice_ticks",
    "render_chart",
    "render_chart_pixmap",
]
