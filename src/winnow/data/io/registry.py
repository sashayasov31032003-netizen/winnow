"""Реестр форматов: одна точка входа для чтения и записи.

GUI вызывает только read_dataset/write_dataset и не знает, какой формат выбран.
Благодаря этому поддержка нового формата - это одна регистрация, а не правки
в диалогах открытия и сохранения.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from winnow.core.dataset import Dataset
from winnow.data.io.csv_io import read_csv, write_csv
from winnow.data.io.excel import read_excel, write_excel
from winnow.data.io.native import read_native, write_native
from winnow.data.io.sav_reader import read_sav_native
from winnow.data.io.sav_writer import write_sav

DatasetReader = Callable[[str | Path], Dataset]
DatasetWriter = Callable[[Dataset, str | Path], Path]

# Ключ -> (подпись для диалога, фильтр файлов, читатель).
# В подписи маска НЕ указывается: она подставляется при сборке фильтра, иначе в
# диалоге получалось «SPSS Statistics (*.sav) (*.sav)».
# Старое расширение .stldata показано рядом с новым: файлы, сохранённые до
# переименования проекта, должны оставаться видимыми в диалоге открытия.
READERS: dict[str, tuple[str, str, DatasetReader]] = {
    "native": ("Набор данных Winnow", "*.wndata;*.stldata", read_native),
    "sav": ("Данные SPSS", "*.sav", read_sav_native),
    "csv": ("Текстовые данные (CSV)", "*.csv;*.txt", read_csv),
    # Старого формата .xls здесь нет намеренно: его читает не openpyxl, а другая
    # библиотека, которой в проекте нет. Обещать в диалоге то, чего программа не
    # умеет, хуже, чем честно не показывать такие файлы.
    "xlsx": ("Данные Excel", "*.xlsx", read_excel),
}

WRITERS: dict[str, tuple[str, str, DatasetWriter]] = {
    "native": ("Набор данных Winnow", "*.wndata", write_native),
    "sav": ("Данные SPSS", "*.sav", write_sav),
    "csv": ("Текстовые данные (CSV)", "*.csv", write_csv),
    "xlsx": ("Данные Excel", "*.xlsx", write_excel),
}

_EXTENSION_READERS: dict[str, DatasetReader] = {
    ".wndata": read_native,
    # Прежние расширения своего формата: .stldata («StatLab data») и .sld.
    ".stldata": read_native,
    ".sld": read_native,
    ".sav": read_sav_native,
    ".csv": read_csv,
    ".txt": read_csv,
    ".xlsx": read_excel,
}


def read_dataset(path: str | Path) -> Dataset:
    """Читает набор данных, определяя формат по расширению."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".xls":
        # Отдельное сообщение: человеку нужно не «формат не поддерживается», а
        # что делать дальше.
        raise ValueError(
            "Старый формат Excel (.xls) не поддерживается. "
            "Откройте файл в Excel и сохраните как «Книга Excel (*.xlsx)»"
        )
    reader = _EXTENSION_READERS.get(suffix)
    if reader is None:
        raise ValueError(
            f"Формат файла не поддерживается: {path.suffix or '(без расширения)'}. "
            f"Поддерживаются: {', '.join(sorted(_EXTENSION_READERS))}"
        )
    dataset = reader(path)
    if not dataset.name or dataset.name == "Набор1":
        dataset.name = path.stem
    return dataset


def write_dataset(dataset: Dataset, path: str | Path, fmt: str | None = None) -> Path:
    """Записывает набор данных в выбранном формате."""
    path = Path(path)
    if fmt is None:
        fmt = path.suffix.lower().lstrip(".")
    if fmt in ("wndata", "stldata", "sld", ""):
        fmt = "native"
    writer_entry = WRITERS.get(fmt)
    if writer_entry is None:
        raise ValueError(f"Формат для сохранения не поддерживается: {fmt!r}")
    return writer_entry[2](dataset, path)


def sav_backend() -> str:
    """Какой парсер используется для .sav.

    Свой парсер работает всегда, поэтому внешняя библиотека нужна только как
    запасной вариант. Возвращаемое значение показывается пользователю, чтобы не
    было догадок о том, чем открыт файл.
    """
    return "собственный парсер Winnow"


# Порядок фильтров в диалоге открытия. Первым идёт общий фильтр по всем данным:
# человек чаще всего открывает чужой файл - из SPSS или Excel, - и не должен
# сначала разыскивать нужный формат в списке. Свой формат Winnow стоит
# предпоследним: он нужен реже всего, но и не спрятан.
_OPEN_FILTER_ORDER = ("sav", "xlsx", "csv", "native")


def file_dialog_filters() -> str:
    """Строка фильтров для диалога открытия, собранная из реестра.

    Первый фильтр - общий. Без него в проводнике видны файлы только одного
    формата, и нужный файл «не находится», хотя лежит в той же папке.
    """
    parts: list[str] = []
    common: list[str] = []
    for key in _OPEN_FILTER_ORDER:
        entry = READERS.get(key)
        if entry is None:
            continue
        _title, pattern, _reader = entry
        # Свой формат в общий фильтр не входит: его файлы не должны попадаться
        # при выборе данных SPSS или Excel.
        if key != "native":
            common.extend(pattern.split(";"))
    if common:
        parts.append(f"Данные и таблицы ({' '.join(common)})")

    for key in _OPEN_FILTER_ORDER:
        entry = READERS.get(key)
        if entry is None:
            continue
        title, pattern, _reader = entry
        parts.append(f"{title} ({pattern})")

    parts.append("Все файлы (*)")
    return ";;".join(parts)


# Порядок фильтров в диалоге сохранения: сначала свой формат, он ничего не
# теряет, затем обменные.
_SAVE_FILTER_ORDER = ("native", "sav", "xlsx", "csv")


def save_dialog_filters() -> str:
    """Строка фильтров для диалога сохранения, собранная из реестра.

    Список строится из того же реестра, что и запись, поэтому формат, который
    программа умеет писать, не может в нём потеряться. Раньше фильтры были
    написаны в окне руками, и в них не оказалось `.sav` - сохранить набор в
    формате SPSS через меню было нельзя, хотя запись поддерживается.
    """
    parts = []
    for key in _SAVE_FILTER_ORDER:
        entry = WRITERS.get(key)
        if entry is None:
            continue
        title, pattern, _writer = entry
        parts.append(f"{title} ({pattern})")
    parts.append("Все файлы (*)")
    return ";;".join(parts)


def format_for_path(path: str | Path, default: str = "native") -> str:
    """Определяет формат записи по расширению файла.

    Одно место вместо цепочки проверок в интерфейсе: добавили формат в реестр -
    он сразу понимается и здесь.
    """
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in ("wndata", "stldata", "sld"):
        return "native"
    if suffix in WRITERS:
        return suffix
    return default


def writable_extensions() -> list[str]:
    """Расширения, в которые программа умеет сохранять (для подсказок)."""
    return sorted({
        pattern.lstrip("*")
        for _title, pattern, _writer in WRITERS.values()
    })


__all__ = [
    "READERS",
    "WRITERS",
    "file_dialog_filters",
    "format_for_path",
    "read_dataset",
    "sav_backend",
    "save_dialog_filters",
    "write_dataset",
    "writable_extensions",
]
