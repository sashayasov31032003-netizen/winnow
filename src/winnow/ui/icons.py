"""Иконки панели инструментов, нарисованные кодом.

Почему не файлы: набор иконок это либо зависимость, либо несколько сотен
килобайт, либо проблема с лицензией. Простые контурные иконки рисуются
средствами Qt за доли миллисекунды, всегда совпадают по цвету с темой и не
требуют поставки ресурсов.

Иконки намеренно простые и «линейные»: в интерфейсе статистического пакета они
не должны привлекать внимание, их задача - помочь найти нужный пункт.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

SIZE = 20


def _strokes(kind: str) -> list[QPainterPath]:
    """Возвращает контуры иконки в системе координат 20x20 (линии)."""
    paths: list[QPainterPath] = []

    if kind == "open":
        path = QPainterPath()
        path.moveTo(4, 5)
        path.lineTo(8, 5)
        path.lineTo(10, 7)
        path.lineTo(16, 7)
        path.lineTo(16, 15)
        path.lineTo(4, 15)
        path.closeSubpath()
        paths.append(path)

    elif kind == "sheet":
        path = QPainterPath()
        path.addRect(QRectF(5, 3, 10, 14))
        for offset in (5.0, 8.0, 11.0):
            line = QPainterPath()
            line.moveTo(7, 3 + offset - 1)
            line.lineTo(13, 3 + offset - 1)
            paths.append(line)
        paths.append(path)

    elif kind == "grid":
        path = QPainterPath()
        path.addRect(QRectF(4, 5, 12, 10))
        for x in (8.0, 12.0):
            line = QPainterPath()
            line.moveTo(x, 5)
            line.lineTo(x, 15)
            paths.append(line)
        line = QPainterPath()
        line.moveTo(4, 10)
        line.lineTo(16, 10)
        paths.append(line)
        paths.append(path)

    elif kind == "bars":
        for index, height in enumerate((5.0, 9.0, 13.0, 7.0)):
            bar = QPainterPath()
            bar.addRect(QRectF(4 + index * 3.2, 16 - height, 2.0, height))
            paths.append(bar)

    elif kind == "curve":
        path = QPainterPath()
        path.moveTo(3, 15)
        path.cubicTo(QPointF(7, 15), QPointF(7, 5), QPointF(10, 5))
        path.cubicTo(QPointF(13, 5), QPointF(13, 15), QPointF(17, 15))
        paths.append(path)

    elif kind == "scatter":
        dots = QPainterPath()
        for x, y in ((6.0, 13.0), (9.0, 10.0), (11.5, 12.0), (14.0, 6.0), (7.5, 8.0)):
            dots.addEllipse(QPointF(x, y), 1.4, 1.4)
        paths.append(dots)

    elif kind == "export":
        page = QPainterPath()
        page.moveTo(4, 4)
        page.lineTo(12, 4)
        page.lineTo(12, 12)
        page.lineTo(4, 12)
        page.closeSubpath()
        paths.append(page)
        arrow = QPainterPath()
        arrow.moveTo(12, 13)
        arrow.lineTo(16, 13)
        arrow.moveTo(14, 11)
        arrow.lineTo(16, 13)
        arrow.lineTo(14, 15)
        paths.append(arrow)

    elif kind == "theme":
        circle = QPainterPath()
        circle.addEllipse(QPointF(10, 10), 5.5, 5.5)
        paths.append(circle)
        cut = QPainterPath()
        cut.moveTo(10, 4.5)
        cut.cubicTo(QPointF(13.5, 5.5), QPointF(13.5, 14.5), QPointF(10, 15.5))
        paths.append(cut)

    elif kind == "help":
        circle = QPainterPath()
        circle.addEllipse(QPointF(10, 10), 6.5, 6.5)
        paths.append(circle)
        question = QPainterPath()
        question.moveTo(8, 8)
        question.cubicTo(QPointF(10, 5.5), QPointF(12.5, 9), QPointF(10, 10.5))
        question.lineTo(10, 12.5)
        paths.append(question)

    elif kind == "table":
        path = QPainterPath()
        path.addRect(QRectF(4, 4, 12, 12))
        for offset in (8.0, 12.0):
            line = QPainterPath()
            line.moveTo(4, offset)
            line.lineTo(16, offset)
            paths.append(line)
        paths.append(path)

    elif kind == "clear":
        # Корзина: крышка с ручкой, корпус и две полосы внутри.
        lid = QPainterPath()
        lid.moveTo(4, 6)
        lid.lineTo(16, 6)
        handle = QPainterPath()
        handle.moveTo(8, 6)
        handle.lineTo(8, 4)
        handle.lineTo(12, 4)
        handle.lineTo(12, 6)
        body = QPainterPath()
        body.moveTo(6, 6)
        body.lineTo(7, 16)
        body.lineTo(13, 16)
        body.lineTo(14, 6)
        paths.extend([lid, handle, body])
        for offset in (9.5, 11.5):
            stripe = QPainterPath()
            stripe.moveTo(offset, 8.5)
            stripe.lineTo(offset, 13.5)
            paths.append(stripe)

    else:  # неизвестный тип: пустой квадрат вместо сюрприза
        path = QPainterPath()
        path.addRect(QRectF(5, 5, 10, 10))
        paths.append(path)

    return paths


def make_icon(kind: str, color: str, size: int = SIZE) -> QIcon:
    """Рисует иконку указанным цветом."""
    scale = 2  # рисуем вдвое крупнее и уменьшаем - так линии выглядят гладко
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(scale * size / SIZE, scale * size / SIZE)

    pen = QPen(QColor(color))
    pen.setWidthF(1.4)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    for path in _strokes(kind):
        painter.drawPath(path)
    painter.end()

    return QIcon(pixmap)


def toolbar_icons(color: str) -> dict[str, QIcon]:
    """Набор иконок для панели инструментов в указанном цвете."""
    return {
        "open": make_icon("open", color),
        "sheet": make_icon("sheet", color),
        "bars": make_icon("bars", color),
        "curve": make_icon("curve", color),
        "grid": make_icon("grid", color),
        "scatter": make_icon("scatter", color),
        "export": make_icon("export", color),
        "table": make_icon("table", color),
        "clear": make_icon("clear", color),
    }


# --------------------------------------------------------- логотип программы

# Цвета повторяют акцентный цвет темы: иконка и интерфейс должны выглядеть как
# одно целое, иначе программа кажется собранной из чужих частей.
LOGO_TOP = "#2a7de1"
LOGO_BOTTOM = "#155099"
LOGO_MARK = "#ffffff"

# Размеры, которые нужны Windows: панель задач, список файлов, крупный значок.
LOGO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw_logo(painter: QPainter, size: float) -> None:
    """Рисует логотип Winnow в квадрате со стороной `size`.

    Логотип - три растущих столбца и ломаная линия над ними: это и данные, и
    рост. Ничего лишнего: значок должен читаться и в 16 точках, где любая
    мелкая деталь превращается в грязь.

    Координаты задаются в сотых долях стороны квадрата: так рисунок не зависит
    от размера, и один и тот же код годится и для значка в 16 точек, и для
    картинки в 256.
    """
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    unit = size / 100.0

    # Фон: скруглённый квадрат с плавным переходом цвета сверху вниз.
    gradient = QLinearGradient(0.0, 0.0, 0.0, size)
    gradient.setColorAt(0.0, QColor(LOGO_TOP))
    gradient.setColorAt(1.0, QColor(LOGO_BOTTOM))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    radius = 23 * unit
    painter.drawRoundedRect(QRectF(2 * unit, 2 * unit, 96 * unit, 96 * unit), radius, radius)

    # Столбцы: растут слева направо, стоят на одной линии.
    baseline = 79.0
    painter.setBrush(QColor(LOGO_MARK))
    for left, height in ((19.0, 22.0), (42.0, 33.0), (65.0, 44.0)):
        top = baseline - height
        painter.drawRoundedRect(
            QRectF(left * unit, top * unit, 16 * unit, height * unit),
            4 * unit,
            4 * unit,
        )

    # Ломаная линия и точка на её конце - «тренд». В мелких значках линия
    # превращается в серую полосу, поэтому там она не рисуется вовсе.
    if size >= 24:
        pen = QPen(QColor(LOGO_MARK))
        pen.setWidthF(max(3.0, 5.0 * unit))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        trend = QPainterPath()
        trend.moveTo(27 * unit, 48 * unit)
        trend.lineTo(50 * unit, 37 * unit)
        trend.lineTo(73 * unit, 24 * unit)
        painter.drawPath(trend)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(LOGO_MARK))
        painter.drawEllipse(QPointF(73 * unit, 24 * unit), 7.5 * unit, 7.5 * unit)


def logo_pixmap(size: int) -> QPixmap:
    """Значок программы указанного размера."""
    # Рисуем вчетверо крупнее и уменьшаем: так края получаются гладкими даже на
    # маленьких размерах, где Windows не применяет сглаживание.
    scale = 4
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_logo(painter, float(size * scale))
    painter.end()
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def app_icon() -> QIcon:
    """Значок программы для окна, панели задач и ярлыка.

    В значок кладутся все нужные размеры: Windows выбирает подходящий сама, и
    без этого в панели задач появляется размытая картинка, увеличенная из
    маленькой.
    """
    icon = QIcon()
    for size in LOGO_SIZES:
        icon.addPixmap(logo_pixmap(size))
    return icon


__all__ = ["app_icon", "draw_logo", "logo_pixmap", "make_icon", "toolbar_icons"]
