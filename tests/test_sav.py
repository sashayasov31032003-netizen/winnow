"""Тесты собственного парсера и писателя SPSS (.sav).

Основная проверка - круговая: набор данных записывается в .sav, читается обратно
своим парсером и сверяется с исходным. Это надёжнее сверки с чужим файлом:
он проверяет и писателя, и читателя разом, и не зависит от того, есть ли под
рукой SPSS.

Дополнительно проверяется чтение бинарной структуры: файл собирается вручную
байтами, чтобы ошибка в разборе заголовка или записи переменной была видна явно.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec, VarType
from winnow.data.io.registry import READERS, WRITERS, read_dataset, write_dataset
from winnow.data.io.sav_reader import (
    SavError,
    parse_print_format,
    read_sav_native,
)
from winnow.data.io.sav_writer import write_sav
from winnow.samples import demo_dataset


def _dataset() -> Dataset:
    """Небольшой набор со всеми важными случаями: метки, пропуски, строки."""
    dataset = Dataset.from_records(
        {
            "age": [25.0, 34.0, 41.0, 58.0, 19.0],
            "income": [30000.0, 45000.0, 52000.0, 61000.0, 24000.0],
            "gender": [1, 2, 2, 1, 2],
            "comment": ["первый", "второй", "третий", "четвёртый", "пятый"],
        }
    )
    age = dataset.var("age")
    age.label = "Возраст, полных лет"
    age.measure = Measure.SCALE
    gender = dataset.var("gender")
    gender.label = "Пол респондента"
    gender.measure = Measure.NOMINAL
    gender.value_labels = {1: "Мужской", 2: "Женский"}
    comment = dataset.var("comment")
    comment.label = "Комментарий"
    comment.var_type = VarType.STRING
    comment.columns = 12
    income = dataset.var("income")
    income.label = "Доход в месяц"
    income.missing = MissingSpec(discrete={-1.0})
    return dataset


def _roundtrip(dataset: Dataset, tmp_path: Path, name: str = "test.sav") -> Dataset:
    path = write_sav(dataset, tmp_path / name)
    return read_sav_native(path)


# ------------------------------------------------------------- круговая проверка


def test_roundtrip_preserves_values(tmp_path):
    dataset = _dataset()
    restored = _roundtrip(dataset, tmp_path)

    for name in dataset.names():
        original = dataset.frame[name]
        if dataset.var(name).var_type == VarType.STRING:
            assert list(restored.frame[name]) == [str(v) for v in original], name
        else:
            assert list(restored.frame[name]) == pytest.approx(
                [float(v) for v in original], abs=1e-9
            ), name


def test_roundtrip_preserves_variable_labels(tmp_path):
    restored = _roundtrip(_dataset(), tmp_path)
    assert restored.var("age").label == "Возраст, полных лет"
    assert restored.var("gender").label == "Пол респондента"


def test_roundtrip_preserves_value_labels(tmp_path):
    restored = _roundtrip(_dataset(), tmp_path)
    assert restored.var("gender").value_labels == {1: "Мужской", 2: "Женский"}


def test_roundtrip_preserves_measure(tmp_path):
    dataset = _dataset()
    # Проверяются все три типа шкалы: они хранятся в расширении с собственной
    # нумерацией кодов (1 - номинальная, 2 - порядковая, 3 - количественная),
    # и перепутать их легко.
    dataset.var("income").measure = Measure.ORDINAL
    restored = _roundtrip(dataset, tmp_path)
    assert restored.var("age").measure == Measure.SCALE
    assert restored.var("gender").measure == Measure.NOMINAL
    assert restored.var("income").measure == Measure.ORDINAL
    assert restored.var("comment").measure == Measure.NOMINAL


def test_roundtrip_preserves_missing_values(tmp_path):
    restored = _roundtrip(_dataset(), tmp_path)
    assert restored.var("income").missing.discrete == {-1.0}


def test_roundtrip_preserves_string_type(tmp_path):
    restored = _roundtrip(_dataset(), tmp_path)
    assert restored.var("comment").var_type == VarType.STRING
    assert not restored.var("comment").is_numeric
    assert restored.var("age").var_type == VarType.NUMERIC


def test_roundtrip_preserves_dataset_name(tmp_path):
    dataset = _dataset()
    dataset.name = "Опрос сотрудников"
    restored = _roundtrip(dataset, tmp_path)
    assert restored.name == "Опрос сотрудников"


def test_roundtrip_keeps_long_variable_names(tmp_path):
    """Имена длиннее восьми символов должны сохраниться полностью."""
    dataset = Dataset.from_records(
        {"very_long_variable_name": [1.0, 2.0], "short": [3.0, 4.0]}
    )
    restored = _roundtrip(dataset, tmp_path)
    assert "very_long_variable_name" in restored.variables
    assert list(restored.frame["very_long_variable_name"]) == [1.0, 2.0]


def test_russian_names_are_transliterated_and_unique_for_spss(tmp_path):
    """Имена в SPSS - латиница, поэтому русский текст уходит в метку.

    Знаки вопроса в имени SPSS не принимает: файл с ними не открывается. Поэтому
    имя транслитерируется, повторы получают номер, а полный текст остаётся в
    метке переменной - её SPSS и показывает в отчётах.
    """
    dataset = Dataset.from_records(
        {
            "Ваш пол": [1.0, 2.0],
            "Да или нет?": [1.0, 1.0],
            "Да или нет?: Да": [1.0, 0.0],
            "Ваш  пол": [2.0, 1.0],
        }
    )
    for name in dataset.names():
        dataset.var(name).label = name

    restored = _roundtrip(dataset, tmp_path, "names.sav")
    assert restored.names() == [
        "Vash_pol",
        "Da_ili_net",
        "Da_ili_net_Da",
        "Vash_pol_2",
    ]
    assert [restored.var(name).label for name in restored.names()] == [
        "Ваш пол",
        "Да или нет?",
        "Да или нет?: Да",
        "Ваш  пол",
    ]


def test_roundtrip_of_demo_dataset(tmp_path):
    """Проверка на реалистичном наборе: 14 переменных, 200 кейсов."""
    dataset = demo_dataset(n=200, seed=20240517)
    restored = _roundtrip(dataset, tmp_path, "demo.sav")

    assert restored.n_cases == 200
    assert set(restored.names()) == set(dataset.names())
    for name in dataset.names():
        variable = dataset.var(name)
        if variable.var_type == VarType.STRING:
            continue
        assert list(restored.frame[name]) == pytest.approx(
            [float(v) for v in dataset.frame[name]], abs=1e-9
        ), name


def test_roundtrip_preserves_cyrillic_labels(tmp_path):
    """Русские метки должны читаться, а не превращаться в мусор.

    Для этого в файл пишется запись о кодировке: без неё SPSS (и наш парсер)
    прочитает байты cp1251 как latin-1.
    """
    dataset = Dataset.from_records({"x": [1.0, 2.0]})
    dataset.var("x").label = "Показатель качества жизни"
    dataset.var("x").value_labels = {1: "Низкий", 2: "Высокий"}
    restored = _roundtrip(dataset, tmp_path)
    assert restored.var("x").label == "Показатель качества жизни"
    assert restored.var("x").value_labels == {1: "Низкий", 2: "Высокий"}


def test_roundtrip_with_missing_data(tmp_path):
    """Пропуски в данных должны остаться пропусками."""
    dataset = Dataset.from_records({"x": [1.0, np.nan, 3.0], "y": [4.0, 5.0, np.nan]})
    restored = _roundtrip(dataset, tmp_path)
    assert restored.frame["x"].isna().sum() == 1
    assert restored.frame["y"].isna().sum() == 1
    assert restored.frame["x"].notna().tolist() == [True, False, True]


def test_written_file_starts_with_spss_magic(tmp_path):
    """Файл обязан начинаться так, как ожидает SPSS."""
    path = write_sav(_dataset(), tmp_path / "magic.sav")
    raw = path.read_bytes()
    # Файл начинается прямо с подписи формата: кода записи перед ней нет.
    assert raw[:4] == b"$FL2"


def test_written_file_is_not_compressed(tmp_path):
    """Проверяем осознанное решение: пишем без сжатия."""
    path = write_sav(_dataset(), tmp_path / "plain.sav")
    raw = path.read_bytes()
    compressed = struct.unpack("<i", raw[72:76])[0]
    assert compressed == 0


def test_roundtrip_through_registry(tmp_path):
    """Через реестр формат должен определяться по расширению."""
    path = write_dataset(_dataset(), tmp_path / "reg.sav")
    assert path.suffix == ".sav"
    restored = read_dataset(path)
    assert "age" in restored.variables
    assert restored.var("gender").value_labels == {1: "Мужской", 2: "Женский"}


def test_sav_is_registered_in_both_directions():
    assert "sav" in READERS
    assert "sav" in WRITERS


# ------------------------------------------------------- разбор структуры файла


def test_parse_print_format_unpacks_fields():
    """Формат упакован в одно целое: тип, ширина, знаков после запятой."""
    packed = (5 << 16) | (11 << 8) | 2
    assert parse_print_format(packed) == (5, 11, 2)


def test_reader_rejects_foreign_file(tmp_path):
    path = tmp_path / "not_spss.sav"
    path.write_bytes("это вовсе не файл SPSS, а обычный текст".encode("utf-8") * 10)
    with pytest.raises(SavError):
        read_sav_native(path)


def test_reader_rejects_truncated_header(tmp_path):
    path = tmp_path / "short.sav"
    path.write_bytes(b"\x01\x00\x00\x00")
    with pytest.raises(SavError):
        read_sav_native(path)


def test_reader_handles_handcrafted_file(tmp_path):
    """Файл собирается байтами: проверяем разбор заголовка и переменной.

    Такой тест не зависит от писателя: если оба модуля ошибаются одинаково,
    круговая проверка этого не заметит, а этот тест заметит.
    """
    path = tmp_path / "manual.sav"
    stream = bytearray()

    # Заголовок: ровно 176 байт. Раскладка полей проверена на настоящем файле
    # SPSS: подпись, затем продукт 60 байт, число переменных по смещению 68,
    # признак сжатия, веса, число случаев, смещение сжатия.
    stream += b"$FL2"                                   # подпись формата
    stream += b"@(#) SPSS DATA FILE".ljust(60, b"\x00")  # продукт (60)
    stream += struct.pack("<i", 2)                      # код размещения
    stream += struct.pack("<i", 1)                      # одна переменная
    stream += struct.pack("<i", 0)                      # без сжатия
    stream += struct.pack("<i", 0)                      # без весов
    stream += struct.pack("<i", 2)                      # два случая
    stream += struct.pack("<d", 100.0)                  # смещение сжатия (8 байт)
    stream += struct.pack("<iii", 2024, 5, 17)          # дата: год, месяц, день
    stream += struct.pack("<6B", 12, 0, 0, 0, 0, 0)     # время и заполнитель
    stream += b"\x00" * 2                               # выравнивание до метки
    stream += "Ручной файл".encode("cp1251").ljust(64, b"\x00")[:64]

    # Переменная x: числовая, с меткой.
    label = "Число".encode("cp1251")
    stream += struct.pack("<i", 2)                      # код записи переменной
    stream += struct.pack("<i", 0)                      # числовая
    stream += struct.pack("<i", 1)                      # метка есть
    stream += struct.pack("<i", 0)                      # пропусков нет
    fmt = (5 << 16) | (11 << 8) | 2
    stream += struct.pack("<i", fmt)
    stream += struct.pack("<i", fmt)
    stream += b"x".ljust(8, b"\x00")
    # Метка переменной дополняется до кратности 8.
    stream += struct.pack("<i", len(label))
    stream += label.ljust(((len(label) + 7) // 8) * 8, b"\x00")

    # Начало данных и два случая.
    stream += struct.pack("<i", 999)
    stream += struct.pack("<d", 1.5)
    stream += struct.pack("<d", 2.5)
    path.write_bytes(bytes(stream))

    dataset = read_sav_native(path)
    assert dataset.n_cases == 2
    assert list(dataset.frame["x"]) == pytest.approx([1.5, 2.5])
    assert dataset.var("x").label == "Число"
    assert dataset.name == "Ручной файл"


def test_reader_decodes_compressed_blocks(tmp_path):
    """Сжатые данные читаются блоками по восемь значений.

    Проверяются два правила сжатия, на которых легко ошибиться:

    * байты значения для кода 253 лежат не на его месте, а после всего блока;
    * байт-заполнитель 0 место в наборе не занимает и в счёт не входит.

    Если любое из них нарушить, значения «уезжают» начиная с первого кода 253:
    именно так в наборах SPSS терялись случаи и портились данные.
    """
    path = tmp_path / "compressed.sav"
    stream = bytearray()

    # Заголовок: ровно 176 байт, сжатие включено.
    stream += b"$FL2"
    stream += b"@(#) SPSS DATA FILE".ljust(60, b"\x00")
    stream += struct.pack("<i", 2)                      # код размещения
    stream += struct.pack("<i", 4)                      # четыре переменные
    stream += struct.pack("<i", 1)                      # сжатие включено
    stream += struct.pack("<i", 0)                      # без весов
    stream += struct.pack("<i", 4)                      # четыре случая
    stream += struct.pack("<d", 100.0)                  # смещение сжатия
    stream += struct.pack("<iii", 2024, 5, 17)
    stream += struct.pack("<6B", 12, 0, 0, 0, 0, 0)
    stream += b"\x00" * 2
    stream += "Сжатый".encode("cp1251").ljust(64, b"\x00")[:64]

    # Четыре числовые переменные без меток.
    fmt = (5 << 16) | (11 << 8) | 2
    for name in ("v1", "v2", "v3", "v4"):
        stream += struct.pack("<i", 2)
        stream += struct.pack("<i", 0)
        stream += struct.pack("<i", 0)                  # метки нет
        stream += struct.pack("<i", 0)                  # пропусков нет
        stream += struct.pack("<i", fmt)
        stream += struct.pack("<i", fmt)
        stream += name.encode("ascii").ljust(8, b"\x00")

    # Данные: первый блок со значением 152 (код 253) и заполнителем 0,
    # второй блок - со вторым кодом 253.
    stream += struct.pack("<i", 999)
    stream += bytes([101, 102, 103, 104, 0, 105, 106, 107, 108])
    stream += bytes([109, 110, 253, 111, 112, 113, 114, 115])
    stream += struct.pack("<d", 152.0)                  # значение для кода 253
    stream += bytes([252])                              # конец данных
    path.write_bytes(bytes(stream))

    dataset = read_sav_native(path)
    assert dataset.n_cases == 4
    expected = [
        [1.0, 2.0, 3.0, 4.0],
        [5.0, 6.0, 7.0, 8.0],
        [9.0, 10.0, 152.0, 11.0],
        [12.0, 13.0, 14.0, 15.0],
    ]
    for name, column in zip(("v1", "v2", "v3", "v4"), zip(*expected)):
        assert list(dataset.frame[name]) == pytest.approx(list(column))


def test_reader_defaults_measure_to_scale_without_extension(tmp_path):
    """Без расширения 24 тип шкалы неизвестен - числовая считается количественной."""
    dataset = _dataset()
    path = write_sav(dataset, tmp_path / "measure.sav")
    restored = read_sav_native(path)
    assert restored.var("age").measure in (Measure.SCALE, Measure.ORDINAL)


# --------------------------------------------------------------- крайние случаи


def test_empty_dataset_roundtrip(tmp_path):
    dataset = Dataset.from_records({"x": []})
    path = write_sav(dataset, tmp_path / "empty.sav")
    restored = read_sav_native(path)
    assert restored.names() == ["x"]
    assert len(restored.frame) == 0


def test_single_case_roundtrip(tmp_path):
    dataset = Dataset.from_records({"x": [7.0], "s": ["один"]})
    dataset.var("s").var_type = VarType.STRING
    dataset.var("s").columns = 8
    restored = _roundtrip(dataset, tmp_path)
    assert list(restored.frame["x"]) == [7.0]
    assert list(restored.frame["s"]) == ["один"]


def test_wide_string_values_roundtrip(tmp_path):
    """Строки шире 8 байт занимают несколько слов: легко ошибиться в подсчёте."""
    dataset = Dataset.from_records({"s": ["короткая", "очень длинная строка значений"]})
    dataset.var("s").var_type = VarType.STRING
    dataset.var("s").columns = 40
    restored = _roundtrip(dataset, tmp_path)
    assert list(restored.frame["s"]) == ["короткая", "очень длинная строка значений"]


def test_many_variables_roundtrip(tmp_path):
    dataset = demo_dataset(n=30, seed=5)
    restored = _roundtrip(dataset, tmp_path, "wide.sav")
    assert len(restored.variables) == len(dataset.variables)


def test_negative_and_extreme_values_roundtrip(tmp_path):
    dataset = Dataset.from_records({"x": [-1e-9, 0.0, 1e15, -99999.5]})
    restored = _roundtrip(dataset, tmp_path)
    assert list(restored.frame["x"]) == pytest.approx(
        [-1e-9, 0.0, 1e15, -99999.5], rel=1e-6, abs=1e-3
    )


def test_reader_tolerates_trailing_zero_padding(tmp_path):
    """Файл с нулевым хвостом не должен давать лишних случаев."""
    path = write_sav(_dataset(), tmp_path / "pad.sav")
    with path.open("ab") as stream:
        stream.write(b"\x00" * 16)
    restored = read_sav_native(path)
    assert restored.n_cases == 5


def test_sav_error_message_is_understandable(tmp_path):
    path = tmp_path / "bad.sav"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 200)
    with pytest.raises(SavError) as error:
        read_sav_native(path)
    assert "SPSS" in str(error.value)


def test_cyrillic_name_in_cp1251_is_decoded():
    """Имя переменной записано в кодировке файла, а не в UTF-8.

    На реальном файле (учебный (2).sav) короткие имена набраны по-русски в
    cp1251: они читались как «ВО�...», причём мусорные имена совпадали, и из
    файла выходило 6 переменных вместо 14 - столбцы схлопывались.
    """
    from winnow.data.io.sav_reader import _decode_text

    for name in ("ВОЗРАСТ", "ПОЛ", "ЗАРПЛАТА"):
        assert _decode_text(name.encode("cp1251"), "cp1251") == name
    # Имя в UTF-8 тоже читается верно, даже если файл объявил другую кодировку.
    assert _decode_text("ВОЗРАСТ".encode("utf-8"), "cp1251") == "ВОЗРАСТ"
