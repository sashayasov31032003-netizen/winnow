"""Тесты разбиения вопросов с несколькими ответами на переменные-отметки."""
from __future__ import annotations

import pytest

from winnow.core.dataset import Dataset
from winnow.stats.command import CrosstabsCommand, FrequenciesCommand
from winnow.stats.multianswer import detect_multi_answer, split_all, split_column


def _survey() -> Dataset:
    """Анкета, как её выгружает Google Forms: варианты склеены в одну ячейку."""
    return Dataset.from_records(
        {
            "1. Ваш пол": ["1. Мужской", "2. Женский"] * 6,
            "10. Источники информации": [
                "2. Соцсети (YouTube, Telegram);7. Форумы",
                "2. Соцсети (YouTube, Telegram);6. Вебинары;7. Форумы",
                "",
                "6. Вебинары",
                None,
                "7. Форумы",
            ]
            * 2,
        }
    )


def test_multi_answer_question_is_detected():
    dataset = _survey()
    found = detect_multi_answer(dataset)
    assert len(found) == 1
    item = found[0]
    assert item.name == "10. Источники информации"
    # Запятая внутри названия варианта не должна создавать лишний вариант.
    assert item.options == [
        "2. Соцсети (YouTube, Telegram)",
        "7. Форумы",
        "6. Вебинары",
    ]


def test_plain_columns_are_not_detected():
    dataset = Dataset.from_records({"пол": ["муж", "жен"] * 5})
    assert detect_multi_answer(dataset) == []


def test_split_creates_short_named_marks():
    dataset = _survey()
    created, handled = split_all(dataset)

    assert len(handled) == 1
    assert created == ["q10_2", "q10_7", "q10_6"], "имена короткие, по номеру варианта"
    # Метка хранит полный текст варианта.
    assert dataset.var("q10_2").label == "2. Соцсети (YouTube, Telegram)"


def test_split_marks_are_one_and_zero_and_keep_missing():
    dataset = _survey()
    split_all(dataset)
    marks = dataset.frame["q10_2"]

    # Первый и второй ответ выбрали этот вариант.
    assert marks.iloc[0] == 1.0
    assert marks.iloc[1] == 1.0
    # Ноль ставится только там, где человек ответил, но этот вариант не выбрал.
    assert marks.iloc[5] == 0.0
    # А пустая ячейка и пропуск остаются пропусками: «не ответил» и «не выбрал» -
    # разные вещи, и заменять одно другим значило бы испортить доли.
    assert marks.iloc[2] != marks.iloc[2]
    assert marks.iloc[4] != marks.iloc[4]


def test_split_marks_can_be_analysed():
    """Ради этого всё и делалось: по отметкам считаются частоты и сопряжённость."""
    dataset = _survey()
    split_all(dataset)

    frequencies = FrequenciesCommand(
        dataset=dataset, variables=["q10_2"]
    ).execute()
    assert frequencies.tables
    assert frequencies.conclusions, "у частот должен быть вывод простыми словами"

    crosstabs = CrosstabsCommand(
        dataset=dataset, row_vars=["1. Ваш пол"], col_vars=["q10_2"]
    ).execute()
    assert crosstabs.tables


def test_comma_separated_export_is_detected():
    """Выгрузка Excel пишет варианты через запятую с номером, а не через «;»."""
    dataset = Dataset.from_records(
        {
            "12. Источники": [
                "2. Соцсети (YouTube, Telegram, VK), 6. Вебинары (Coursera, Udemy)",
                "2. Соцсети (YouTube, Telegram, VK)",
                "6. Вебинары (Coursera, Udemy), 7. Форумы",
                "2. Соцсети (YouTube, Telegram, VK), 7. Форумы",
            ]
            * 3,
        }
    )
    found = detect_multi_answer(dataset)
    assert found, "вопрос с вариантами через запятую должен распознаваться"
    assert found[0].options == [
        "2. Соцсети (YouTube, Telegram, VK)",
        "6. Вебинары (Coursera, Udemy)",
        "7. Форумы",
    ], "запятые внутри названий не должны разрывать вариант"


def test_single_option_column_is_left_alone():
    """Обычный вопрос с одним ответом не трогаем."""
    dataset = Dataset.from_records({"пол": ["1. Мужской", "2. Женский"] * 5})
    assert detect_multi_answer(dataset) == []
