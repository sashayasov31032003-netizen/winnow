"""Тесты разбиения файла и группировки вывода.

Разбиение - сквозная возможность движка: одна и та же процедура выполняется
отдельно по каждой категории. Тесты проверяют именно это, а не отдельную
процедуру: так гарантируется, что разбиение работает для всех процедур сразу.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.command import DescriptivesCommand, FrequenciesCommand, TTestCommand
from winnow.stats.engine import execute


def _split_dataset() -> Dataset:
    """Два города с разными средними - удобно проверять раздельные расчёты."""
    dataset = Dataset.from_records(
        {
            "score": [10.0, 12.0, 11.0, 13.0, 30.0, 32.0, 31.0, 33.0],
            "city": [1, 1, 1, 1, 2, 2, 2, 2],
        }
    )
    dataset.var("city").label = "Город"
    dataset.var("city").value_labels = {1: "Москва", 2: "Питер"}
    dataset.var("city").measure = dataset.var("city").measure.NOMINAL
    return dataset


def test_set_split_collects_categories_in_order():
    dataset = _split_dataset()
    dataset.set_split("city")
    assert dataset.has_split
    assert dataset.split_var == "city"
    assert dataset.split_values == [1, 2]
    assert "Разбиение" in dataset.summary()


def test_split_label_uses_variable_label_and_value_labels():
    dataset = _split_dataset()
    dataset.set_split("city")
    assert dataset.split_label(2) == "Город = Питер"


def test_split_mask_respects_general_filter():
    dataset = _split_dataset()
    dataset.set_split("city")
    # Оставляем только первые три кейса Москвы.
    dataset.set_filter(
        __import__("pandas").Series([True, True, True, False, False, False, False, False])
    )
    mask = dataset.split_mask(1)
    assert int(mask.sum()) == 3
    # Вторая группа после отбора пуста - должна быть отвергнута.
    with pytest.raises(ValueError):
        dataset.split_mask(2)


def test_split_unknown_variable_is_an_error():
    dataset = _split_dataset()
    with pytest.raises(KeyError):
        dataset.set_split("нет_такой")


def test_clear_split_disables_grouping():
    dataset = _split_dataset()
    dataset.set_split("city")
    dataset.clear_split()
    assert not dataset.has_split
    assert dataset.split_values == []


def test_descriptives_run_per_split_group():
    """Каждая группа должна считаться отдельно: N и среднее свои."""
    dataset = _split_dataset()
    dataset.set_split("city")
    result = DescriptivesCommand(
        dataset=dataset, variables=["score"], statistics=["n", "mean"], confidence=0.0
    ).execute()

    # Два заголовка групп плюс две таблицы результатов.
    headers = [table.title for table in result.tables if not table.columns]
    assert headers == ["Город = Москва", "Город = Питер"]

    data_tables = [table for table in result.tables if table.columns]
    assert len(data_tables) == 2
    first = dict(zip([c.label for c in data_tables[0].columns], data_tables[0].rows[0]))
    second = dict(zip([c.label for c in data_tables[1].columns], data_tables[1].rows[0]))
    assert first["N"] == 4
    assert second["N"] == 4
    assert first["Среднее"] == pytest.approx(11.5)
    assert second["Среднее"] == pytest.approx(31.5)
    # Общий средний по всем данным был бы 21.5 - значит разбиение действительно работает.
    assert first["Среднее"] != pytest.approx(21.5)


def test_group_note_explains_split():
    dataset = _split_dataset()
    dataset.set_split("city")
    result = DescriptivesCommand(
        dataset=dataset, variables=["score"], statistics=["mean"], confidence=0.0
    ).execute()
    assert any("Разбиение файла" in note for note in result.notes)


def test_frequencies_also_respect_split():
    """Разбиение живёт в движке, поэтому работает для любой процедуры."""
    dataset = _split_dataset()
    dataset.set_split("city")
    result = FrequenciesCommand(dataset=dataset, variables=["score"]).execute()
    data_tables = [table for table in result.tables if table.columns]
    # По две таблицы на группу: сводка и собственно частоты.
    assert len(data_tables) == 4


def test_split_keeps_original_filter_untouched():
    """После расчёта общий отбор должен остаться таким же, как был."""
    dataset = _split_dataset()
    dataset.set_split("city")
    DescriptivesCommand(
        dataset=dataset, variables=["score"], statistics=["mean"], confidence=0.0
    ).execute()
    assert not dataset.has_filter


def test_split_with_selected_categories_only():
    dataset = _split_dataset()
    dataset.set_split("city", [2])
    result = DescriptivesCommand(
        dataset=dataset, variables=["score"], statistics=["mean"], confidence=0.0
    ).execute()
    headers = [table.title for table in result.tables if not table.columns]
    assert headers == ["Город = Питер"]


def test_split_on_demo_dataset_with_t_test():
    """Реальный сценарий: t-критерий отдельно по городам."""
    dataset = demo_dataset(n=200, seed=20240517)
    dataset.set_split("city")
    result = TTestCommand(
        dataset=dataset,
        kind="independent",
        test_vars=["anxiety"],
        group_var="gender",
        group_values=[1, 2],
    ).execute()
    headers = [table.title for table in result.tables if not table.columns]
    assert len(headers) == 3  # три города в демо-наборе
    # Каждая группа должна дать свои таблицы критерия.
    test_tables = [
        table for table in result.tables
        if table.columns and "независимых выборок" in table.title
    ]
    assert len(test_tables) == 3


def test_group_header_table_has_no_columns():
    """Заголовок группы - таблица без колонок: так его отличает рендерер."""
    dataset = _split_dataset()
    dataset.set_split("city")
    result = DescriptivesCommand(
        dataset=dataset, variables=["score"], statistics=["mean"], confidence=0.0
    ).execute()
    headers = [table for table in result.tables if not table.columns]
    assert all(not table.rows for table in headers)
    assert all(table.title for table in headers)


def test_split_without_variation_is_ignored_gracefully():
    """Если у переменной одна категория, разбиение не должно ломать расчёт."""
    dataset = Dataset.from_records({"score": [1.0, 2.0, 3.0], "grp": [1, 1, 1]})
    dataset.set_split("grp")
    result = DescriptivesCommand(
        dataset=dataset, variables=["score"], statistics=["mean"], confidence=0.0
    ).execute()
    assert result.tables
    headers = [table.title for table in result.tables if not table.columns]
    assert headers == ["grp = 1"]


def test_execute_without_split_has_no_group_headers():
    dataset = _split_dataset()
    result = execute(
        DescriptivesCommand(
            dataset=dataset, variables=["score"], statistics=["mean"], confidence=0.0
        )
    )
    assert not [table for table in result.tables if not table.columns]
