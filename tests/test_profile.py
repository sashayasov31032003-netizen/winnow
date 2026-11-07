"""Тесты профиля данных: роли переменных и замечания о качестве набора.

Профиль - это то, на чём будет строиться подсказка «что можно сделать с этими
данными». Если он ошибается, программа уверенно предложит бессмыслицу, поэтому
проверяются не только удачные случаи, но и ловушки: номер респондента, константа,
вопрос «выберите подходящее».
"""

from __future__ import annotations

import pandas as pd
import pytest

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure
from winnow.samples import demo_dataset
from winnow.stats.profile import profile_dataset, profile_variable


def _dataset(**columns) -> Dataset:
    return Dataset.from_records(dict(columns))


def test_demo_dataset_profile_finds_questionnaire():
    """Демо-набор содержит шкалу из четырёх пунктов - она должна быть узнана."""
    profile = profile_dataset(demo_dataset())
    assert profile.n_cases == 200
    assert profile.n_variables == 14

    items = {variable.name for variable in profile.likert_items}
    assert {"stress1", "stress2", "stress3", "stress4"} <= items

    joined = " ".join(profile.notes)
    assert "Похоже на анкету" in joined


def test_identifier_is_not_a_measure():
    """Сквозная нумерация строк - не показатель, и её надо пометить."""
    dataset = _dataset(number=list(range(1, 41)), height=[170 + i % 7 for i in range(40)])
    profile = profile_dataset(dataset)

    assert profile.identifiers == ["number"]
    assert profile.by_name("number").is_identifier
    assert not profile.by_name("number").is_usable
    assert "идентификатор" in profile.by_name("number").role
    assert "номер" not in [variable.name for variable in profile.scales]


def test_constant_variable_is_flagged():
    dataset = _dataset(same=[5] * 20, varied=list(range(20)))
    profile = profile_dataset(dataset)

    assert profile.constants == ["same"]
    assert profile.by_name("same").is_constant
    assert not profile.by_name("same").is_usable


def test_checkbox_pattern_is_recognised():
    """«Выберите подходящее»: у ответивших единица, у остальных пропуск.

    Такие переменные сейчас константы и в анализе не участвуют, но это
    исправимо: пропуск означает «не выбрано». Программа обязана это заметить и
    сказать, что делать.
    """
    dataset = _dataset(
        **{
            "source_web": [1.0] * 12 + [None] * 28,
            "source_print": [1.0] * 8 + [None] * 32,
            "source_radio": [1.0] * 5 + [None] * 35,
            "age": [20 + i for i in range(40)],
        }
    )
    profile = profile_dataset(dataset)

    assert set(profile.checkboxes) == {"source_web", "source_print", "source_radio"}
    assert profile.by_name("source_web").looks_like_checkbox
    assert "выберите подходящее" in " ".join(profile.notes)
    # Про такие переменные отдельно объясняется, что пропуск - это «не выбрано».
    assert "заменить нулями" in " ".join(profile.notes)


def test_checkbox_note_does_not_repeat_for_every_variable():
    """Замечания сводятся в одно: девяносто одинаковых строк никто не читает."""
    dataset = _dataset(**{f"item{i}": [1.0] * 5 + [None] * 15 for i in range(30)})
    profile = profile_dataset(dataset)

    checkbox_notes = [note for note in profile.notes if "выберите подходящее" in note]
    assert len(checkbox_notes) == 1
    assert "30" in checkbox_notes[0]
    assert len(profile.notes) <= 5


def test_binary_codes_are_categories_not_ranks():
    """Пол, закодированный единицей и двойкой, - категория."""
    dataset = _dataset(gender=[1, 2] * 10)
    profile = profile_dataset(dataset)

    assert profile.by_name("gender").is_binary
    assert "категория" in profile.by_name("gender").role


def test_group_variable_needs_at_least_two_cases_per_group():
    """Группа из одного случая не даёт сравнения, и предлагать её нельзя."""
    dataset = _dataset(
        group=[1] * 19 + [2],
        outcome=[float(value) for value in range(20)],
    )
    profile = profile_dataset(dataset)

    assert not profile.by_name("group").can_compare_groups
    assert "group" not in [variable.name for variable in profile.groupers]


def test_normality_and_outliers_are_reported_for_scales():
    """Для количественного показателя считается нормальность и выбросы."""
    values = [10.0, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
    dataset = _dataset(score=values + [200.0])  # последнее значение - выброс
    profile = profile_dataset(dataset)

    variable = profile.by_name("score")
    assert variable.is_scale
    assert variable.is_normal is False or variable.is_normal is True  # проверка выполнена
    assert variable.n_outliers >= 1


def test_missing_values_respect_dataset_codes():
    """Коды пропусков из паспорта переменной учитываются как пропуски."""
    dataset = _dataset(income=[100.0, 200.0, -1.0, 300.0, -1.0])
    dataset.var("income").missing.discrete = {-1.0}
    profile = profile_variable(dataset, "income")

    assert profile.n_missing == 2
    assert profile.n_unique == 3
    assert profile.missing_share == pytest.approx(0.4)


def test_profile_does_not_change_metadata():
    """Профиль только читает: паспорта переменных меняться не должны."""
    dataset = demo_dataset()
    before = {name: dataset.var(name).measure for name in dataset.names()}
    profile_dataset(dataset)
    after = {name: dataset.var(name).measure for name in dataset.names()}

    assert before == after


def test_empty_dataset_profile_is_not_a_crash():
    """Пустой набор - обычное состояние при запуске, профиль не должен падать."""
    frame = pd.DataFrame({"a": pd.Series(dtype="float64")})
    profile = profile_dataset(Dataset(frame=frame))
    assert profile.n_cases == 0
    assert profile.variables[0].n_unique == 0
