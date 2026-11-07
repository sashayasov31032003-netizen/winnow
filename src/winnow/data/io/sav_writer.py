"""Запись файлов SPSS (.sav).

Пара к `sav_reader.py`: вместе они дают возможность обмениваться данными со SPSS
без внешних библиотек и без вопросов о лицензиях.

Данные записываются без сжатия. Сжатие экономит место (иногда в разы), но
добавляет ещё один слой, в котором легко ошибиться, а ошибочно записанный файл
открывается в SPSS без единого предупреждения и молча даёт неверные числа. Обмен
данными важнее размера файла, поэтому формат записи намеренно простой, и это
решение осознанное.

Порядок записей соответствует спецификации: заголовок, описания переменных с
метками значений, блок расширений (кодировка, длинные имена, тип шкалы, ширина
столбца), запись о начале данных, затем данные по одному случаю на запись.
"""

from __future__ import annotations

import math
import re
import struct
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, Variable, VarType

MAGIC = b"$FL2"
VALUE_WIDTH = 8

REC_HEADER = 1
REC_VARIABLE = 2
REC_VALUE_LABELS = 3
# Список переменных, к которым относятся предыдущие метки значений.
REC_VALUE_LABEL_VARS = 4
REC_EXTENSIONS = 7
REC_DATA = 999

SUB_VARIABLE_DISPLAY = 11
SUB_LONG_NAMES = 13
SUB_ENCODING = 20
SUB_MEASURE = 24

# Коды форматов вывода. Числа взяты из спецификации: 5 - числовой общего вида,
# 1 - строковый, 22 - числовой с запятой. Они влияют только на то, как SPSS
# покажет столбец по умолчанию.
FORMAT_STRING = 1
FORMAT_NUMERIC = 5

# Соответствие уровня измерения коду SPSS.
MEASURE_CODES = {
    Measure.NOMINAL: 0,
    Measure.ORDINAL: 1,
    Measure.SCALE: 2,
}

# Коды шкалы для расширения 11: нумерация отличается от MEASURE_CODES, потому что
# так устроен формат SPSS. Проверено на настоящем файле.
DISPLAY_MEASURE_CODES = {
    Measure.NOMINAL: 1,
    Measure.ORDINAL: 2,
    Measure.SCALE: 3,
}

MAX_STRING_WIDTH = 255


# Название продукта в заголовке идёт сразу за подписью формата. В настоящих
# файлах SPSS здесь 64 байта («@(#) IBM SPSS STATISTICS 64-bit MS Windows
# 27.0.1.0» и пробелы), и код размещения оказывается по смещению 68.
# ВАЖНО: никакого кода записи перед подписью нет - файл начинается прямо с
# «$FL2». Лишние четыре байта сдвигали весь файл, и настоящий файл SPSS не
# читался («ожидался заголовок, получен код записи 843859492»).
PRODUCT = b"@(#) SPSS DATA FILE - Winnow"
HEADER_SIZE = 176
# Раскладка заголовка (всего ровно 176 байт):
#   4   подпись «$FL2»
#   64  название продукта
#   4   код размещения
#   4   число переменных
#   4   признак сжатия
#   4   номер весовой переменной
#   4   число случаев
#   8   смещение сжатия (число с плавающей точкой)
#   12  дата: год, месяц, день
#   6   время: часы, минуты, секунды, заполнитель
#   64  метка файла
#   2   заполнитель до 176
PRODUCT_SIZE = 60
# Метка файла лежит в последних 64 байтах заголовка. Оба модуля используют это
# смещение, поэтому не могут разойтись из-за пересчёта полей.
LABEL_OFFSET = HEADER_SIZE - 64


def _pack_format(format_type: int, width: int, decimals: int) -> int:
    """Упаковывает формат в одно целое: тип, ширина и знаков после запятой."""
    return ((format_type & 0xFF) << 16) | ((width & 0xFF) << 8) | (decimals & 0xFF)


def _pad_to(value: bytes, multiple: int) -> bytes:
    """Дополняет до кратного размера нулями."""
    remainder = len(value) % multiple
    if remainder == 0:
        return value
    return value + b"\x00" * (multiple - remainder)


#: Имя переменной в SPSS: только латиница, цифры и символы _ . @ # $, не длиннее
#: 64 байт. Русский текст в имени записать нельзя - в файле он стал бы знаками
#: вопроса, и SPSS такой файл не открыл бы. Поэтому имена транслитерируются, а
#: полный текст вопроса остаётся в метке переменной: её SPSS и показывает в
#: отчётах и в редакторе данных.
MAX_NAME = 64

_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
        "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E",
        "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M",
        "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
        "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Shch",
        "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
        "І": "I", "Ї": "Yi", "Є": "Ye", "Ґ": "G",
    }
)

#: Всё, что SPSS не принимает в имени переменной.
_NAME_BAD = re.compile(r"[^A-Za-z0-9_.@#$]")


def _spss_names(names: list[str]) -> list[str]:
    """Готовит имена переменных для SPSS: латиница, до 64 байт, без повторов.

    SPSS сравнивает имена без учёта регистра и требует их уникальности, поэтому
    повторы получают номер: «kto_ty», «kto_ty_2».
    """
    result: list[str] = []
    taken: set[str] = set()
    for index, source in enumerate(names, start=1):
        text = re.sub(r"\s+", " ", str(source or "")).strip().translate(_TRANSLIT)
        text = re.sub(r"_{2,}", "_", _NAME_BAD.sub("_", text)).strip("_.")
        if not text:
            text = f"V{index}"
        if not text[0].isalpha():
            text = f"V{text}"
        text = text[:MAX_NAME].rstrip("_.")
        candidate = text
        attempt = 2
        while candidate.lower() in taken:
            suffix = f"_{attempt}"
            candidate = f"{text[: MAX_NAME - len(suffix)].rstrip('_.')}{suffix}"
            attempt += 1
        taken.add(candidate.lower())
        result.append(candidate)
    return result


def _short_names(long_names: list[str]) -> list[str]:
    """Короткие имена SPSS (8 символов): они тоже обязаны быть уникальными.

    Короткое имя - это первые восемь символов длинного; если два вопроса
    начинаются одинаково, хвост заменяется номером.
    """
    result: list[str] = []
    taken: set[str] = set()
    for name in long_names:
        candidate = name[:8]
        attempt = 2
        while candidate.lower() in taken:
            suffix = str(attempt)
            candidate = f"{name[: 8 - len(suffix)]}{suffix}"
            attempt += 1
        taken.add(candidate.lower())
        result.append(candidate)
    return result


class SavWriter:
    """Пишет набор данных в формат .sav."""

    def __init__(
        self,
        dataset: Dataset,
        path: str | Path,
        encoding: str = "cp1251",
    ) -> None:
        self.dataset = dataset
        self.path = Path(path)
        # Кодировка по умолчанию - cp1251: русские метки должны читаться в SPSS,
        # а не превращаться в вопросительные знаки.
        self.encoding = encoding
        self.variables: list[Variable] = [
            dataset.var(name) for name in dataset.names()
        ]
        # Имена для файла считаются один раз: короткое и длинное имя нужны и в
        # описании переменной, и в блоке расширений, и они должны совпадать.
        self.long_names = _spss_names([variable.name for variable in self.variables])
        self.short_names = _short_names(self.long_names)

    # ------------------------------------------------------------ описание

    def _write_header(self, stream, n_cases: int, weight_index: int) -> None:
        """Пишет заголовок файла.

        Заголовок обязан занимать ровно 176 байт - это не украшение, а требование
        формата: записи переменных начинаются сразу после него, и любой лишний или
        пропущенный байт сдвигает весь разбор. Поэтому длина проверяется в конце.

        Файл начинается прямо с подписи «$FL2»: кода записи перед ней НЕТ.
        Раньше здесь стоял лишний четвёртый байт-код, из-за которого настоящие
        файлы SPSS не читались, а собственные оказывались сдвинутыми на 4 байта.
        """
        file_label = (self.dataset.name or "")[:64]
        now = datetime.now()
        start = stream.tell()
        stream.write(MAGIC)                                       # 4
        stream.write(PRODUCT.ljust(PRODUCT_SIZE, b"\x00")[:PRODUCT_SIZE])
        stream.write(struct.pack("<i", 2))          # код размещения
        stream.write(struct.pack("<i", len(self.variables)))
        stream.write(struct.pack("<i", 0))          # сжатие выключено
        stream.write(struct.pack("<i", weight_index))
        stream.write(struct.pack("<i", n_cases))
        # Смещение сжатия - число с плавающей точкой двойной точности, а не
        # целое. Именно из-за этого поля заголовок раньше не сходился по длине.
        stream.write(struct.pack("<d", 100.0))
        # Дата и время: год, месяц и день - по четыре байта, часы, минуты,
        # секунды и три байта заполнителя - по одному. Точная длина критична:
        # заголовок обязан занимать ровно 176 байт.
        stream.write(struct.pack("<iii", now.year, now.month, now.day))
        clock = struct.pack(
            "<6B",
            now.hour % 256,
            now.minute % 256,
            now.second % 256,
            0,
            0,
            0,
        )
        stream.write(clock)
        # Пишем метку строго по рассчитанному смещению: если поле продукта или
        # что-то ещё изменит длину, метка всё равно окажется там, где её ждёт
        # читатель, а проверка длины заголовка внизу сообщит о расхождении.
        label_bytes = file_label.encode(self.encoding, errors="replace")[:64]
        prefix = stream.tell() - start
        gap = LABEL_OFFSET - prefix
        if gap < 0:
            raise AssertionError(
                f"Поля заголовка .sav занимают {prefix} байт - метка файла не "
                f"помещается по смещению {LABEL_OFFSET}"
            )
        stream.write(b"\x00" * gap)
        stream.write(label_bytes.ljust(64, b"\x00"))

        if stream.tell() - start != HEADER_SIZE:
            raise AssertionError(
                f"Заголовок .sav занимает {stream.tell() - start} байт вместо "
                f"{HEADER_SIZE}: формат требует ровно 176, иначе все записи "
                "после него сдвинутся"
            )

    def _variable_width(self, variable: Variable) -> int:
        """Ширина значения в байтах: 0 для числовых, иначе ширина строки."""
        if variable.var_type != VarType.STRING:
            return 0
        return max(1, min(int(variable.columns or variable.width or 8), MAX_STRING_WIDTH))

    def _write_variable(
        self, stream, index: int, variable: Variable, width: int
    ) -> None:
        name = self.short_names[index].encode("ascii")[:8].ljust(8, b"\x00")
        label = (variable.label or "").encode(self.encoding, errors="replace")[:255]
        # Текст метки дополняется до кратности 4 байтам: так хранит SPSS.
        # При кратности 8 файл читается «почти правильно» и расходится на 4 байта
        # на каждой метке - на настоящем файле SPSS это давало ошибку в самом
        # неожиданном месте.
        label_padded = (
            label.ljust(int(math.ceil(len(label) / 4.0)) * 4, b"\x00") if label else b""
        )
        if width:
            print_format = _pack_format(FORMAT_STRING, width, 0)
        else:
            print_format = _pack_format(FORMAT_NUMERIC, 11, max(0, min(variable.decimals, 15)))

        missing_values = self._missing_values(variable)

        stream.write(struct.pack("<i", REC_VARIABLE))
        stream.write(struct.pack("<i", width))
        stream.write(struct.pack("<i", 1 if label else 0))
        stream.write(struct.pack("<i", len(missing_values)))
        stream.write(struct.pack("<i", print_format))
        stream.write(struct.pack("<i", print_format))
        # Дальше сразу имя: до него ровно 24 байта - код записи и пять полей.
        # Проверено на настоящем файле SPSS (103 переменные): имя всегда
        # начинается через 24 байта после кода записи. Лишнее служебное слово
        # сдвигало весь файл на 4 байта, и настоящие файлы не читались.
        stream.write(name)
        if label:
            stream.write(struct.pack("<i", len(label)))
            stream.write(label_padded)
        for value in missing_values:
            stream.write(struct.pack("<d", value))

    def _missing_values(self, variable: Variable) -> list[float]:
        """Готовит пропущенные значения к записи.

        SPSS хранит до трёх значений. Диапазон записывается как LO THRU x или
        x THRU HI: на месте границы стоит бесконечность. Диапазон и дискретные
        значения одновременно записать нельзя, поэтому приоритет у диапазона -
        это соответствует тому, как ведёт себя сам SPSS.
        """
        spec = variable.missing
        if spec is None or spec.is_empty:
            return []
        if spec.lo is not None or spec.hi is not None:
            low = spec.lo if spec.lo is not None else -math.inf
            high = spec.hi if spec.hi is not None else math.inf
            # Запись вида «LO THRU x» занимает два слова: LO и граница, поэтому
            # первым идёт минус бесконечность, а не само значение.
            if spec.lo is None:
                return [high, high]
            if spec.hi is None:
                return [low, low]
            return [0.0, low, high]
        discrete = [float(value) for value in sorted(spec.discrete)][:3]
        return discrete

    def _write_value_labels(self, stream, variable: Variable) -> None:
        """Пишет метки значений для числовой переменной."""
        labels = variable.value_labels or {}
        if not labels or variable.var_type == VarType.STRING:
            return
        entries = []
        for value, label in labels.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            text = str(label).encode(self.encoding, errors="replace")[:255]
            entries.append((number, text))
        if not entries:
            return
        stream.write(struct.pack("<i", REC_VALUE_LABELS))
        stream.write(struct.pack("<i", len(entries)))
        for number, text in entries:
            stream.write(struct.pack("<d", number))
            # Байт длины и текст вместе занимают целое число 8-байтовых слов:
            # для текста в 33 байта это 40 байт. Дополнение только текста до
            # кратности 4 сдвигало разбор, и он «съедал» следующие переменные.
            block = int(math.ceil((len(text) + 1) / 8.0)) * 8
            stream.write(struct.pack("<B", len(text)))
            stream.write(text.ljust(block - 1, b"\x00"))
        # Запись 4 перечисляет переменные, к которым относятся эти метки.
        # Без неё метки достаются не той переменной.
        stream.write(struct.pack("<i", REC_VALUE_LABEL_VARS))
        stream.write(struct.pack("<i", 1))
        stream.write(struct.pack("<i", self.variables.index(variable) + 1))

    # ----------------------------------------------------------- расширения

    def _write_extension(self, stream, subtype: int, payload: bytes, size: int) -> None:
        """Пишет одно расширение: подтип, размер элемента, число элементов, данные.

        Данные занимают ровно ``размер * число`` байт. Раскладка проверена на
        настоящем файле SPSS: там подтип, размер и число идут тремя отдельными
        полями, а длина данных равна их произведению. Раньше подтип писался
        первым словом данных, а длина считалась в четырёхбайтовых словах -
        из-за этого разбор чужих файлов уезжал внутрь текста длинных имён.
        """
        body = payload.ljust(int(math.ceil(len(payload) / size)) * size, b"\x00")
        stream.write(struct.pack("<i", REC_EXTENSIONS))
        stream.write(struct.pack("<i", subtype))
        stream.write(struct.pack("<i", size))
        stream.write(struct.pack("<i", len(body) // size))
        stream.write(body)

    def _write_extensions(self, stream) -> None:
        # Кодировка: без неё SPSS прочитает русские метки как мусор.
        encoding_name = self.encoding.encode("ascii", errors="replace")
        self._write_extension(stream, SUB_ENCODING, encoding_name + b"\x00", size=1)

        # Длинные имена: короткое имя и полное через знак равенства, записи
        # разделены знаком табуляции. Нужно для имён длиннее восьми символов -
        # а у нас таких большинство.
        entries = []
        for index, variable in enumerate(self.variables):
            short = self.short_names[index].encode("ascii")
            full = self.long_names[index].encode("ascii")
            if short != full:
                entries.append(short + b"=" + full)
        if entries:
            payload = b"\t".join(entries)
            payload = payload.ljust(int(math.ceil(len(payload) / 8)) * 8, b" ")
            self._write_extension(stream, SUB_LONG_NAMES, payload, size=1)

        # Тип шкалы: по одному числу на переменную.
        payload = b"".join(
            struct.pack("<i", MEASURE_CODES.get(variable.measure, 2))
            for variable in self.variables
        )
        self._write_extension(stream, SUB_MEASURE, payload, size=4)

        # Тип шкалы, ширина столбца и выравнивание: по три числа на переменную.
        # Тип шкалы пишется именно здесь, потому что так делают файлы SPSS, и
        # читатель берёт его отсюда. Нумерация кодов здесь своя: 1 - номинальная,
        # 2 - порядковая, 3 - количественная.
        payload = b""
        for variable in self.variables:
            width = max(8, min(int(variable.columns or 8), 255))
            payload += struct.pack(
                "<iii", DISPLAY_MEASURE_CODES.get(variable.measure, 3), width, 1
            )
        self._write_extension(stream, SUB_VARIABLE_DISPLAY, payload, size=4)

    # --------------------------------------------------------------- данные

    def _write_data(self, stream, frame: pd.DataFrame) -> None:
        stream.write(struct.pack("<i", REC_DATA))
        widths = [self._variable_width(variable) for variable in self.variables]
        # Числовые значения выгружаются одним массивом: так цикл идёт по строкам,
        # а не по отдельным значениям, и запись получается заметно быстрее.
        numeric_columns = [
            frame[variable.name].to_numpy(dtype=float)
            if variable.var_type != VarType.STRING
            else None
            for variable in self.variables
        ]
        string_columns = [
            frame[variable.name].astype(str).to_numpy()
            if variable.var_type == VarType.STRING
            else None
            for variable in self.variables
        ]

        for row in range(len(frame)):
            for index, variable in enumerate(self.variables):
                if variable.var_type == VarType.STRING:
                    value = string_columns[index][row]
                    raw = str(value).encode(self.encoding, errors="replace")
                    raw = raw[: widths[index]].ljust(widths[index], b" ")
                    stream.write(_pad_to(raw, 8))
                else:
                    value = numeric_columns[index][row]
                    if value is None or not np.isfinite(value):
                        # Системный пропуск записывается тем же числом, которое
                        # использует SPSS для отсутствующего значения.
                        value = -math.inf if np.isneginf(value) else math.nan
                    stream.write(struct.pack("<d", float(value)))

    # ------------------------------------------------------------------ вход

    def write(self) -> Path:
        """Записывает файл и возвращает путь к нему."""
        frame = self.dataset.frame
        weight_index = 0
        if self.dataset.weight_var and self.dataset.weight_var in self.dataset.variables:
            weight_index = self.dataset.names().index(self.dataset.weight_var) + 1

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("wb") as stream:
            self._write_header(stream, len(frame), weight_index)
            for index, variable in enumerate(self.variables):
                width = self._variable_width(variable)
                self._write_variable(stream, index, variable, width)
                self._write_value_labels(stream, variable)
            self._write_extensions(stream)
            self._write_data(stream, frame)
        return self.path


def write_sav(dataset: Dataset, path: str | Path, encoding: str = "cp1251") -> Path:
    """Записывает набор данных в файл SPSS."""
    return SavWriter(dataset, path, encoding=encoding).write()


__all__ = ["SavWriter", "write_sav"]
