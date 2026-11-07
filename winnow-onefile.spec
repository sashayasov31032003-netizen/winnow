# -*- mode: python ; coding: utf-8 -*-
"""Сборка Winnow в ОДИН файл. Необязательный вариант - см. предупреждение.

Сборка:
    python -m PyInstaller --noconfirm --clean --workpath build/onefile winnow-onefile.spec

Результат: dist/Winnow.exe (около 100 МБ). Именно этот файл лежит в корне проекта
как Winnow.exe.

ВАЖНО, почему это не основной способ. Сборка в один файл при КАЖДОМ запуске
распаковывает себя во временный каталог. Если Windows не даёт его создать -
переменная TEMP указывает на несуществующий путь, нет прав, мешает защита, -
программа не запускается вовсе, с ошибкой «Could not create temporary directory!».
Ошибку выдаёт загрузчик ДО старта Python, поэтому изнутри программы её не
перехватить и не объяснить. Именно на это наткнулся пользователь.

Поэтому здесь задано runtime_tmpdir="." - распаковка идёт РЯДОМ С ПРОГРАММОЙ, а не
в системный временный каталог. Это снимает ошибку, но появляется другое условие:
папку с программой нельзя держать там, где запрещена запись. Основная сборка
(winnow.spec) не распаковывается вовсе и таких условий не имеет.
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()
SRC = PROJECT_ROOT / "src"

HIDDEN_IMPORTS = [
    "winnow.stats.frequencies",
    "winnow.stats.descriptives",
    "winnow.stats.crosstabs",
    "winnow.stats.ttest",
    "winnow.stats.anova",
    "winnow.stats.nonparametric",
    "winnow.stats.correlations",
    "winnow.stats.regression",
    "winnow.stats.transform",
    "winnow.stats.reliability",
    "winnow.stats.factor",
    "winnow.stats.charts",
    "winnow.stats.expressions",
    "winnow.data.io.sav_reader",
    "winnow.data.io.sav_writer",
    "winnow.syntax.sps",
]

EXCLUDES = [
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtBluetooth",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtLocation", "PySide6.QtMultimedia",
    "PySide6.QtNetworkAuth", "PySide6.QtNfc", "PySide6.QtOpenGL",
    "PySide6.QtPdf", "PySide6.QtPositioning", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtRemoteObjects", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtStateMachine",
    "PySide6.QtTest", "PySide6.QtWebChannel", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    "tkinter", "IPython", "matplotlib",
]

a = Analysis(
    [str(SRC / "winnow" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[(str(PROJECT_ROOT / "assets" / "winnow.ico"), "assets")],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Winnow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(PROJECT_ROOT / "assets" / "winnow.ico"),
    # Распаковка идёт РЯДОМ С ПРОГРАММОЙ, а не в системный временный каталог.
    # Это и снимает ошибку «Could not create temporary directory!»: каталог рядом
    # с .exe существует всегда, а переменная TEMP может указывать на что угодно.
    # Плата: папку с программой нужно держать в месте, доступном для записи.
    runtime_tmpdir=".",
)
