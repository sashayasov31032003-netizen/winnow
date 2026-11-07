# -*- mode: python ; coding: utf-8 -*-
"""Сборка Winnow в каталог (режим onedir). Это основной способ сборки.

Почему не один файл: сборка в один файл при каждом запуске распаковывает себя во
временный каталог. Если Windows не даёт его создать (переменная TEMP указывает на
несуществующий путь, каталог недоступен, мешает защита), программа не запускается
вовсе - с ошибкой «Could not create temporary directory!». Ошибка возникает ДО
запуска Python, поэтому подсказать что-либо изнутри программы невозможно.

Сборка в каталог ничего не распаковывает и от временного каталога не зависит, а
запускается так же - двойным щелчком по Winnow.exe.

Сборка (обратите внимание на --workpath: у каждой спецификации он свой, иначе
PyInstaller переиспользует промежуточные файлы другой сборки, и значок или состав
могут остаться от прошлого раза):

    python -m PyInstaller --noconfirm --clean --workpath build/onedir winnow.spec

Результат: dist/Winnow/Winnow.exe рядом со служебной папкой _internal.
Переносить программу на другой компьютер нужно ВСЕЙ папкой Winnow.

Для одного файла:

    python -m PyInstaller --noconfirm --clean --workpath build/onefile winnow-onefile.spec

Подпись кода здесь не делается: для этого нужен сертификат. Сборка подписывается
отдельным шагом (signtool), условия зависят от сертификата.
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()
SRC = PROJECT_ROOT / "src"

# Скрытые импорты: модули процедур движок подключает по имени, статический
# анализ их не видит, и без списка программа падала бы при первом же запуске
# процедуры.
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

# Лишние модули Qt: без исключений сборка распухает на сотни мегабайт.
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
    # ВАЖНО: unittest исключать нельзя - его подтягивает numpy при импорте
    # (numpy.testing), и сборка падала бы при первом обращении к статистике.
    "tkinter", "IPython", "matplotlib",
]

a = Analysis(
    [str(SRC / "winnow" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    # Значок кладётся внутрь сборки: он нужен и как значок файла, и на случай,
    # если программа захочет показать его сама.
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
    [],
    exclude_binaries=True,
    name="Winnow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Обычная программа открывается двойным щелчком без чёрного окна консоли.
    # Диагностические сообщения не теряются: они пишутся в winnow.log рядом
    # с программой.
    console=False,
    disable_windowed_traceback=False,
    icon=str(PROJECT_ROOT / "assets" / "winnow.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Winnow",
)
