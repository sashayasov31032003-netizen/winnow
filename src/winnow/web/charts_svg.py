"""Рисование графиков в SVG на сервере.

Почему SVG, а не рисование в браузере: данные для графиков уже считает движок
(`stats/charts.py`), и он же используется настольной версией. Серверный рендерер
избавляет от второго набора формул в JavaScript, а готовый SVG одинаково
показывается в интерфейсе, скачивается файлом и вставляется в отчёт Word/HTML.

Оформление простое и намеренно строгое: это статистика, сетка и числа важнее
украшений.
"""

from __future__ import annotations

import html
import math

WIDTH = 720
HEIGHT = 420
PAD_LEFT = 64
PAD_RIGHT = 24
PAD_TOP = 44
PAD_BOTTOM = 56

PAPER = "#ffffff"
INK = "#101828"
MUTED = "#667085"
GRID = "#e3e9f2"
ACCENT = "#2563eb"
ACCENT_SOFT = "#a8c4f5"
WARN = "#b54708"


def _esc(text: object) -> str:
    return html.escape(str(text))


def _nice_max(value: float) -> float:
    """Верхняя граница оси: круглое число не меньше значения."""
    if value <= 0 or not math.isfinite(value):
        return 1.0
    exponent = 10 ** math.floor(math.log10(value))
    for factor in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        candidate = factor * exponent
        if candidate >= value:
            return candidate
    return 10 * exponent


def _frame(title: str, extra: str = "") -> list[str]:
    """Общая рамка: фон, заголовок и место под подписи осей."""
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="100%" height="auto" role="img">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{PAPER}"/>',
        f'<text x="{WIDTH / 2}" y="24" text-anchor="middle" font-family="Inter, Segoe UI, sans-serif" '
        f'font-size="15" font-weight="600" fill="{INK}">{_esc(title)}</text>',
        extra,
    ]


def _axes(y_max: float, y_label: str, ticks: int = 5) -> list[str]:
    """Оси, сетка и подписи по вертикали."""
    parts: list[str] = []
    left, right = PAD_LEFT, WIDTH - PAD_RIGHT
    top, bottom = PAD_TOP, HEIGHT - PAD_BOTTOM
    for index in range(ticks + 1):
        value = y_max * index / ticks
        y = bottom - (bottom - top) * index / ticks
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="Inter, Segoe UI, sans-serif" '
            f'font-size="11" fill="{MUTED}">{_esc(_format_tick(value))}</text>'
        )
    parts.append(
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{MUTED}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{MUTED}" stroke-width="1"/>'
    )
    if y_label:
        parts.append(
            f'<text x="16" y="{(top + bottom) / 2:.1f}" text-anchor="middle" '
            f'transform="rotate(-90 16 {(top + bottom) / 2:.1f})" '
            f'font-family="Inter, Segoe UI, sans-serif" font-size="11" fill="{MUTED}">{_esc(y_label)}</text>'
        )
    return parts


def _format_tick(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", " ")
    if abs(value - round(value)) < 1e-9:
        return f"{round(value)}"
    return f"{value:.1f}".replace(".", ",")


def _x_labels(labels: list[str], positions: list[float], rotate: bool = False) -> list[str]:
    """Подписи по горизонтали: длинные — наклоняются, чтобы не наезжали."""
    parts: list[str] = []
    bottom = HEIGHT - PAD_BOTTOM
    for label, x in zip(labels, positions):
        short = label if len(label) <= 16 else label[:15] + "…"
        if rotate:
            parts.append(
                f'<text x="{x:.1f}" y="{bottom + 16}" text-anchor="end" '
                f'transform="rotate(-35 {x:.1f} {bottom + 16})" '
                f'font-family="Inter, Segoe UI, sans-serif" font-size="10" fill="{MUTED}">{_esc(short)}</text>'
            )
        else:
            parts.append(
                f'<text x="{x:.1f}" y="{bottom + 18}" text-anchor="middle" '
                f'font-family="Inter, Segoe UI, sans-serif" font-size="10" fill="{MUTED}">{_esc(short)}</text>'
            )
    return parts


def render_histogram(data) -> str:
    counts = list(data.bin_counts) or [0]
    y_max = _nice_max(max(counts))
    parts = _frame(data.title) + _axes(y_max, data.y_label or "Частота")
    left, right = PAD_LEFT, WIDTH - PAD_RIGHT
    top, bottom = PAD_TOP, HEIGHT - PAD_BOTTOM
    width = (right - left) / max(1, len(counts))
    positions: list[float] = []
    edges = list(data.bin_edges)
    for index, count in enumerate(counts):
        x = left + width * index
        height = (bottom - top) * (count / y_max if y_max else 0)
        parts.append(
            f'<rect x="{x + 1:.1f}" y="{bottom - height:.1f}" width="{max(1.0, width - 2):.1f}" '
            f'height="{height:.1f}" fill="{ACCENT_SOFT}" stroke="{ACCENT}" stroke-width="0.8"/>'
        )
        centre = x + width / 2
        positions.append(centre)
        if len(counts) <= 12 and index < len(edges) - 1:
            parts.append(
                f'<text x="{centre:.1f}" y="{bottom - height - 4:.1f}" text-anchor="middle" '
                f'font-family="Inter, Segoe UI, sans-serif" font-size="10" fill="{INK}">{count}</text>'
            )

    labels = [
        f"{_format_tick(edges[index])}–{_format_tick(edges[index + 1])}"
        for index in range(min(len(counts), max(0, len(edges) - 1)))
    ]
    # Когда интервалов много, подписи не помещаются: подписывается каждый
    # второй, и только нижней границей - иначе текст наезжает друг на друга.
    if len(labels) > 6:
        labels = [
            _format_tick(edges[index]) if index % 2 == 0 else ""
            for index in range(len(labels))
        ]
    parts += _x_labels(labels, positions, rotate=len(labels) > 6)

    curve = data.normal_curve
    if curve:
        xs, ys = curve
        if xs and ys:
            peak = max(ys) or 1.0
            points = []
            for x_value, y_value in zip(xs, ys):
                if edges and edges[-1] > edges[0]:
                    relative = (x_value - edges[0]) / (edges[-1] - edges[0])
                else:
                    relative = 0.0
                x = left + (right - left) * min(1.0, max(0.0, relative))
                y = bottom - (bottom - top) * (y_value / peak) * (max(counts) / y_max if y_max else 0)
                points.append(f"{x:.1f},{y:.1f}")
            parts.append(
                f'<polyline points="{" ".join(points)}" fill="none" stroke="{WARN}" '
                f'stroke-width="1.6" stroke-dasharray="5 3"/>'
            )
            parts.append(
                f'<text x="{right - 4}" y="{top + 12}" text-anchor="end" '
                f'font-family="Inter, Segoe UI, sans-serif" font-size="10" fill="{WARN}">'
                f"нормальное распределение</text>"
            )

    for value, label in ((data.mean_value, "среднее"), (data.median_value, "медиана")):
        if value is None or not edges or edges[-1] <= edges[0]:
            continue
        relative = (value - edges[0]) / (edges[-1] - edges[0])
        if not 0 <= relative <= 1:
            continue
        x = left + (right - left) * relative
        colour = ACCENT if label == "среднее" else MUTED
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{colour}" '
            f'stroke-width="1.4" stroke-dasharray="4 3"/>'
        )
        # Метки ставятся на разной высоте: среднее и медиана часто рядом, и в
        # одну строку они наезжали друг на друга.
        offset = 12 if label == "среднее" else 28
        parts.append(
            f'<text x="{x + 4:.1f}" y="{top + offset}" font-family="Inter, Segoe UI, sans-serif" '
            f'font-size="10" fill="{colour}">{_esc(label)}</text>'
        )

    if data.x_label:
        parts.append(
            f'<text x="{(left + right) / 2:.1f}" y="{HEIGHT - 12}" text-anchor="middle" '
            f'font-family="Inter, Segoe UI, sans-serif" font-size="11" fill="{MUTED}">{_esc(data.x_label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_bars(data) -> str:
    values = list(data.values) or [0]
    y_max = _nice_max(max(values))
    parts = _frame(data.title) + _axes(y_max, data.y_label or "Частота")
    left, right = PAD_LEFT, WIDTH - PAD_RIGHT
    top, bottom = PAD_TOP, HEIGHT - PAD_BOTTOM
    step = (right - left) / max(1, len(values))
    bar_width = max(8.0, step * 0.62)
    positions: list[float] = []
    for index, value in enumerate(values):
        x = left + step * index + (step - bar_width) / 2
        height = (bottom - top) * (value / y_max if y_max else 0)
        parts.append(
            f'<rect x="{x:.1f}" y="{bottom - height:.1f}" width="{bar_width:.1f}" '
            f'height="{height:.1f}" fill="{ACCENT}" rx="3"/>'
        )
        positions.append(x + bar_width / 2)
        if len(values) <= 14:
            parts.append(
                f'<text x="{x + bar_width / 2:.1f}" y="{bottom - height - 5:.1f}" text-anchor="middle" '
                f'font-family="Inter, Segoe UI, sans-serif" font-size="10" fill="{INK}">{_format_tick(value)}</text>'
            )
    parts += _x_labels(list(data.categories), positions, rotate=len(positions) > 6)
    if data.x_label:
        parts.append(
            f'<text x="{(left + right) / 2:.1f}" y="{HEIGHT - 12}" text-anchor="middle" '
            f'font-family="Inter, Segoe UI, sans-serif" font-size="11" fill="{MUTED}">{_esc(data.x_label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_line(data) -> str:
    values = list(data.values) or [0]
    y_max = _nice_max(max(values))
    y_min = min(0.0, min(values))
    span = y_max - y_min or 1.0
    parts = _frame(data.title) + _axes(y_max, data.y_label or "Среднее")
    left, right = PAD_LEFT, WIDTH - PAD_RIGHT
    top, bottom = PAD_TOP, HEIGHT - PAD_BOTTOM
    step = (right - left) / max(1, len(values) - 1) if len(values) > 1 else 0
    points = []
    positions: list[float] = []
    for index, value in enumerate(values):
        x = left + step * index if len(values) > 1 else (left + right) / 2
        y = bottom - (bottom - top) * ((value - y_min) / span)
        points.append(f"{x:.1f},{y:.1f}")
        positions.append(x)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{ACCENT}"/>')
    if len(points) > 1:
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{ACCENT}" stroke-width="2"/>'
        )
    parts += _x_labels(list(data.categories), positions, rotate=len(positions) > 6)
    parts.append("</svg>")
    return "".join(parts)


def render_scatter(data) -> str:
    xs = [point.x for point in data.points]
    ys = [point.y for point in data.points]
    if not xs or not ys:
        return _empty_svg(data.title, "Нет данных для графика")
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_max == x_min:
        x_max = x_min + 1
    if y_max == y_min:
        y_max = y_min + 1
    left, right = PAD_LEFT, WIDTH - PAD_RIGHT
    top, bottom = PAD_TOP, HEIGHT - PAD_BOTTOM
    parts = _frame(data.title) + _axes(_nice_max(y_max), data.y_label)

    def to_x(value: float) -> float:
        return left + (right - left) * (value - x_min) / (x_max - x_min)

    def to_y(value: float) -> float:
        return bottom - (bottom - top) * (value - y_min) / (y_max - y_min)

    for point in data.points:
        parts.append(
            f'<circle cx="{to_x(point.x):.1f}" cy="{to_y(point.y):.1f}" r="3" '
            f'fill="{ACCENT}" fill-opacity="0.65"/>'
        )
    if data.regression is not None:
        slope, intercept = data.regression
        x1, x2 = x_min, x_max
        parts.append(
            f'<line x1="{to_x(x1):.1f}" y1="{to_y(slope * x1 + intercept):.1f}" '
            f'x2="{to_x(x2):.1f}" y2="{to_y(slope * x2 + intercept):.1f}" '
            f'stroke="{WARN}" stroke-width="1.8"/>'
        )
    if data.x_label:
        parts.append(
            f'<text x="{(left + right) / 2:.1f}" y="{HEIGHT - 12}" text-anchor="middle" '
            f'font-family="Inter, Segoe UI, sans-serif" font-size="11" fill="{MUTED}">{_esc(data.x_label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_boxes(data) -> str:
    boxes = list(data.boxes)
    if not boxes:
        return _empty_svg(data.title, "Нет данных для графика")
    def pick(box, *names, default=0.0):
        """Достаёт число из словаря статистик, не полагаясь на одно имя поля."""
        for name in names:
            if name in box:
                try:
                    return float(box[name])
                except (TypeError, ValueError):
                    continue
        return default

    low = min(pick(box, "lower_whisker", "low", "min") for box in boxes)
    high = max(pick(box, "upper_whisker", "high", "max") for box in boxes)
    if high == low:
        high = low + 1
    left, right = PAD_LEFT, WIDTH - PAD_RIGHT
    top, bottom = PAD_TOP, HEIGHT - PAD_BOTTOM
    parts = _frame(data.title) + _axes(_nice_max(high), data.y_label)

    def to_y(value: float) -> float:
        return bottom - (bottom - top) * (value - low) / (high - low)

    step = (right - left) / max(1, len(boxes))
    width = min(70.0, step * 0.5)
    positions: list[float] = []
    labels: list[str] = []
    for index, box in enumerate(boxes):
        centre = left + step * index + step / 2
        positions.append(centre)
        labels.append(str(box.get("label") or box.get("name") or ""))
        q1, median, q3 = pick(box, "q1"), pick(box, "median"), pick(box, "q3")
        low_v = pick(box, "lower_whisker", "low", "min")
        high_v = pick(box, "upper_whisker", "high", "max")
        parts.append(
            f'<line x1="{centre:.1f}" y1="{to_y(high_v):.1f}" x2="{centre:.1f}" y2="{to_y(q3):.1f}" '
            f'stroke="{MUTED}" stroke-width="1.2"/>'
        )
        parts.append(
            f'<line x1="{centre:.1f}" y1="{to_y(q1):.1f}" x2="{centre:.1f}" y2="{to_y(low_v):.1f}" '
            f'stroke="{MUTED}" stroke-width="1.2"/>'
        )
        for value in (high_v, low_v):
            parts.append(
                f'<line x1="{centre - width / 2:.1f}" y1="{to_y(value):.1f}" '
                f'x2="{centre + width / 2:.1f}" y2="{to_y(value):.1f}" stroke="{MUTED}" stroke-width="1.2"/>'
            )
        parts.append(
            f'<rect x="{centre - width / 2:.1f}" y="{to_y(q3):.1f}" width="{width:.1f}" '
            f'height="{max(1.0, to_y(q1) - to_y(q3)):.1f}" fill="{ACCENT_SOFT}" stroke="{ACCENT}"/>'
        )
        parts.append(
            f'<line x1="{centre - width / 2:.1f}" y1="{to_y(median):.1f}" '
            f'x2="{centre + width / 2:.1f}" y2="{to_y(median):.1f}" stroke="{INK}" stroke-width="2"/>'
        )
    parts += _x_labels(labels, positions, rotate=len(labels) > 5)
    parts.append("</svg>")
    return "".join(parts)


def render_pie(data) -> str:
    values = [max(0.0, float(value)) for value in (data.values or [])]
    total = sum(values)
    if total <= 0:
        return _empty_svg(data.title, "Нет данных для графика")
    cx, cy, radius = WIDTH / 2 - 60, PAD_TOP + 150, 120
    colours = ["#2563eb", "#60a5fa", "#a8c4f5", "#0e7490", "#f59e0b", "#b54708", "#7c3aed", "#059669"]
    parts = _frame(data.title)
    angle = -math.pi / 2
    for index, value in enumerate(values):
        share = value / total
        if share <= 0:
            continue
        end = angle + 2 * math.pi * share
        large = 1 if share > 0.5 else 0
        x1 = cx + radius * math.cos(angle)
        y1 = cy + radius * math.sin(angle)
        x2 = cx + radius * math.cos(end)
        y2 = cy + radius * math.sin(end)
        colour = colours[index % len(colours)]
        parts.append(
            f'<path d="M {cx:.1f} {cy:.1f} L {x1:.1f} {y1:.1f} '
            f'A {radius} {radius} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
            f'fill="{colour}" fill-opacity="0.9" stroke="#ffffff" stroke-width="1.5"/>'
        )
        angle = end

    for index, (label, value) in enumerate(zip(data.categories, values)):
        y = PAD_TOP + 20 + index * 20
        if y > HEIGHT - PAD_BOTTOM:
            break
        colour = colours[index % len(colours)]
        share = value / total * 100
        parts.append(
            f'<rect x="{WIDTH - 210}" y="{y - 9}" width="12" height="12" rx="3" fill="{colour}"/>'
        )
        text_value = f"{label if len(label) <= 22 else label[:21] + '…'} — {share:.1f}%".replace(".", ",")
        parts.append(
            f'<text x="{WIDTH - 192}" y="{y + 1}" font-family="Inter, Segoe UI, sans-serif" '
            f'font-size="11" fill="{INK}">{_esc(text_value)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _empty_svg(title: str, message: str) -> str:
    parts = _frame(title)
    parts.append(
        f'<text x="{WIDTH / 2}" y="{HEIGHT / 2}" text-anchor="middle" '
        f'font-family="Inter, Segoe UI, sans-serif" font-size="14" fill="{MUTED}">{_esc(message)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


#: Палитры графиков. Тёмная совпадает с токенами интерфейса, чтобы график не
#: выглядел белым листом в тёмной теме.
PALETTES = {
    "light": {
        "paper": "#ffffff",
        "ink": "#101828",
        "muted": "#667085",
        "grid": "#e3e9f2",
        "accent": "#2563eb",
        "accent_soft": "#a8c4f5",
        "warn": "#b54708",
    },
    "dark": {
        "paper": "#141922",
        "ink": "#e8edf6",
        "muted": "#aab6ca",
        "grid": "rgba(255, 255, 255, 0.12)",
        "accent": "#6b93ff",
        "accent_soft": "#2b3a56",
        "warn": "#f5b544",
    },
}


def set_theme(theme: str) -> None:
    """Переключает цвета рисования на выбранную тему."""
    global PAPER, INK, MUTED, GRID, ACCENT, ACCENT_SOFT, WARN
    colours = PALETTES.get(theme, PALETTES["light"])
    PAPER = colours["paper"]
    INK = colours["ink"]
    MUTED = colours["muted"]
    GRID = colours["grid"]
    ACCENT = colours["accent"]
    ACCENT_SOFT = colours["accent_soft"]
    WARN = colours["warn"]


RENDERERS = {
    "histogram": render_histogram,
    "bar": render_bars,
    "pie": render_pie,
    "boxplot": render_boxes,
    "scatter": render_scatter,
    "line": render_line,
}


def render(data, theme: str = "light") -> str:
    """Рисует график по данным движка в оформлении выбранной темы."""
    set_theme(theme)
    renderer = RENDERERS.get(data.kind)
    if renderer is None:
        return _empty_svg(data.title, f"График «{data.kind}» пока не рисуется в вебе")
    return renderer(data)


__all__ = ["RENDERERS", "render"]
