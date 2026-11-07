"""Разбиение вопросов с несколькими ответами на отдельные переменные-отметки.

Анкетные сервисы (Google Forms и другие) пишут вопрос «выберите всё подходящее» в
одну ячейку, склеивая варианты через точку с запятой:

    «2. Социальные сети (YouTube, Telegram);6. Вебинары и онлайн-курсы;7. Форумы»

Для анализа такая переменная бесполезна: у неё десятки уникальных значений, и ни
частоты, ни таблицы сопряжённости по ней не построить. Нужны отдельные отметки
«выбрано / не выбрано» на каждый вариант — так же, как это делают в SPSS, когда
разбивают множественный выбор на дихотомии.

Главное решение здесь — что считать пропуском. Если человек вопрос не видел,
отметки должны остаться незаполненными, а не превратиться в нули: иначе «не
спрашивали» и «не выбрал» станут одним и тем же, и доли поедут.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from winnow.core.dataset import Dataset
from winnow.core.variable import VarType

#: Разделитель вариантов в ячейке. Точка с запятой встречается почти всегда;
#: вертикальная черта добавлена как частый вариант в чужих выгрузках.
SEPARATORS = (";", "|")

#: Какая доля заполненных ответов должна содержать разделитель, чтобы вопрос
#: считался множественным. Одно случайное «;» в тексте — ещё не множественный
#: выбор, а половина ответов с разделителем — уже точно он.
MIN_SHARE = 0.1

#: Минимум заполненных ответов: на трёх анкетах судить не о чем.
MIN_ANSWERS = 5

#: Больше вариантов — это уже не список ответов, а свободный текст.
MAX_OPTIONS = 60

_OPTION_CODE = re.compile(r"^\s*(\d+)\s*[.)]\s*")

#: Начало следующего варианта после запятой: «… (Coursera, Udemy), 6. Вебинары».
#: Разделять просто по запятой нельзя - она встречается внутри названий вариантов
#: («Coursera, Udemy, Skillbox»). Поэтому границей считается запятая, за которой
#: идёт номер варианта.
_OPTION_START = re.compile(r"[,;]\s*(?=\d{1,2}\s*[.)]\s)")


@dataclass
class MultiAnswer:
    """Вопрос с несколькими ответами."""

    name: str
    label: str
    n_answers: int
    n_with_separator: int
    options: list[str] = field(default_factory=list)

    @property
    def share(self) -> float:
        return self.n_with_separator / self.n_answers if self.n_answers else 0.0

    def summary(self) -> str:
        return (
            f"«{self.label}»: вариантов {len(self.options)}, "
            f"ответов {self.n_answers}"
        )


def _cells(series: pd.Series) -> pd.Series:
    """Значения как строки; пустые и пропуски не считаются ответами."""
    text = series.astype("string").str.strip()
    return text.mask(text == "", pd.NA)


def _split_cell(value: str) -> list[str]:
    """Разбивает одну ячейку на варианты.

    Форматов два, и оба встречаются в одной и той же анкете: выгрузка CSV пишет
    варианты через точку с запятой, а выгрузка Excel - через запятую с номером
    варианта («2. Социальные сети, 6. Вебинары»). Разделять по запятой нельзя:
    она стоит внутри названий вариантов.
    """
    parts: list[str] = []
    for chunk in value.replace("|", ";").split(";"):
        parts.extend(_OPTION_START.split(chunk))
    return [part.strip() for part in parts if part.strip()]


def detect_column(dataset: Dataset, name: str) -> MultiAnswer | None:
    """Проверяет одну переменную и возвращает описание, если это множественный выбор."""
    variable = dataset.var(name)
    if variable.var_type is not VarType.STRING:
        return None
    cells = _cells(dataset.frame[name]).dropna()
    n_answers = int(len(cells))
    if n_answers < MIN_ANSWERS:
        return None
    with_separator = cells.map(lambda value: len(_split_cell(value)) > 1)
    n_with_separator = int(with_separator.sum())
    if not n_with_separator or n_with_separator / n_answers < MIN_SHARE:
        return None

    options: list[str] = []
    for value in cells:
        for part in _split_cell(value):
            if part not in options:
                options.append(part)
    if len(options) < 2 or len(options) > MAX_OPTIONS:
        return None
    return MultiAnswer(
        name=name,
        label=variable.label or name,
        n_answers=n_answers,
        n_with_separator=n_with_separator,
        options=options,
    )


def detect_multi_answer(dataset: Dataset) -> list[MultiAnswer]:
    """Находит все вопросы с несколькими ответами."""
    found: list[MultiAnswer] = []
    for name in dataset.names():
        item = detect_column(dataset, name)
        if item is not None:
            found.append(item)
    return found


def _short_base(source: str) -> str:
    """Короткая основа для имён отметок.

    Имя столбца в выгрузке Google Forms - это весь текст вопроса («10. В ваших
    повседневных практиках что, чаще всего, является…»). Подставлять его в имя
    переменной нельзя: получается строка в сотню символов, которую не прочитать
    ни в списке переменных, ни в выводе. Полный текст остаётся в метке.
    """
    match = _OPTION_CODE.match(source)
    if match:
        return f"q{match.group(1)}"
    slug = re.sub(r"[^\w]+", "_", source, flags=re.UNICODE).strip("_")
    return (slug[:12] or "q").strip("_")


def _option_name(source: str, option: str, index: int) -> str:
    """Короткое имя отметки: по номеру варианта, если он есть в тексте."""
    match = _OPTION_CODE.match(option)
    suffix = match.group(1) if match else str(index)
    return f"{_short_base(source)}_{suffix}"


def split_column(dataset: Dataset, item: MultiAnswer) -> list[str]:
    """Добавляет переменные-отметки для одного вопроса и возвращает их имена."""
    cells = _cells(dataset.frame[item.name])
    created: list[str] = []
    used: set[str] = set()
    for index, option in enumerate(item.options, start=1):
        name = _option_name(item.name, option, index)
        # Имя должно быть свободным: если вариант без номера, суффиксом служит
        # порядковый номер, и он может совпасть с уже существующим.
        attempt = 2
        base = name
        while name in dataset.names() or name in used:
            name = f"{base}_{attempt}"
            attempt += 1
        used.add(name)

        def chosen(value: str, target: str = option) -> float:
            return 1.0 if target in _split_cell(value) else 0.0

        flags = cells.map(lambda value: chosen(value) if pd.notna(value) else float("nan"))
        dataset.add_variable(name, flags.astype(float), label=option)
        created.append(name)
    return created


def has_marks(dataset: Dataset, item: MultiAnswer) -> bool:
    """Есть ли у вопроса уже готовые переменные-отметки.

    Исходный вопрос после разбиения остаётся в наборе (его никто не удаляет),
    поэтому без этой проверки программа снова и снова предлагала бы его разбить
    и создавала бы дубли вида «q10_8_2».
    """
    prefix = f"{_short_base(item.name)}_"
    return any(name.startswith(prefix) for name in dataset.names())


def split_all(dataset: Dataset) -> tuple[list[str], list[MultiAnswer]]:
    """Разбивает все найденные вопросы. Возвращает имена отметок и описания."""
    created: list[str] = []
    handled: list[MultiAnswer] = []
    for item in detect_multi_answer(dataset):
        if has_marks(dataset, item):
            continue
        names = split_column(dataset, item)
        if names:
            created.extend(names)
            handled.append(item)
    return created, handled


def format_report(handled: list[MultiAnswer], created: list[str]) -> str:
    """Текст для консоли и сообщения в окне."""
    if not handled:
        return "Вопросов с несколькими ответами не найдено."
    lines = [
        f"Разбито вопросов: {len(handled)}, добавлено переменных-отметок: {len(created)}"
    ]
    for item in handled:
        lines.append(f"  • {item.summary()}")
    return "\n".join(lines)


__all__ = [
    "MultiAnswer",
    "detect_column",
    "detect_multi_answer",
    "format_report",
    "has_marks",
    "split_all",
    "split_column",
]
