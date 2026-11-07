"""Тесты моделей данных: паспорта переменных, пропуски, отбор кейсов, копирование."""

from __future__ import annotations

import pandas as pd
import pytest

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec, VarType


def test_variable_metadata_is_inferred_sensibly():
    dataset = Dataset.from_records(
        {
            "gender": [1, 2, 1],
            # Дробные значения -> количественная шкала.
            "age": [20.5, 30.25, 40.75],
            # Целые с малым числом градаций -> порядковая (шкала Ликерта).
            "likert": [1, 3, 5],
            "name": ["a", "b", "c"],
        }
    )
    # Два значения - это коды, а не ступени: порядок между ними не определён.
    assert dataset.var("gender").measure is Measure.NOMINAL
    assert dataset.var("age").measure is Measure.SCALE
    assert dataset.var("likert").measure is Measure.ORDINAL
    assert dataset.var("name").var_type is VarType.STRING
    assert dataset.var("name").measure is Measure.NOMINAL


def test_integer_age_is_not_mistaken_for_an_ordinal_scale():
    """Целочисленный возраст - количественная шкала, и маленькая выборка не
    должна это менять.

    Раньше правило смотрело только на число различных значений: у шести человек
    шесть различных значений возраста, значит «мало градаций» - и возраст
    объявлялся порядковой шкалой. Из-за этого в списках процедур он переставал
    предлагаться как количественный показатель.
    """
    dataset = Dataset.from_records(
        {
            "age": [23, 35, 41, 29, 52, 31],
            "experience": [2, 10, 15, 6, 25, 8],
            # Пункт анкеты: целые в узком диапазоне - это порядковая шкала.
            "satisfaction": [4, 3, 5, 2, 4, 3],
            # Константа: измерять нечего.
            "same": [7, 7, 7, 7, 7, 7],
        }
    )
    assert dataset.var("age").measure is Measure.SCALE
    assert dataset.var("experience").measure is Measure.SCALE
    assert dataset.var("satisfaction").measure is Measure.ORDINAL
    assert dataset.var("same").measure is Measure.NOMINAL


def test_display_name_combines_label_and_name():
    dataset = Dataset.from_records({"age": [20, 30]})
    dataset.var("age").label = "Возраст респондента"
    assert dataset.var("age").display_name == "Возраст респондента [age]"


def test_value_labels_do_not_leak_between_datasets():
    """Копия набора не должна делить словарь меток с оригиналом."""
    dataset = Dataset.from_records({"gender": [1, 2]})
    dataset.var("gender").value_labels = {1: "мужской"}
    clone = dataset.copy()
    clone.var("gender").value_labels[2] = "женский"
    assert 2 not in dataset.var("gender").value_labels


def test_discrete_missing_becomes_nan_in_analysis():
    dataset = Dataset.from_records({"hours": [10.0, -1.0, 20.0, -1.0]})
    dataset.var("hours").missing = MissingSpec(discrete={-1.0})
    series = dataset.analysis_series("hours")
    assert int(series.notna().sum()) == 2
    assert list(series.dropna()) == [10.0, 20.0]


def test_missing_range_is_respected():
    dataset = Dataset.from_records({"q": [-99.0, -95.0, 5.0, 7.0, -50.0]})
    dataset.var("q").missing = MissingSpec(lo=-99.0, hi=-90.0)
    assert dataset.analysis_series("q").dropna().tolist() == [5.0, 7.0, -50.0]


def test_missing_spec_contains_handles_int_and_float():
    spec = MissingSpec(discrete={-99})
    assert spec.contains(-99)
    assert spec.contains(-99.0)
    assert not spec.contains(10)


def test_filter_selects_cases_and_rejects_empty_filter():
    dataset = Dataset.from_records({"x": [1, 2, 3, 4]})
    dataset.set_filter(pd.Series([True, False, True, False]))
    assert dataset.analysis_series("x").tolist() == [1.0, 3.0]
    assert "Отобрано" in dataset.summary()

    with pytest.raises(ValueError):
        dataset.set_filter(pd.Series([False, False, False, False]))


def test_filter_length_mismatch_is_an_error():
    dataset = Dataset.from_records({"x": [1, 2, 3]})
    with pytest.raises(ValueError):
        dataset.set_filter(pd.Series([True, False]))


def test_numeric_column_required_for_analysis_series():
    dataset = Dataset.from_records({"name": ["a", "b"]})
    with pytest.raises(TypeError):
        dataset.analysis_series("name")


def test_add_and_drop_variable():
    dataset = Dataset.from_records({"x": [1, 2, 3]})
    dataset.add_variable("y", [4, 5, 6], label="Новая переменная")
    assert dataset.var("y").label == "Новая переменная"
    assert dataset.n_vars == 2

    with pytest.raises(ValueError):
        dataset.add_variable("y", [1, 2, 3])

    dataset.drop_variable("y")
    assert dataset.n_vars == 1


def test_weight_values_excludes_non_positive_weights():
    dataset = Dataset.from_records({"x": [1, 2, 3], "w": [1.0, 0.0, -2.0]})
    dataset.weight_var = "w"
    weights = dataset.weight_values()
    assert weights is not None
    assert weights.tolist() == [1.0, 0.0, 0.0]


def test_analysis_frame_does_not_mutate_source_data():
    dataset = Dataset.from_records({"x": [1.0, -1.0]})
    dataset.var("x").missing = MissingSpec(discrete={-1.0})
    frame = dataset.analysis_frame(["x"])
    frame.loc[0, "x"] = 999.0
    assert dataset.frame["x"].iloc[0] == 1.0


def test_analysis_frame_without_arguments_uses_all_variables():
    dataset = Dataset.from_records({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    frame = dataset.analysis_frame()
    assert list(frame.columns) == ["x", "y"]
    assert len(frame) == 2
