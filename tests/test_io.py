"""Тесты ввода-вывода: метаданные должны переживать сохранение и загрузку."""

from __future__ import annotations

import importlib.util
import json

import pytest

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec, VarType
from winnow.data.io.native import dataset_from_dict, dataset_to_dict, read_native, write_native
from winnow.data.io.registry import (
    file_dialog_filters,
    format_for_path,
    read_dataset,
    save_dialog_filters,
    write_dataset,
)


def test_open_dialog_offers_common_formats_first():
    """В диалоге открытия первым должен идти общий фильтр по данным.

    Иначе в проводнике видны файлы только своего формата Winnow, и чужой файл
    (.sav или .xlsx) «не находится», хотя лежит в той же папке.
    """
    filters = file_dialog_filters().split(";;")
    first = filters[0]
    assert first.startswith("Данные и таблицы")
    assert "*.sav" in first
    assert "*.xlsx" in first
    # Свой формат в общий фильтр не подмешивается.
    assert "*.wndata" not in first
    assert "*.stldata" not in first
    # И он не первый в списке: нужен реже.
    assert "Набор данных Winnow" not in filters[0]
    assert any("Набор данных Winnow" in part for part in filters)
    assert filters[-1] == "Все файлы (*)"


def test_save_dialog_offers_every_writable_format():
    """В сохранении должны быть все форматы, которые программа умеет писать.

    Раньше список был написан в окне руками, и в нём не оказалось `.sav`:
    сохранить набор в формате SPSS через меню было нельзя.
    """
    filters = save_dialog_filters().split(";;")
    joined = " ".join(filters)
    for extension in ("*.wndata", "*.sav", "*.xlsx", "*.csv"):
        assert extension in joined, f"в сохранении нет формата {extension}"
    assert filters[0].startswith("Набор данных Winnow")
    assert filters[-1] == "Все файлы (*)"


def test_format_for_path_maps_extensions():
    assert format_for_path("data.wndata") == "native"
    assert format_for_path("data.sav") == "sav"
    assert format_for_path("data.xlsx") == "xlsx"
    assert format_for_path("data.csv") == "csv"
    # Прежние расширения своего формата открываются по-прежнему: старые файлы
    # не должны перестать работать из-за переименования проекта.
    assert format_for_path("data.stldata") == "native"
    assert format_for_path("data.sld") == "native"
    # Неизвестное расширение не должно молча уходить в чужой формат.
    assert format_for_path("data.unknown") == "native"


def test_old_excel_format_explains_what_to_do(tmp_path):
    """Старый .xls не поддерживается, но сообщение должно подсказывать выход."""
    path = tmp_path / "old.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0")  # подпись старого формата Excel
    with pytest.raises(ValueError) as error:
        read_dataset(path)
    message = str(error.value)
    assert ".xls" in message
    assert "xlsx" in message


def _rich_dataset() -> Dataset:
    """Набор со всеми видами метаданных - чтобы round-trip проверял всё сразу."""
    dataset = Dataset.from_records(
        {
            "gender": [1, 2, 1, 2],
            "age": [20, 35, 41, 29],
            "hours": [10.0, -1.0, 22.5, -1.0],
            "name": ["Аня", "Борис", "Вера", "Глеб"],
        },
        name="Опрос",
    )
    dataset.var("gender").label = "Пол"
    dataset.var("gender").measure = Measure.NOMINAL
    dataset.var("gender").value_labels = {1: "мужской", 2: "женский"}
    dataset.var("age").label = "Возраст"
    dataset.var("age").decimals = 0
    dataset.var("hours").missing = MissingSpec(discrete={-1.0})
    dataset.var("name").var_type = VarType.STRING
    return dataset


def test_native_round_trip_preserves_metadata(tmp_path):
    dataset = _rich_dataset()
    path = write_native(dataset, tmp_path / "data.wndata")
    restored = read_native(path)

    assert restored.name == "Опрос"
    assert restored.names() == dataset.names()
    assert restored.var("gender").label == "Пол"
    assert restored.var("gender").measure is Measure.NOMINAL
    assert restored.var("gender").value_labels == {1: "мужской", 2: "женский"}
    assert restored.var("hours").missing.discrete == {-1.0}
    assert restored.var("age").decimals == 0
    assert restored.var("name").var_type is VarType.STRING
    assert restored.frame.shape == dataset.frame.shape


def test_native_dict_round_trip_is_json_safe():
    payload = dataset_to_dict(_rich_dataset())
    text = json.dumps(payload, ensure_ascii=False)
    restored = dataset_from_dict(json.loads(text))
    assert restored.var("gender").value_labels == {1: "мужской", 2: "женский"}


def test_csv_round_trip_keeps_labels_and_missing(tmp_path):
    dataset = _rich_dataset()
    path = write_dataset(dataset, tmp_path / "data.csv", "csv")
    restored = read_dataset(path)

    assert restored.names() == dataset.names()
    assert restored.var("gender").label == "Пол"
    assert restored.var("gender").value_labels == {1: "мужской", 2: "женский"}
    assert restored.var("hours").missing.discrete == {-1.0}
    # Числовые значения должны остаться числами, а не превратиться в строки.
    assert restored.analysis_series("age").tolist() == [20.0, 35.0, 41.0, 29.0]


@pytest.mark.skipif(
    importlib.util.find_spec("openpyxl") is None, reason="openpyxl не установлен"
)
def test_excel_round_trip(tmp_path):
    dataset = _rich_dataset()
    path = write_dataset(dataset, tmp_path / "data.xlsx", "xlsx")
    restored = read_dataset(path)

    assert restored.names() == dataset.names()
    assert restored.var("gender").value_labels == {1: "мужской", 2: "женский"}
    assert restored.var("gender").measure is Measure.NOMINAL


def test_unknown_extension_is_reported_clearly(tmp_path):
    path = tmp_path / "data.zzz"
    path.write_text("nonsense", encoding="utf-8")
    with pytest.raises(ValueError) as error:
        read_dataset(path)
    assert "не поддерживается" in str(error.value)


def test_sav_format_is_always_available(tmp_path):
    """.sav читается своим парсером, поэтому доступен всегда.

    Внешняя библиотека (pyreadstat) больше не требуется: формат не должен
    выглядеть работающим только при удачном окружении.
    """
    from winnow.data.io.registry import READERS, WRITERS, sav_backend

    assert "sav" in READERS
    assert "sav" in WRITERS
    assert "Winnow" in sav_backend()


def test_dataset_name_defaults_to_file_stem(tmp_path):
    dataset = _rich_dataset()
    path = write_dataset(dataset, tmp_path / "Клинические данные.csv", "csv")
    restored = read_dataset(path)
    assert restored.name == "Клинические данные"


def test_missing_native_file_is_not_a_winnow_dataset(tmp_path):
    path = tmp_path / "bad.wndata"
    path.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_native(path)


def test_files_saved_before_rename_still_open(tmp_path):
    """Набор, сохранённый до переименования проекта, должен открываться.

    Прежний маркер формата и прежнее расширение - часть истории: у человека
    могли остаться файлы, и терять их из-за смены названия нельзя.
    """
    payload = dataset_to_dict(_rich_dataset())
    payload["format"] = "statlab-dataset"
    path = tmp_path / "old.stldata"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    restored = read_dataset(path)
    assert restored.var("gender").label == "Пол"
    assert restored.n_cases == 4
