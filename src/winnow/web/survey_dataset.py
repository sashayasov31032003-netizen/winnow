"""Превращение ответов опроса в обычный набор Winnow.

Смысл всей затеи с опросами: структура известна заранее. Поэтому переменные
получают правильные метки и уровни измерения **без догадок**, а множественные
ответы сразу становятся отметками 1/0 - без разбора строк и без риска ошибки,
который есть при загрузке чужой выгрузки CSV.

Соответствие «вопрос → переменная»:

    один вариант      «Ваш пол»            категория, метки вариантов (1 = «Мужской»)
    несколько         «Источники: Радио»   отметки 1/0 на каждый вариант
    число             «Возраст»            количественная
    шкала             «Оцените курс»       порядковая
    текст             «Что улучшить»       строковая, номинальная

Имя переменной - текст вопроса: в «Данных» сразу видно, о чём столбец, а не
«q3». Поэтому же метка переменной совпадает с именем, и в отчётах вопрос
показывается один раз.

Пропуск остаётся пропуском: если человек не отвечал на вопрос, значения нет, а
не ноль. Для множественного выбора это принципиально: «не спрашивали» и «не
выбрал» - разные вещи, и доли по вариантам поехали бы, если их смешать.
"""

from __future__ import annotations

from collections import OrderedDict

import pandas as pd

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, VarType
from winnow.web import surveys
from winnow.web.core import Answer, Question, Survey, SurveyResponse

#: Метка переменной: длинный текст вопроса обрезается. В SPSS метка тоже
#: ограничена, а в дереве переменных всё равно видна одна строка.
MAX_LABEL = 200

#: Имя переменной: это текст вопроса. Сто символов хватает, чтобы вопрос узнавался
#: в заголовке таблицы, и при этом столбцы остаются читаемыми.
MAX_NAME = 100

#: Метки отметок множественного выбора: как у дихотомий в SPSS.
YES_NO = {1.0: "выбрано", 0.0: "не выбрано"}


class _Column:
    """Собираемая переменная: значения и паспорт до попадания в Dataset."""

    def __init__(self, name: str, label: str):
        self.name = name
        self.label = label
        self.values: list[float | str | None] = []
        self.measure = Measure.NOMINAL
        self.var_type = VarType.NUMERIC
        self.value_labels: dict[float, str] = {}
        self.decimals = 2

    def numeric(self, measure: Measure, decimals: int = 2) -> "_Column":
        self.measure = measure
        self.var_type = VarType.NUMERIC
        self.decimals = decimals
        return self

    def text(self) -> "_Column":
        self.measure = Measure.NOMINAL
        self.var_type = VarType.STRING
        return self


def _label(text: str) -> str:
    """Метка переменной в одну строку."""
    return " ".join(str(text).split())[:MAX_LABEL]


def _question_text(question: Question) -> str:
    """Текст вопроса в одну строку: он и есть имя переменной."""
    return " ".join(str(question.text).split())


def _unique(name: str, used: set[str]) -> str:
    """Освобождает имя: два вопроса с одинаковым текстом - это два столбца."""
    candidate = name
    attempt = 2
    while candidate in used:
        suffix = f" ({attempt})"
        candidate = f"{name[: MAX_NAME - len(suffix)].rstrip()}{suffix}"
        attempt += 1
    used.add(candidate)
    return candidate


def _base_name(question: Question, used: set[str]) -> str:
    """Имя переменной - текст вопроса.

    Так в «Данных» сразу видно, о чём столбец, и не нужно смотреть метку. Имена
    должны быть уникальными, поэтому два одинаковых вопроса получают номер.
    """
    text = _question_text(question)[:MAX_NAME].rstrip()
    if not text:
        text = f"Вопрос {question.position + 1}"
    return _unique(text, used)


def _multi_name(question: Question, choice: dict, used: set[str]) -> str:
    """Имя отметки: «Какие фрукты?: яблоко».

    Текст вопроса сокращается сильнее, чтобы не потерялся вариант - именно он
    отличает одну отметку от другой.
    """
    option = " ".join(str(choice["label"]).split())
    limit = max(12, MAX_NAME - len(option) - 2)
    text = _question_text(question)[:limit].rstrip() or f"Вопрос {question.position + 1}"
    return _unique(f"{text}: {option}"[:MAX_NAME], used)


def _answer_map(response: SurveyResponse) -> dict[int, Answer]:
    return {answer.question_id: answer for answer in response.answers}


def _single_code(question: Question, answer: Answer | None) -> float | None:
    """Код выбранного варианта - то же число, что в options вопроса."""
    if answer is None or not answer.option_ids:
        return None
    value = str(answer.option_ids[0])
    if value.isdigit():
        return float(value)
    # Вариант без числового номера: тогда его место в списке вариантов.
    for index, choice in enumerate(surveys.question_choices(question), start=1):
        if choice["id"] == value:
            return float(index)
    return None


def _number(value: float | None) -> float | None:
    return None if value is None else float(value)


def build(survey: Survey, responses: list[SurveyResponse]) -> Dataset:
    """Собирает набор из ответов.

    ``responses`` передаются уже загруженными: запрос к базе - дело вызывающего
    кода, а здесь только сборка, которую можно проверить без HTTP.
    """
    questions = list(survey.questions)
    if not questions:
        raise ValueError("В опросе нет вопросов: собирать набор не из чего")
    if not responses:
        raise ValueError("Ответов пока нет: собирать набор не из чего")

    answers = [_answer_map(response) for response in responses]
    columns: OrderedDict[str, _Column] = OrderedDict()
    used: set[str] = set()

    for question in questions:
        kind = question.kind

        if kind == surveys.SINGLE:
            name = _base_name(question, used)
            column = _Column(name, _label(question.text)).numeric(Measure.NOMINAL, 0)
            column.value_labels = {
                float(index): choice["label"]
                for index, choice in enumerate(
                    surveys.question_choices(question), start=1
                )
            }
            column.values = [
                _single_code(question, answers[number].get(question.id))
                for number in range(len(responses))
            ]
            columns[name] = column

        elif kind == surveys.MULTI:
            # Один вопрос - несколько переменных: по отметке на вариант. Так
            # доли считаются по каждому варианту отдельно, как в SPSS.
            for choice in surveys.question_choices(question):
                name = _multi_name(question, choice, used)
                column = _Column(
                    name, _label(f"{_question_text(question)}: {choice['label']}")
                ).numeric(Measure.NOMINAL, 0)
                column.value_labels = dict(YES_NO)
                values: list[float | None] = []
                for number in range(len(responses)):
                    answer = answers[number].get(question.id)
                    if answer is None:
                        # Вопрос пропущен целиком: не ноль, а «не спрашивали».
                        values.append(None)
                        continue
                    chosen = str(choice["id"]) in {
                        str(item) for item in answer.option_ids or []
                    }
                    values.append(1.0 if chosen else 0.0)
                column.values = values
                columns[name] = column

        elif kind == surveys.SCALE:
            name = _base_name(question, used)
            column = _Column(name, _label(question.text)).numeric(Measure.ORDINAL, 0)
            column.values = [
                _number(answers[number][question.id].value_number)
                if question.id in answers[number]
                else None
                for number in range(len(responses))
            ]
            columns[name] = column

        elif kind == surveys.NUMBER:
            name = _base_name(question, used)
            column = _Column(name, _label(question.text)).numeric(Measure.SCALE, 2)
            column.values = [
                _number(answers[number][question.id].value_number)
                if question.id in answers[number]
                else None
                for number in range(len(responses))
            ]
            columns[name] = column

        else:  # текст
            name = _base_name(question, used)
            column = _Column(name, _label(question.text)).text()
            column.values = [
                answers[number][question.id].value_text
                if question.id in answers[number]
                else None
                for number in range(len(responses))
            ]
            columns[name] = column

    # Числовые столбцы - вещественные с NaN для пропусков: так их одинаково
    # понимают все процедуры. Строковые остаются объектными.
    data: dict[str, pd.Series] = {}
    for name, column in columns.items():
        if column.var_type == VarType.STRING:
            data[name] = pd.Series(column.values, dtype="object")
        else:
            data[name] = pd.Series(
                [float("nan") if value is None else float(value) for value in column.values],
                dtype=float,
            )
    dataset = Dataset(frame=pd.DataFrame(data), name=_label(survey.title))

    for name, column in columns.items():
        variable = dataset.var(name)
        variable.label = column.label
        variable.measure = column.measure
        variable.var_type = column.var_type
        variable.value_labels = dict(column.value_labels)
        variable.decimals = column.decimals
        if column.var_type == VarType.STRING:
            lengths = dataset.frame[name].dropna().astype(str).str.len()
            variable.columns = int(lengths.max()) if len(lengths) else 8

    return dataset


__all__ = ["MAX_LABEL", "YES_NO", "build"]
