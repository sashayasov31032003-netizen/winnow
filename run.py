"""Запуск Winnow без установки пакета: python run.py [gui|demo|version].

Запускать GUI нужно тем интерпретатором, в котором установлен PySide6. У разных
пользователей их несколько (системные Python, встроенный рантайм DSH), и
интерпретатор по умолчанию легко оказывается "чужим" - тогда окно мгновенно
закрывается с непонятной ошибкой. Поэтому для режима GUI выполняется поиск
подходящего интерпретатора.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"


def _prepare_streams() -> None:
    """Готовит вывод к русскому тексту.

    В консоли кодировка задана системой (cp1251), и часть символов в ней
    непредставима. При выводе в файл или в другую программу это ещё и опасно:
    читатель ждёт UTF-8 и получает ошибку декодирования. Поэтому в трубу пишем
    UTF-8, а в консоль - как есть, заменяя непредставимые символы.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if not stream.isatty():
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


_prepare_streams()

# Сначала проверяется текущий интерпретатор, затем эти.
CANDIDATE_RUNTIMES = (
    Path(r"D:\ds\deepseekk\resources\runtime\primary-runtime\dependencies\python\python.exe"),
)

_PROBE = "import importlib.util as u; raise SystemExit(0 if u.find_spec('PySide6') else 1)"


def _has_pyside6(executable: str) -> bool:
    """Проверяет, установлен ли PySide6 для указанного интерпретатора."""
    try:
        if Path(executable).resolve() == Path(sys.executable).resolve():
            return importlib.util.find_spec("PySide6") is not None
    except OSError:
        return importlib.util.find_spec("PySide6") is not None

    try:
        completed = subprocess.run(
            [executable, "-c", _PROBE], timeout=25, capture_output=True
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _default_mode(argv: list[str]) -> tuple[str, list[str]]:
    """Определяет режим запуска: без аргументов - графический интерфейс."""
    if not argv:
        return "gui", []
    first = argv[0].lower()
    if first in ("gui", "demo", "version", "sav-info", "advise"):
        return first, argv[1:]
    if first in ("-h", "--help", "/?"):
        return "help", []
    # Всё остальное передаём как аргументы интерфейсу.
    return "gui", argv


def _relaunch_gui_with_suitable_runtime(argv: list[str]) -> int | None:
    """Ищет интерпретатор с PySide6 и перезапускает интерфейс им.

    Возвращает код выхода, если перезапуск состоялся, и None, если подходящего
    интерпретатора не нашлось (тогда вызывающий код печатает подсказку).
    """
    try:
        current = Path(sys.executable).resolve()
    except OSError:
        current = None

    for candidate in CANDIDATE_RUNTIMES:
        if not candidate.exists():
            continue
        try:
            if current is not None and candidate.resolve() == current:
                continue
        except OSError:
            pass
        if not _has_pyside6(str(candidate)):
            continue

        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
        print(f"Интерфейс запускается интерпретатором: {candidate}")
        try:
            return subprocess.run(
                [str(candidate), str(ROOT / "run.py"), "gui", *argv], env=env
            ).returncode
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Не удалось запустить {candidate}: {exc}", file=sys.stderr)
            return None
    return None


def _print_help() -> None:
    print(
        "Winnow - статистический анализ данных\n\n"
        "Использование:\n"
        "  python run.py            запустить графический интерфейс\n"
        "  python run.py gui        то же самое\n"
        "  python run.py demo       демонстрационный анализ в консоли (без GUI)\n"
        "  python run.py version    показать версию\n"
        "  python run.py sav-info файл.sav   что удалось прочитать из файла .sav\n"
    )


def _print_missing_gui_help() -> None:
    print(
        "Не удалось запустить графический интерфейс: для этого интерпретатора\n"
        "не установлен PySide6.\n\n"
        f"Текущий интерпретатор:\n  {sys.executable}\n\n"
        "Что делать (любой из вариантов):\n"
        f'  1. Установить интерфейс:  "{sys.executable}" -m pip install PySide6\n'
        "  2. Запустить через Winnow.bat (он сам найдёт подходящий интерпретатор)\n"
        "  3. Посмотреть работу ядра без интерфейса:  python run.py demo\n",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    mode, rest = _default_mode(args)

    if mode == "help":
        _print_help()
        return 0

    sys.path.insert(0, str(SRC))

    if mode == "version":
        from winnow import __version__

        print(f"Winnow {__version__}")
        return 0

    if mode == "demo":
        from winnow.main import run_demo

        return run_demo()

    if mode == "sav-info":
        if not rest:
            print("Укажите путь к файлу .sav", file=sys.stderr)
            return 2
        from winnow.main import run_sav_info

        return run_sav_info(rest[0])

    if mode == "advise":
        if not rest:
            print("Укажите путь к файлу с данными", file=sys.stderr)
            return 2
        from winnow.main import run_advise

        return run_advise(rest[0])

    # Режим GUI.
    if importlib.util.find_spec("PySide6") is None:
        code = _relaunch_gui_with_suitable_runtime(rest)
        if code is None:
            _print_missing_gui_help()
            return 2
        return code

    from winnow.main import main as winnow_main

    return winnow_main(["gui", *rest])


if __name__ == "__main__":
    raise SystemExit(main())
