"""Чтение и запись наборов данных.

Принцип: метаданные переменных должны переживать сохранение и загрузку. Иначе
пользователь один раз расставит метки значений, а после перезапуска получит
"голые" числа - и это подорвёт доверие ко всему продукту. Поэтому собственный
формат (.wndata) хранит паспорта целиком, а CSV и Excel - насколько возможно.
"""

from winnow.data.io.csv_io import read_csv, write_csv
from winnow.data.io.excel import read_excel, write_excel
from winnow.data.io.native import read_native, write_native
from winnow.data.io.registry import READERS, WRITERS, read_dataset, write_dataset
from winnow.data.io.sav_reader import read_sav_native
from winnow.data.io.sav_writer import write_sav

__all__ = [
    "READERS",
    "WRITERS",
    "read_csv",
    "read_dataset",
    "read_excel",
    "read_native",
    "read_sav_native",
    "write_csv",
    "write_dataset",
    "write_excel",
    "write_native",
    "write_sav",
]
