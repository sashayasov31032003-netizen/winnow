"""HTML-вывод результатов.

Используется и в Qt-Viewer (QTextBrowser умеет HTML), и для сохранения отчёта
в файл. Один рендерер на два применения - меньше расхождений между тем, что
пользователь видит на экране, и тем, что он отправляет коллеге.
"""

from __future__ import annotations

import html
from typing import Any

from winnow.core.formatting import num
from winnow.stats.result import Result, Table

# Оформление вывода задаётся ТОЛЬКО через css_from_theme: он собирается из
# дизайн-токенов темы, поэтому тёмная тема получается сама собой. Отдельный
# статический набор стилей здесь раньше лежал и не использовался - правки в нём
# ни на что не влияли, что легко принять за работающий код.


def css_from_theme(theme: str = "light") -> str:
    """Собирает CSS вывода из дизайн-токенов.

    Нужно, чтобы таблицы результатов выглядели частью интерфейса, а не
    «вставкой из интернета»: те же цвета, шрифты и скругления, что и в окне.
    """
    from winnow.ui.theme import design_system

    ds = design_system(theme)
    p, t = ds.palette, ds.typography
    # В окне вывода шрифт на пару пунктов мельче интерфейсного: таблицы
    # статистики широкие, и крупный текст заставляет заголовки переноситься по
    # одной букве, что делает таблицу нечитаемой.
    base = max(8, t.size_base - 2)
    small = max(7, t.size_small - 2)
    return f"""
body {{
    font-family: "{t.family}", "DejaVu Sans", sans-serif;
    font-size: {t.pt(base)};
    color: {p.text};
    background: {p.surface};
    margin: 0;
    padding: {ds.spacing.sm}px {ds.spacing.md}px;
}}
h1 {{ font-size: {t.pt(base + 6)}; font-weight: 700; margin: 0 0 {ds.spacing.md}px 0; }}
h2 {{ font-size: {t.pt(base + 3)}; font-weight: 600; margin: {ds.spacing.lg}px 0 {ds.spacing.xs}px 0;
     color: {p.text}; }}
h3 {{ font-size: {t.pt(base + 1)}; font-weight: 600; margin: {ds.spacing.sm}px 0 {ds.spacing.xxs}px 0;
     color: {p.text_muted}; }}
table {{ border-collapse: collapse;
        margin: {ds.spacing.xs}px 0 {ds.spacing.md}px 0; }}
th, td {{ border: 1px solid {p.border}; padding: 2px {ds.spacing.xs + 2}px; vertical-align: top;
         white-space: nowrap; }}
th {{ background: {p.surface_alt}; font-weight: 600; text-align: center; color: {p.text_muted}; }}
td {{ background: {p.surface}; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.txt, th.txt {{ text-align: left; }}
tr.total td {{ font-weight: 600; background: {p.accent_soft}; }}
.footnote {{ color: {p.text_muted}; font-size: {t.pt(small)};
            margin: {ds.spacing.xxs}px 0 {ds.spacing.sm}px 0; white-space: normal; }}
.warning {{ color: {p.warning}; background: {p.warning_soft}; border-left: 3px solid {p.warning};
           padding: {ds.spacing.xs}px {ds.spacing.sm}px; margin: {ds.spacing.xs}px 0;
           font-size: {t.pt(small)}; white-space: normal; }}
.note {{ color: {p.text_muted}; font-size: {t.pt(small)}; margin: {ds.spacing.xxs}px 0;
        white-space: normal; }}
/* Каждое исследование - отдельная карточка. Без рамки результаты сливались в
   одно полотно, и понять, где кончился один расчёт и начался следующий, при
   прокрутке было невозможно.
   Карточка сделана таблицей, а не блоком с рамкой, намеренно: Qt рисует рамки у
   таблиц, но игнорирует их у блоков div. Блок с рамкой выглядел правильно
   только в браузере и никак - в окне программы, то есть там, где он и нужен. */
.proc {{ margin: 0 0 {ds.spacing.lg}px 0; }}
.card {{ width: 100%; border-collapse: collapse; background: {p.surface_alt};
        border: 1px solid {p.border}; border-left: 4px solid {p.accent}; }}
.cardCell {{ padding: {ds.spacing.sm}px {ds.spacing.md}px; vertical-align: top;
            background: {p.surface_alt}; }}
.proc:first-child {{ margin-top: 0; }}
.proc > h2:first-child {{ margin-top: 0; }}
/* Блок «простыми словами»: главное в отчёте, поэтому он выделен сильнее
   остальных пояснений. */
.findings {{ background: {p.accent_soft}; border: 1px solid {p.border};
            border-radius: {ds.radii.sm}px; padding: {ds.spacing.sm}px {ds.spacing.md}px;
            margin: {ds.spacing.xs}px 0 {ds.spacing.md}px 0; }}
.findings h3 {{ margin: 0 0 {ds.spacing.xs}px 0; color: {p.accent}; }}
.finding {{ margin: {ds.spacing.xxs}px 0; font-size: {t.pt(base)};
           line-height: 1.45; white-space: normal; }}
.finding.conclusion {{ color: {p.text}; font-weight: 600; }}
.finding.caution {{ color: {p.warning}; font-weight: 400; }}
.finding.note {{ color: {p.text_muted}; font-weight: 400; }}
.finding .mark {{ font-weight: 400; color: {p.accent}; }}
/* Заголовок группы при разбиении файла: заметная плашка, чтобы границы между
   группами было видно при прокрутке длинного отчёта. */
h2.group {{ background: {p.accent_soft}; color: {p.accent}; border-radius: {ds.radii.sm}px;
           padding: {ds.spacing.xs}px {ds.spacing.sm}px;
           margin: {ds.spacing.lg}px 0 {ds.spacing.sm}px 0;
           border-left: 4px solid {p.accent}; font-size: {t.pt(base + 2)}; }}
.syntax {{ font-family: "{t.family_mono}", monospace; font-size: {t.pt(small)};
          background: {p.surface_sunken}; border: 1px solid {p.border};
          padding: {ds.spacing.sm}px; white-space: pre-wrap; margin: {ds.spacing.sm}px 0;
          color: {p.text_muted}; }}
"""


def _cell_html(value: Any, align: str, decimals: int | None, suffix: str = "") -> str:
    css = "num" if align == "right" else "txt"
    if value is None:
        return f'<td class="{css}">.</td>'
    if isinstance(value, float):
        text = num(value, decimals) + suffix
    else:
        text = str(value)
    return f'<td class="{css}">{html.escape(text).replace(chr(10), "<br>")}</td>'


def table_to_html(table: Table) -> str:
    # Таблица без колонок используется как заголовок группы при разбиении файла:
    # рисуем её заметным подзаголовком, а не пустой таблицей.
    if not table.columns:
        return f'<h2 class="group">{html.escape(table.title)}</h2>'

    parts = [f"<h3>{html.escape(table.caption)}</h3>", "<table>"]
    if table.columns:
        parts.append("<tr>")
        for column in table.columns:
            css = "num" if column.align == "right" else "txt"
            parts.append(f'<th class="{css}">{html.escape(column.label)}</th>')
        parts.append("</tr>")
    for row in table.rows:
        # Итоговая строка выделяется: пользователи ищут её глазами.
        is_total = bool(row) and isinstance(row[0], str) and row[0].strip().lower() in (
            "всего",
            "итого",
        )
        parts.append('<tr class="total">' if is_total else "<tr>")
        for column, value in zip(table.columns, row):
            parts.append(_cell_html(value, column.align, column.decimals, column.suffix))
        parts.append("</tr>")
    parts.append("</table>")
    for note in table.footnotes:
        parts.append(f'<div class="footnote">{html.escape(note)}</div>')
    return "\n".join(parts)


def findings_to_html(result: Result) -> str:
    """Блок «Простыми словами»: человеческий вывод перед таблицами.

    Записи группируются по смыслу: сначала выводы, затем предупреждения, затем
    пояснения. Раньше они шли в порядке появления, и предупреждение оказывалось
    между двумя выводами - читалось так, будто относится к ним обоим.
    """
    labels = {"conclusion": "Вывод", "caution": "Внимание", "note": "Пояснение"}
    order = ("conclusion", "caution", "note")
    grouped: dict[str, list] = {kind: [] for kind in order}
    others: list = []
    for finding in result.findings:
        if finding.kind in grouped:
            grouped[finding.kind].append(finding)
        else:
            others.append(finding)

    parts = ['<div class="findings">', "<h3>Простыми словами</h3>"]
    current_group = None
    for kind in order:
        for finding in grouped[kind]:
            # Выводы одного анализа идут под своим подзаголовком: в отчёте с
            # несколькими парами переменных иначе не понять, где чей вывод.
            group = getattr(finding, "group", "")
            if group and group != current_group:
                parts.append(
                    f'<h4 class="finding-group">{html.escape(group)}</h4>'
                )
                current_group = group
            parts.append(
                f'<div class="finding {html.escape(kind)}">'
                f'<span class="mark">{labels[kind]}. </span>'
                f"{html.escape(finding.text)}</div>"
            )
    for finding in others:
        parts.append(f'<div class="finding">{html.escape(finding.text)}</div>')
    parts.append("</div>")
    return "\n".join(parts)


def result_to_html(
    result: Result, include_syntax: bool = True, number: int | None = None
) -> str:
    """Один результат процедуры. number - сквозной номер в отчёте."""
    heading = result.title or result.procedure
    if number is not None:
        heading = f"{number}. {heading}"
    parts = [
        f'<div class="proc" id="result-{number or 0}">',
        # Карточка-таблица: рамку вокруг результата иначе не нарисовать (см.
        # пояснение к .card в стилях).
        '<table class="card"><tr><td class="cardCell">',
        f"<h2>{html.escape(heading)}</h2>",
    ]
    # Выводы «простыми словами» идут первыми: человеку нужен ответ, а не таблица.
    # Таблицы остаются ниже - для тех, кто захочет проверить числа.
    if result.findings:
        parts.append(findings_to_html(result))
    for note in result.notes:
        parts.append(f'<div class="note">{html.escape(note)}</div>')
    for table in result.tables:
        parts.append(table_to_html(table))
    for warning in result.warnings:
        parts.append(f'<div class="warning">{html.escape(warning)}</div>')
    if include_syntax and result.syntax:
        parts.append("<h3>Синтаксис</h3>")
        parts.append(f'<div class="syntax">{html.escape(result.syntax)}</div>')
    parts.append("</td></tr></table>")
    parts.append("</div>")
    return "\n".join(parts)


def report_to_html(
    results: list[Result],
    title: str = "Отчёт Winnow",
    theme: str = "light",
    show_title: bool = True,
    include_syntax: bool = True,
) -> str:
    """Полный отчёт: theme связывает вид таблиц с темой интерфейса.

    show_title=False используется во встроенном окне вывода - там заголовок
    отчёта лишний, его роль выполняет заголовок панели.

    include_syntax=False используется в простом режиме: команды SPSS нужны
    опытному пользователю, а начинающего они только сбивают с толку. В файлах
    отчёта синтаксис остаётся всегда.
    """
    body = "\n".join(
        result_to_html(result, include_syntax=include_syntax, number=index)
        for index, result in enumerate(results, start=1)
    )
    heading = f"<h1>{html.escape(title)}</h1>" if show_title else ""
    return (
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{css_from_theme(theme)}</style></head>"
        f"<body>{heading}{body}</body></html>"
    )


__all__ = [
    "css_from_theme",
    "report_to_html",
    "result_to_html",
    "table_to_html",
]
