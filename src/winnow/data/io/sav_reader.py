"""Собственный читатель и писатель файлов SPSS (.sav).

Зачем свой парсер, если есть pyreadstat: лицензии. ReadStat распространяется под
MIT, но его поддержка .sav основана на коде GNU PSPP, который под GPL. Для
открытого проекта это не проблема, для закрытого - риск. Формат .sav
документирован (PSPP Developer's Guide, «System File Format»), и его можно
прочитать самому, чем этот модуль и занимается. Заодно исчезает внешняя
зависимость: файлы SPSS открываются сразу после установки программы.

Реализовано ровно то, что нужно для обмена данными:

* заголовок, метка файла, кодировка текста;
* короткие и длинные имена переменных, метки переменных;
* метки значений, включая строковые;
* пропущенные значения (дискретные и диапазоны);
* тип шкалы (номинальная, порядковая, количественная) и ширина столбца;
* данные без сжатия и со сжатием байт-кодом (обычный режим SPSS).

Чего нет и что честно сообщается ошибкой: строки шире 8 байт без записи
subtype 4, а также очень старые варианты сжатия. Лучше понятная ошибка, чем
молча испорченные данные.
"""

from __future__ import annotations

import math
import struct
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import numpy as np
import pandas as pd

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec, Variable, VarType

MAGIC = b"$FL2"
MAGIC_ROWS = b"$FL3"

# Размер заголовка задан форматом: записи переменных начинаются сразу за ним.
HEADER_SIZE = 176
# Название продукта: 64 байта сразу после подписи. В настоящих файлах SPSS здесь
# стоит «@(#) IBM SPSS STATISTICS 64-bit MS Windows ...» и пробелы.
PRODUCT_SIZE = 60

# Коды записей.
REC_HEADER = 1
REC_VARIABLE = 2
REC_VALUE_LABELS = 3
# Список переменных, к которым относятся предыдущие метки значений. Без разбора
# этой записи разбор описания сдвигается: она стоит между записями меток.
REC_VALUE_LABEL_VARS = 4
REC_DOCUMENT = 6
REC_EXTENSIONS = 7
REC_DATA = 999

# Подтипы расширений.
SUB_INTEGER_INFO = 3
SUB_FLOAT_INFO = 4
SUB_VARIABLE_DISPLAY = 11
SUB_LONG_NAMES = 13
SUB_VERY_LONG_STRINGS = 14
SUB_ENCODING = 20
SUB_LONG_STRING_VALUE_LABELS = 21
SUB_MEASURE = 24

# Коды сжатия. Значения 254 и 255 означают разное: 254 - строка из восьми
# пробелов, 255 - системный пропуск. Перепутать их нельзя.
CODE_IGNORE = 0
CODE_EOF = 252
CODE_NOT_COMPRESSED = 253
CODE_SPACES = 254
CODE_SYSTEM_MISSING = 255

# Ширина поля значения.
VALUE_WIDTH = 8

DIAGONAL_MEASURES = {
    0: Measure.NOMINAL,
    1: Measure.ORDINAL,
    2: Measure.SCALE,
    3: Measure.SCALE,  # 3 - «неизвестно», ближе всего количественная
}

# Коды шкалы в расширении 11 (отображение переменных). Нумерация здесь ДРУГАЯ,
# чем в расширении 24: 1 - номинальная, 2 - порядковая, 3 - количественная.
# Проверено на настоящем файле SPSS: совпадает по всем переменным.
DISPLAY_MEASURES = {
    1: Measure.NOMINAL,
    2: Measure.ORDINAL,
    3: Measure.SCALE,
}


class SavError(RuntimeError):
    """Файл не является корректным .sav или использует неподдерживаемую возможность."""


class _StopRecords(Exception):
    """Служебный сигнал: описание переменных оборвано, переходим к данным.

    Нужен, когда часть описания разобрать не удалось (например, метки значений
    записаны непривычным способом). Лучше прочитать данные и сообщить о пропуске,
    чем не открыть файл вообще.
    """


@dataclass
class SavVariable:
    """Описание переменной до превращения в Variable набора данных."""

    name: str
    label: str = ""
    width: int = 0                 # для строк: ширина в байтах
    print_format: int = 0
    write_format: int = 0
    missing: MissingSpec = field(default_factory=MissingSpec)
    value_labels: dict[Any, str] = field(default_factory=dict)
    measure: Measure = Measure.SCALE
    columns: int = 8
    decimals: int = 2

    @property
    def is_string(self) -> bool:
        return self.width > 0


def parse_print_format(value: int) -> tuple[int, int, int]:
    """Разбирает упакованный код формата в (тип, ширина, знаков после запятой)."""
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def _decode_text(raw: bytes, encoding: str) -> str:
    """Декодирует текст, не падая на неполных последовательностях.

    В метках SPSS иногда встречаются байты, не соответствующие заявленной
    кодировке. Портить из-за этого чтение всего файла нельзя, поэтому спорные
    байты заменяются, а не выбрасывают исключение.

    Если в тексте есть байты UTF-8 (так бывает в файлах SPSS 21 и новее, где
    метки хранятся в UTF-8 независимо от кодировки данных), декодируем как UTF-8.
    Иначе русские метки превращались бы в мусор вида «РЈС‚РѕС‡РЅРёС‚Рµ».
    """
    body = raw.rstrip(b"\x00").strip()
    if not body:
        return ""
    if encoding.lower().replace("-", "") not in ("utf8", "utf8mb4"):
        try:
            decoded = body.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            # Признак настоящего UTF-8: получились осмысленные символы, и байтов
            # многобайтовых последовательностей много.
            if any(ord(character) > 127 for character in decoded) and _utf8_likely(body):
                return decoded
    return raw.decode(encoding, errors="replace").rstrip("\x00").strip()


def _utf8_likely(raw: bytes) -> bool:
    """Похоже ли, что байты действительно записаны в UTF-8.

    Проверка нужна, чтобы не принять за UTF-8 обычный текст cp1251: русские
    буквы в cp1251 идут одиночными байтами и в UTF-8 не складываются.
    """
    multi = sum(1 for byte in raw if byte >= 0xC0)
    return multi * 2 >= len(raw) * 0.4


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise SavError(
            f"Файл обрывается: ожидалось {size} байт, получено {len(data)}"
        )
    return data


class SavReader:
    """Читает .sav последовательно, запись за записью."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.encoding = "cp1251"
        self.variables: list[SavVariable] = []
        self.file_label = ""
        self.weight_name: str | None = None
        self.n_cases = 0
        self.n_variables = 0
        self.compressed = False
        self.bias = 100.0
        self.product = ""
        self._long_names: dict[str, str] = {}
        self._very_long: dict[str, int] = {}
        self._value_label_values: dict[str, list[Any]] = {}
        self._long_value_labels: list[tuple[str, bytes, str]] = []
        self._measure_codes: dict[str, int] = {}
        self._display: dict[str, int] = {}
        # Коды шкалы из расширения 11.
        self._display_measures: dict[str, int] = {}
        # Замечания при чтении: то, что удалось прочитать, но не полностью.
        self.warnings: list[str] = []
        # Признак: метки значений прочитать не удалось.
        self.value_labels_incomplete = False
        # Байты меток переменных: кодировка становится известна позже, поэтому
        # метки перекодируются после чтения всего описания.
        self._raw_variable_labels: list[bytes] = []
        # Сырые байты коротких имён: кодировка файла становится известна позже,
        # поэтому имя, как и метку, приходится перекодировать вторым проходом.
        self._raw_names: list[bytes] = []
        # Метки значений последней записи: нужны, чтобы запись 4 могла перенести
        # их на перечисленные переменные.
        self._pending_labels: dict[Any, str] = {}
        self._pending_variable: SavVariable | None = None

    # ------------------------------------------------------------- заголовок

    def read_header(self) -> None:
        """Читает заголовок файла.

        Файл начинается прямо с подписи «$FL2»: кода записи перед ней нет.
        Раньше здесь ожидался код записи, из-за чего настоящие файлы SPSS не
        читались - вместо подписи разбиралось название продукта.
        """
        start = self.stream.tell()
        magic = _read_exact(self.stream, 4)
        if magic not in (MAGIC, MAGIC_ROWS):
            head = self.stream.read(16)
            raise SavError(
                "Это не файл SPSS: не найдена подпись формата в начале файла. "
                f"Начало файла: {head!r}. "
                "Возможно, это CSV, Excel или другой формат, "
                "либо файл повреждён"
            )
        # Название продукта: 60 байт, дальше начинается код размещения.
        # Точная длина важна - от неё зависят все последующие поля. В настоящем
        # файле SPSS здесь 60 байт, и число переменных оказывается по смещению 68.
        self.product = _decode_text(_read_exact(self.stream, PRODUCT_SIZE), "ascii")
        self.stream.seek(4, 1)                 # код размещения (не используется)
        # Порядок полей: число переменных, признак сжатия, веса, число случаев.
        # Раньше первое поле читалось как число случаев - из-за этого набор из
        # 200 кейсов читался как 14 (столько в нём переменных).
        self.n_variables = struct.unpack("<i", _read_exact(self.stream, 4))[0]
        self.compressed = struct.unpack("<i", _read_exact(self.stream, 4))[0] == 1
        weight_index = struct.unpack("<i", _read_exact(self.stream, 4))[0]
        self.n_cases = struct.unpack("<i", _read_exact(self.stream, 4))[0]
        # Смещение сжатия - число с плавающей точкой двойной точности.
        self.bias = struct.unpack("<d", _read_exact(self.stream, 8))[0] or 100.0
        # Дата создания: три целых (год, месяц, день) и шесть байт (часы, минуты,
        # секунды и заполнитель).
        self.stream.seek(4 * 3 + 6, 1)
        # Метка файла лежит по фиксированному смещению: так читатель и писатель
        # не разойдутся, если поля заголовка изменятся.
        self.stream.seek(start + HEADER_SIZE - 64)
        raw_label = _read_exact(self.stream, 64)
        self.stream.seek(start + HEADER_SIZE)
        self.file_label = ""
        self._raw_label = raw_label
        self._weight_index = weight_index

    # ------------------------------------------------------------ переменные

    def read_variable_records(self) -> None:
        """Читает записи переменных и расширений до начала данных."""
        while True:
            raw = self.stream.read(4)
            if len(raw) < 4:
                raise SavError("Файл обрывается до начала данных")
            record_type = struct.unpack("<i", raw)[0]

            if record_type == REC_VARIABLE:
                self._read_one_variable()
            elif record_type == REC_VALUE_LABELS:
                try:
                    self._read_value_labels()
                except _StopRecords:
                    break
            elif record_type == REC_VALUE_LABEL_VARS:
                self._read_value_label_variables()
            elif record_type == REC_DOCUMENT:
                self._skip_document()
            elif record_type == REC_EXTENSIONS:
                # Код записи уже прочитан этим циклом, поэтому он передаётся
                # внутрь. Если метод прочитает его второй раз, он примет за код
                # поле «размер слова» и уйдёт вперёд на 4 байта.
                self._read_extension_records(record_type)
            elif record_type == REC_DATA:
                break
            elif record_type in (0, 5):
                # Служебные записи, которых в наших файлах нет, но которые
                # встречаются в настоящих. Размер заранее неизвестен, поэтому
                # пропускаем их и помечаем, что файл прочитан не полностью.
                self.warnings.append(
                    f"пропущена служебная запись {record_type} по смещению "
                    f"{self.stream.tell() - 4}"
                )
            else:
                # Неизвестная запись. Если переменные уже прочитаны, описание
                # можно оборвать: данные без сжатия лежат в конце файла, и их
                # положение вычисляется по числу случаев. Это лучше, чем не
                # открыть файл вообще - данные пользователю нужнее меток.
                if self.variables:
                    self.value_labels_incomplete = True
                    self.warnings.append(
                        f"описание переменных оборвано на смещении "
                        f"{self.stream.tell() - 4} (код {record_type}); "
                        "данные прочитаны, часть меток могла быть пропущена"
                    )
                    break
                raise SavError(
                    f"Неизвестный код записи {record_type} по смещению "
                    f"{self.stream.tell() - 4} в описании переменных. "
                    "Возможно, файл создан более новой версией SPSS или повреждён"
                )

        self._apply_long_names()
        self._apply_value_labels()
        # Имена переменных перекодируются здесь же и по той же причине, что и
        # метки: короткое имя занимает 8 байт и записано в кодировке файла, а не
        # в UTF-8. На файлах, где имя набрано по-русски, оно читалось как мусор
        # вида «�������» - при том что метка той же переменной была верной.
        for index, variable in enumerate(self.variables):
            if index >= len(getattr(self, "_raw_names", ())):
                continue
            raw = self._raw_names[index]
            if not raw:
                continue
            # Перекодируется только имя, прочитанное мусором. Трогать все подряд
            # нельзя: у файлов в UTF-8 имя обрезано по 8 байтам и может кончаться
            # на середине буквы, и повторное декодирование испортило бы верное имя.
            if "\ufffd" not in variable.name:
                continue
            decoded = _decode_text(raw, self.encoding)
            # Замена делается, только если новый вариант чистый.
            if decoded and "\ufffd" not in decoded:
                variable.name = decoded
        # Метки переменных перекодируются только сейчас: кодировку задаёт
        # расширение 20, а записи переменных идут раньше него. Без этого часть
        # русских меток читалась как мусор вида «РЎРѕС†РёР°Р»СЊРЅС‹Рµ».
        for index, variable in enumerate(self.variables):
            if index < len(self._raw_variable_labels):
                raw = self._raw_variable_labels[index]
                if raw:
                    variable.label = _decode_text(raw, self.encoding)
        # Метка файла декодируется только сейчас: кодировку задаёт расширение 20,
        # которое встречается уже после заголовка. Расшифровать метку раньше
        # означало бы прочитать русский текст как latin-1.
        if getattr(self, "_raw_label", None):
            self.file_label = _decode_text(self._raw_label, self.encoding)

    def _read_one_variable(self) -> None:
        """Читает запись переменной.

        Код записи уже прочитан вызывающим циклом. Длины проверены на настоящем
        файле SPSS:

        * до имени ровно 24 байта - шесть 4-байтовых полей;
        * имя занимает 8 байт;
        * затем 4 байта длины метки и сама метка, дополненная до кратности 4.

        Ошибка в любом из этих размеров сдвигает весь дальнейший разбор, и
        сообщение получается про чужую запись («неизвестный код записи 0»).
        """
        # Проверено на настоящем файле SPSS (103 переменные): имя начинается
        # ровно через 24 байта после кода записи, то есть поля занимают 20 байт,
        # затем идут 8 байт имени. Вариант «24 байта полей» даёт ноль успешно
        # прочитанных переменных, «20 байт полей» - все 103.
        head = _read_exact(self.stream, 20)
        width, has_label, missing_count, print_format, write_format = struct.unpack(
            "<iiiii", head
        )
        # Короткое имя занимает 8 байт и дополняется до них нулями или
        # пробелами - в файлах SPSS встречается и то, и другое. Если пробелы не
        # убрать, имя «ВОП1 » не найдётся в таблице длинных имён, и переменная
        # останется под коротким именем.
        raw_name = _read_exact(self.stream, 8)
        self._raw_names.append(raw_name)
        name = raw_name.decode("utf-8", errors="replace").rstrip("\x00 ").strip()

        raw_label = b""
        if has_label:
            length = struct.unpack("<i", _read_exact(self.stream, 4))[0]
            # Метка в UTF-8 для длинного русского текста занимает больше 255
            # байт, поэтому верхняя граница взята с запасом. Совсем
            # неправдоподобное значение означает сдвиг разбора.
            if length < 0 or length > 4096:
                raise SavError(
                    f"Недопустимая длина метки переменной: {length} "
                    f"(переменная {name!r}, позиция {self.stream.tell()})"
                )
        # Текст метки дополняется до кратности 4 байтам. Проверено на файле
            # SPSS: метка в 30 байт занимает 32 байта с двумя байтами добивки.
            padded = int(math.ceil(length / 4.0)) * 4
            raw_label = _read_exact(self.stream, padded)[:length]
            label = _decode_text(raw_label, self.encoding)
        else:
            label = ""
        # Байты метки сохраняются: кодировка становится известна только из
        # расширения 20, которое идёт позже. Тогда метку можно перекодировать
        # правильно, а не угадывать.
        self._raw_variable_labels.append(raw_label)

        missing = self._read_missing_values(missing_count, width)
        variable = SavVariable(
            name=name,
            label=label,
            width=width,
            print_format=print_format,
            write_format=write_format,
            missing=missing,
        )
        _type, _width, decimals = parse_print_format(print_format)
        variable.decimals = decimals
        self.variables.append(variable)

    def _read_missing_values(self, count: int, width: int) -> MissingSpec:
        """Читает описание пропущенных значений.

        Дискретных значений может быть до трёх; вместо второго и третьего может
        стоять диапазон (LO THRU x, x THRU HI). Значения занимают 8 байт каждое
        независимо от типа переменной.
        """
        if count <= 0:
            return MissingSpec()
        raw_values = [_read_exact(self.stream, VALUE_WIDTH) for _ in range(count)]
        if width > 0:
            # Пропуски строковых переменных в SPSS задаются текстовыми значениями,
            # но MissingSpec работает только с числами. Пропуски строк честно не
            # поддерживаем: молча записать их как числовые было бы хуже.
            return MissingSpec()

        numbers = [struct.unpack("<d", value)[0] for value in raw_values]
        if count == 3 and numbers[1] == -math.inf and not math.isfinite(numbers[2]):
            # Запись «низкое THRU высокое» - то есть пропущено всё.
            return MissingSpec()
        if count == 2 and numbers[0] == -math.inf:
            return MissingSpec(hi=numbers[1] if math.isfinite(numbers[1]) else None)
        if count == 2 and numbers[1] == math.inf:
            return MissingSpec(lo=numbers[0] if math.isfinite(numbers[0]) else None)
        if count == 3:
            return MissingSpec(
                lo=numbers[1] if math.isfinite(numbers[1]) else None,
                hi=numbers[2] if math.isfinite(numbers[2]) else None,
            )
        return MissingSpec(discrete={value for value in numbers if math.isfinite(value)})

    # ---------------------------------------------------------- метки значений

    def _read_value_labels(self) -> None:
        """Читает метки значений для очередной переменной.

        Если метки разобрать не удалось (встречаются варианты записи, которых нет
        в наших файлах), чтение не прерывается: метки значений - украшение по
        сравнению с самими данными, а пользователь должен получить набор и
        возможность его анализировать. О неудаче сообщается в предупреждениях.
        """
        start_position = self.stream.tell() - 4
        count = struct.unpack("<i", _read_exact(self.stream, 4))[0]
        if count <= 0 or not self.variables:
            return
        variable = self.variables[-1]
        try:
            for _ in range(count):
                raw_value = _read_exact(self.stream, VALUE_WIDTH)
                length_raw = _read_exact(self.stream, 1)
                length = length_raw[0]
                # Правдоподобность длины: текст метки значения редко длиннее
                # 200 байт. Неправдоподобная длина означает, что запись
                # устроена иначе, и продолжать разбор нельзя - иначе «уедет»
                # всё дальнейшее описание.
                if length > 200:
                    raise SavError(f"неправдоподобная длина метки: {length}")
                # Байт длины и текст вместе занимают целое число 8-байтовых слов:
                # для текста в 33 байта это 40 байт (1 + 33 + 6 добивки).
                # Дополнение до кратности 4 сдвигало разбор на 3 байта на каждой
                # метке, и разбор описания переменных обрывался.
                block = int(math.ceil((length + 1) / 8.0)) * 8
                text_bytes = _read_exact(self.stream, block - 1)
                label = _decode_text(text_bytes[:length], self.encoding)
                if variable.is_string:
                    index = struct.unpack("<i", raw_value[:4])[0]
                    self._long_value_labels.append(
                        (variable.name, struct.pack("<i", index), label)
                    )
                else:
                    number = struct.unpack("<d", raw_value)[0]
                    key: Any = int(number) if float(number).is_integer() else float(number)
                    variable.value_labels[key] = label
            # Запоминаем, куда метки попали: следующая запись (код 4) может
            # указать, что относятся они к другим переменным.
            self._pending_variable = variable
            self._pending_labels = dict(variable.value_labels)
        except SavError:
            # Не смогли разобрать метки: пропускаем их и продолжаем с данными.
            # Смещение неизвестно, поэтому дальше описание переменных не читаем.
            self.value_labels_incomplete = True
            self.warnings.append(
                f"метки значений по смещению {start_position} прочитать не удалось "
                "- они пропущены, данные прочитаны"
            )
            raise _StopRecords() from None

    def _read_value_label_variables(self) -> None:
        """Читает запись 4: к каким переменным относятся метки значений.

        Нумерация переменных в файле начинается с единицы. Метки предыдущей
        записи сначала попадают на последнюю прочитанную переменную - так они не
        теряются в файлах без этой записи, - а здесь переносятся на те
        переменные, которые перечислены.
        """
        count = struct.unpack("<i", _read_exact(self.stream, 4))[0]
        if count <= 0:
            return
        indices = [
            struct.unpack("<i", _read_exact(self.stream, 4))[0] for _ in range(count)
        ]
        labels = self._pending_labels
        source = self._pending_variable
        self._pending_labels = {}
        self._pending_variable = None
        if not labels:
            return
        if source is not None:
            for key in labels:
                source.value_labels.pop(key, None)
        for index in indices:
            if 1 <= index <= len(self.variables):
                self.variables[index - 1].value_labels.update(labels)

    def _skip_document(self) -> None:
        """Запись 6: строки документации, по пять на запись, до нулевой строки."""
        while True:
            lines = [_read_exact(self.stream, 80) for _ in range(5)]
            if all(not line.strip(b"\x00 ") for line in lines):
                return

    # ------------------------------------------------------------- расширения

    def _read_extension_records(self, first_code: int) -> None:
        """Читает блок расширений.

        Код первой записи передаётся вызывающим циклом: он его уже прочитал,
        чтобы понять, что начался блок расширений. Метод читает расширения, пока
        они идут, и останавливается, НЕ съедая код начала данных: этот код должен
        прочитать внешний цикл, иначе он не поймёт, что описание закончилось.

        Раскладка расширения проверена на настоящем файле SPSS: подтип, размер
        элемента и число элементов - три отдельных поля, а данных ровно
        ``размер * число`` байт. Раньше считалось ``размер * число * 4``, и
        разбор уезжал внутрь текста длинных имён.
        """
        record_type = first_code
        while record_type == REC_EXTENSIONS:
            subtype = struct.unpack("<i", _read_exact(self.stream, 4))[0]
            size = struct.unpack("<i", _read_exact(self.stream, 4))[0]
            count = struct.unpack("<i", _read_exact(self.stream, 4))[0]
            if size <= 0 or count < 0:
                raise SavError(
                    f"Некорректное расширение: размер элемента {size}, "
                    f"элементов {count}"
                )
            payload = _read_exact(self.stream, size * count)
            self._handle_extension(subtype, size, count, payload)

            raw = self.stream.read(4)
            if len(raw) < 4:
                raise SavError("Файл обрывается в блоке расширений")
            record_type = struct.unpack("<i", raw)[0]
            if record_type == REC_DATA:
                # Возвращаем код обратно: его должен прочитать внешний цикл.
                self.stream.seek(-4, 1)
                return

    def _handle_extension(
        self, subtype: int, size: int, count: int, data: bytes
    ) -> None:
        """Разбирает одно расширение по его подтипу."""
        if count < 1:
            return
        if subtype == SUB_ENCODING:
            # Имя кодировки может быть дополнено нулями; берём часть до первого
            # нуля. Если строка окажется не-ASCII, это не имя кодировки, и менять
            # кодировку по ней нельзя.
            raw_encoding = data.split(b"\x00", 1)[0]
            try:
                encoding = raw_encoding.decode("ascii")
            except UnicodeDecodeError:
                encoding = ""
            if encoding:
                self.encoding = encoding
        elif subtype == SUB_LONG_NAMES:
            self._parse_long_names(data)
        elif subtype == SUB_VERY_LONG_STRINGS:
            self._parse_very_long_strings(size, count, data)
        elif subtype == SUB_INTEGER_INFO:
            self._parse_string_table(data)
        elif subtype == SUB_VARIABLE_DISPLAY:
            self._parse_display(data)
        elif subtype == SUB_MEASURE:
            self._parse_measure(data)

    def _parse_long_names(self, data: bytes) -> None:
        """Расширение 13: длинные имена вида «КОРОТКОЕ=ДлинноеИмя».

        Записи разделены знаком табуляции и дополнены пробелами до кратности
        восьми. Разделение по нулю не работало: нулей между записями нет.
        """
        text = data.decode("utf-8", errors="replace")
        for entry in text.replace("\x00", "\t").split("\t"):
            if "=" not in entry:
                continue
            short, _sep, long_name = entry.partition("=")
            short = short.strip()
            long_name = long_name.strip()
            if short and long_name:
                self._long_names[short] = long_name

    def _parse_very_long_strings(self, size: int, count: int, data: bytes) -> None:
        """Расширение 14: строки длиннее 8 байт."""
        if len(data) < 8 or not self.variables:
            return
        width = struct.unpack("<i", data[4:8])[0]
        self._very_long[self.variables[-1].name] = width

    def _parse_string_table(self, data: bytes) -> None:
        """Таблица строк для строковых меток значений."""
        entries: list[str] = []
        for offset in range(0, len(data) - 7, 8):
            entries.append(_decode_text(data[offset : offset + 8], self.encoding))
        if entries:
            self._value_label_values["_table"] = entries

    def _parse_display(self, data: bytes) -> None:
        """Расширение 11: тип шкалы, ширина столбца и выравнивание.

        На каждую переменную приходится три числа: код шкалы, ширина и
        выравнивание. Именно здесь SPSS хранит тип шкалы - расширения 24 в файлах
        SPSS 27 нет вовсе. Раньше эти числа читались как «ширина и выравнивание»,
        и все переменные оказывались количественными.
        """
        if not self.variables:
            return
        for index, variable in enumerate(self.variables):
            start = index * 12
            if start + 12 > len(data):
                break
            measure_code, width, _alignment = struct.unpack("<iii", data[start : start + 12])
            if measure_code in DISPLAY_MEASURES:
                self._display_measures[variable.name] = measure_code
            if width > 0:
                self._display[variable.name] = width

    def _parse_measure(self, data: bytes) -> None:
        """Расширение 24: тип шкалы по переменным (по одному числу на переменную)."""
        for index, variable in enumerate(self.variables):
            start = index * 4
            if start + 4 <= len(data):
                self._measure_codes[variable.name] = struct.unpack("<i", data[start : start + 4])[0]

    def _apply_long_names(self) -> None:
        for variable in self.variables:
            # Все расширения записаны под КОРОТКИМ именем переменной, а ниже имя
            # может быть заменено на длинное. Поэтому искать нужно по короткому:
            # иначе тип шкалы и ширина столбца теряются при переименовании.
            short_name = variable.name
            long_name = self._long_names.get(short_name)
            if long_name:
                variable.name = long_name
            if short_name in self._very_long:
                variable.width = self._very_long[short_name]
            if short_name in self._measure_codes:
                variable.measure = DIAGONAL_MEASURES.get(
                    self._measure_codes[short_name], variable.measure
                )
            elif short_name in self._display_measures:
                # Расширение 24 встречается редко; в файлах SPSS шкала лежит в
                # расширении 11, поэтому оно используется как основной источник.
                variable.measure = DISPLAY_MEASURES.get(
                    self._display_measures[short_name], variable.measure
                )
            if short_name in self._display:
                variable.columns = max(self._display[short_name], 4)
            if variable.is_string:
                variable.measure = Measure.NOMINAL

    def _apply_value_labels(self) -> None:
        """Привязывает строковые метки значений к переменным через таблицу строк."""
        if not self._long_value_labels:
            return
        table = self._value_label_values.get("_table", [])
        by_name = {variable.name: variable for variable in self.variables}
        for short_name, packed, label in self._long_value_labels:
            variable = by_name.get(short_name) or by_name.get(
                self._long_names.get(short_name, "")
            )
            if variable is None:
                continue
            index = struct.unpack("<i", packed)[0]
            value = table[index] if 0 <= index < len(table) else str(index)
            variable.value_labels[value] = label

    # ------------------------------------------------------------------ данные

    def read_cases(self) -> pd.DataFrame:
        """Читает данные после записи о начале данных."""
        if not self.variables:
            return pd.DataFrame()
        if self.compressed:
            # Сжатые данные нельзя искать от конца файла: их длина заранее
            # неизвестна. Поэтому при обрыве описания продолжаем с текущей
            # позиции, а если она уже ушла вперёд - с начала данных, найденного
            # поиском записи о начале данных.
            if self.value_labels_incomplete:
                self._seek_to_data()
            frame = self._read_compressed_cases()
            # Проверка полноты: если прочиталась лишь малая часть случаев, значит
            # разбор сжатия не совпал с вариантом записи в файле. Молча отдавать
            # обрывок нельзя - пользователь примет его за данные.
            if 0 < self.n_cases and len(frame) < self.n_cases * 0.5:
                raise SavError(
                    f"Прочитано случаев: {len(frame)} из {self.n_cases}. "
                    "Сжатый файл устроен иначе, чем умеет читать программа. "
                    "Откройте его в SPSS и сохраните без сжатия "
                    "(Файл → Сохранить как → Сжать данные не ставить) - "
                    "такой файл читается полностью"
                )
            return frame
        if self.value_labels_incomplete:
            # Данные без сжатия лежат в конце файла вплотную, и их положение
            # вычисляется по числу случаев из заголовка.
            width = self._total_width() * VALUE_WIDTH
            try:
                self.stream.seek(0, 2)
                size = self.stream.tell()
                start = size - width * self.n_cases
                if start > 0:
                    self.stream.seek(start)
            except OSError:
                pass
        return self._read_uncompressed_cases()

    def _seek_to_data(self) -> None:
        """Ищет запись о начале данных (код 999) поиском по файлу.

        Нужна, когда описание переменных разобрано не полностью: по этому коду
        данные находятся надёжнее, чем по пересчёту длин.

        Поиск идёт по всем байтам, а не по каждому четвёртому: запись о данных
        не выровнена по четырём байтам - в настоящем файле SPSS код 999 стоял по
        смещению 29339. Чтение идёт кусками с перекрытием, поэтому файл любого
        размера не загружается в память целиком.
        """
        try:
            position = self.stream.tell()
            self.stream.seek(0)
            marker = struct.pack("<i", REC_DATA)
            overlap = len(marker) - 1
            offset = 0
            tail = b""
            while True:
                chunk = self.stream.read(1 << 20)
                if not chunk:
                    break
                buffer = tail + chunk
                index = buffer.find(marker)
                if index >= 0:
                    # Встаём сразу за записью о данных: оттуда начинаются данные.
                    self.stream.seek(offset - len(tail) + index + len(marker))
                    return
                offset += len(chunk)
                tail = buffer[-overlap:] if overlap else b""
            # Не нашли: возвращаемся куда были.
            self.stream.seek(position)
        except OSError:
            pass

    def _total_width(self) -> int:
        """Ширина записи одного случая в 8-байтовых словах."""
        total = 0
        for variable in self.variables:
            total += 1 if not variable.is_string else int(math.ceil(variable.width / VALUE_WIDTH))
        return total

    def _read_uncompressed_cases(self) -> pd.DataFrame:
        width = self._total_width() * VALUE_WIDTH
        columns: list[list[Any]] = [[] for _ in self.variables]
        cases = 0
        while True:
            # Число случаев в заголовке бывает неточным (-1), поэтому конец файла
            # определяется по факту, а не по счётчику.
            raw = self.stream.read(width)
            if len(raw) < width:
                # Хвост из нулей в конце файла допустим: так выравнивают записи.
                if raw.strip(b"\x00"):
                    raise SavError("Данные обрываются на середине случая")
                break
            # Число случаев из заголовка считается точным: по нему и
            # останавливаемся. Проверять «строка из нулей» нельзя - случай, где
            # все значения нулевые, встречается в настоящих данных, и чтение
            # обрывалось бы на нём.
            if self.n_cases > 0 and cases >= self.n_cases:
                break
            self._decode_case(raw, columns)
            cases += 1
        return self._build_frame(columns, cases)

    def _read_compressed_cases(self) -> pd.DataFrame:
        """Читает сжатые данные.

        Числовое значение кодируется разностью со смещением (bias):

        * 0 - заполнитель, места в наборе не занимает и в счёт не входит;
        * 1..251 - значение ``код - bias``;
        * 252 - конец данных;
        * 253 - значение, которое не сжалось: восемь байт лежат НЕ здесь, а
          сразу после всего блока командных байт, в порядке появления;
        * 254 - строка из восьми пробелов;
        * 255 - системный пропуск.

        Блок командных байт содержит ВОСЕМЬ ЗНАЧЕНИЙ, а не восемь байт: байты
        заполнителя в это число не входят. Проверено на настоящем файле SPSS -
        при счёте по значениям сходятся все случаи, при счёте по байтам
        совпадает лишь часть, дальше разбор уезжает.

        Читать байты для кода 253 на его месте нельзя по той же причине: они
        лежат после блока, и разбор сдвинулся бы на середину следующего.
        """
        columns: list[list[Any]] = [[] for _ in self.variables]
        index = 0
        cases = 0
        pending: list[Any] = []
        finished = False
        block_size = 8

        while not finished:
            # Значения этого блока: None там, где значение лежит после блока.
            slots: list[Any] = []
            escaped: list[tuple[int, Any]] = []
            while len(slots) < block_size:
                raw = self.stream.read(1)
                if not raw:
                    finished = True
                    break
                code = raw[0]
                if code == CODE_EOF:
                    finished = True
                    break
                if code == CODE_IGNORE:
                    # Заполнитель: место в наборе не занимает, счёт не меняет.
                    continue
                variable = self.variables[index]
                if code == CODE_NOT_COMPRESSED:
                    slots.append(None)
                    escaped.append((len(slots) - 1, variable))
                elif code in (CODE_SPACES, CODE_SYSTEM_MISSING):
                    # Для строки это пустое значение, для числа - пропуск.
                    slots.append("" if variable.is_string else np.nan)
                elif variable.is_string:
                    # В строковом поле код задаёт байт символа.
                    slots.append(chr(max(0, min(code, 255))))
                else:
                    slots.append(float(code) - self.bias)
                index += 1
                if index >= len(self.variables):
                    index = 0

            # Несжатые значения идут сразу после блока командных байт, в том же
            # порядке, в каком встретились коды 253.
            for position, variable in escaped:
                if variable.is_string:
                    words = int(math.ceil(variable.width / VALUE_WIDTH))
                    raw_value = self.stream.read(words * VALUE_WIDTH)
                    if len(raw_value) < words * VALUE_WIDTH:
                        finished = True
                        break
                    slots[position] = _decode_text(
                        raw_value[: variable.width], self.encoding
                    )
                else:
                    raw_value = self.stream.read(VALUE_WIDTH)
                    if len(raw_value) < VALUE_WIDTH:
                        finished = True
                        break
                    slots[position] = struct.unpack("<d", raw_value)[0]

            for value in slots:
                pending.append(value)
                if len(pending) >= len(self.variables):
                    for number, column in enumerate(columns):
                        column.append(pending[number])
                    pending = pending[len(self.variables) :]
                    cases += 1
                    if self.n_cases > 0 and cases >= self.n_cases:
                        finished = True
                        break
            if finished:
                break

        return self._build_frame(columns, cases)

    def _decode_case(self, raw: bytes, columns: list[list[Any]]) -> None:
        offset = 0
        for index, variable in enumerate(self.variables):
            if variable.is_string:
                words = int(math.ceil(variable.width / VALUE_WIDTH))
                chunk = raw[offset : offset + words * VALUE_WIDTH]
                columns[index].append(_decode_text(chunk[: variable.width], self.encoding))
                offset += words * VALUE_WIDTH
            else:
                columns[index].append(struct.unpack("<d", raw[offset : offset + VALUE_WIDTH])[0])
                offset += VALUE_WIDTH

    def _build_frame(self, columns: list[list[Any]], cases: int) -> pd.DataFrame:
        if cases == 0:
            return pd.DataFrame(columns=[variable.name for variable in self.variables])
        frame = pd.DataFrame(
            {variable.name: column for variable, column in zip(self.variables, columns)}
        )
        for variable in self.variables:
            if not variable.is_string:
                frame[variable.name] = pd.to_numeric(frame[variable.name], errors="coerce")
        return frame


# ---------------------------------------------------------------------------
# Превращение в набор данных
# ---------------------------------------------------------------------------


def _to_dataset(frame: pd.DataFrame, reader: SavReader, name: str) -> Dataset:
    variables: OrderedDict[str, Variable] = OrderedDict()
    for info in reader.variables:
        variables[info.name] = Variable(
            name=info.name,
            label=info.label,
            measure=info.measure,
            var_type=VarType.STRING if info.is_string else VarType.NUMERIC,
            decimals=info.decimals,
            value_labels=dict(info.value_labels),
            missing=info.missing,
            columns=info.columns if info.is_string else 0,
        )
    dataset = Dataset(frame=frame.reset_index(drop=True), variables=variables, name=name)
    if reader.weight_name and reader.weight_name in dataset.variables:
        dataset.weight_var = reader.weight_name
    return dataset


def read_sav_native(path: str | Path) -> Dataset:
    """Читает .sav своим парсером, без внешних библиотек."""
    path = Path(path)
    with path.open("rb") as stream:
        reader = SavReader(stream)
        reader.read_header()
        reader.read_variable_records()
        # Имя весовой переменной задаётся номером в заголовке, а не именем:
        # переводим номер в имя только после чтения переменных.
        weight_index = getattr(reader, "_weight_index", 0)
        if 0 < weight_index <= len(reader.variables):
            reader.weight_name = reader.variables[weight_index - 1].name
        frame = reader.read_cases()
    # Метка файла в SPSS - это название набора данных, поэтому используем её как
    # имя набора, а имя файла оставляем запасным вариантом.
    return _to_dataset(frame, reader, reader.file_label or path.stem)


__all__ = [
    "HEADER_SIZE",
    "MAGIC",
    "MAGIC_ROWS",
    "SavError",
    "SavReader",
    "SavVariable",
    "parse_print_format",
    "read_sav_native",
]
