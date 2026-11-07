"""Точка входа Winnow.

Полезно, что интерфейс не единственный способ запуска: команда ``winnow demo``
считает демонстрационный анализ в консоли. Это позволяет проверять ядро без GUI
(например, на сервере или в CI) и служит живым примером для скриптового режима.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _prepare_output() -> Path | None:
    """Готовит вывод для запуска без консоли.

    Оконная сборка (.exe) запускается без консольного окна - так открываются
    обычные программы. Но тогда стандартный вывод некуда писать, и попытка
    что-то напечатать приводит к ошибке. Здесь проверяется, есть ли поток
    вывода, и если нет - он направляется в файл-журнал рядом с программой.

    Возвращает путь к журналу, если он использован.
    """
    log_path: Path | None = None
    if sys.stdout is None or sys.stderr is None:
        # Определяем каталог программы: рядом с .exe в сборке, иначе - домашний.
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.home()
        log_path = base / "winnow.log"
        try:
            stream = open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            # Даже журнал открыть не удалось: подставляем «пустую» заглушку,
            # чтобы программа всё равно работала.
            class _Null:
                def write(self, _text: str) -> int:
                    return 0

                def flush(self) -> None:
                    return None

                def isatty(self) -> bool:
                    return False

            if sys.stdout is None:
                sys.stdout = _Null()  # type: ignore[assignment]
            if sys.stderr is None:
                sys.stderr = _Null()  # type: ignore[assignment]
            return None
        if sys.stdout is None:
            sys.stdout = stream  # type: ignore[assignment]
        if sys.stderr is None:
            sys.stderr = stream  # type: ignore[assignment]

    # Консоль Windows работает в cp1251, и часть символов в ней непредставима:
    # стрелка «→» в подсказках валила печать с UnicodeEncodeError. Непредставимые
    # символы заменяются, а не роняют программу: это диагностический вывод, и
    # терять его из-за одного значка нельзя. В окне и в отчётах стрелка остаётся.
    #
    # Под тестами это не делается намеренно: pytest подменяет поток вывода своим,
    # и перенастройка чужого потока ломает перехват - тесты начинали падать через
    # раз. Настройка нужна только настоящему запуску программы.
    if "pytest" not in sys.modules:
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is None:
                continue
            try:
                if not stream.isatty():
                    # Вывод в файл или в другую программу: UTF-8. Иначе русский
                    # текст уходит в кодировке консоли (cp1251), и тот, кто читает
                    # вывод, получает мусор или ошибку декодирования.
                    reconfigure(encoding="utf-8", errors="replace")
                else:
                    reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    return log_path


def run_demo() -> int:
    """Прогоняет набор процедур на демо-данных и печатает текстовый отчёт."""
    from winnow.samples import demo_dataset
    from winnow.stats.command import (
        AnovaCommand,
        ComputeCommand,
        CorrelationsCommand,
        CrosstabsCommand,
        DescriptivesCommand,
        FactorCommand,
        FrequenciesCommand,
        LinearRegressionCommand,
        LogisticRegressionCommand,
        NonparametricCommand,
        RecodeCommand,
        RecodeRule,
        ReliabilityCommand,
        TTestCommand,
    )

    dataset = demo_dataset()
    print(f"Набор: {dataset.name} ({dataset.summary()})\n")

    commands = [
        DescriptivesCommand(
            dataset=dataset,
            variables=["age", "income", "anxiety"],
            statistics=["n", "missing", "mean", "std", "min", "max", "skewness"],
            confidence=0.95,
        ),
        FrequenciesCommand(dataset=dataset, variables=["gender", "education"], show_cumulative=True),
        CrosstabsCommand(
            dataset=dataset,
            row_vars=["gender"],
            col_vars=["education"],
            chi_square=True,
            row_percent=True,
        ),
        TTestCommand(
            dataset=dataset,
            kind="independent",
            test_vars=["anxiety"],
            group_var="gender",
            group_values=[1, 2],
        ),
        AnovaCommand(
            dataset=dataset,
            dependent=["income"],
            factor="education",
            post_hoc="tukey",
        ),
        NonparametricCommand(
            dataset=dataset,
            kind="independent",
            test_vars=["anxiety"],
            group_var="education",
        ),
        CorrelationsCommand(
            dataset=dataset, variables=["age", "income", "anxiety", "life_satisfaction"]
        ),
        LinearRegressionCommand(
            dataset=dataset,
            dependent="income",
            predictors=["age", "education", "anxiety"],
        ),
        LogisticRegressionCommand(
            dataset=dataset,
            dependent="special_software",
            predictors=["age", "income", "anxiety"],
            reference_value=1,
        ),
        ComputeCommand(
            dataset=dataset,
            target="income_thousands",
            expression="income / 1000",
            label="Доход, тыс. руб.",
        ),
        RecodeCommand(
            dataset=dataset,
            source="education",
            target="higher_education",
            rules=[
                RecodeRule(kind="range", low=3, high=5, new_value=1, new_label="Есть высшее"),
                RecodeRule(kind="else", new_value=0, new_label="Нет высшего"),
            ],
        ),
        ReliabilityCommand(
            dataset=dataset,
            items=["stress1", "stress2", "stress3", "stress4"],
        ),
        FactorCommand(
            dataset=dataset,
            variables=["stress1", "stress2", "stress3", "stress4"],
            method="pca",
            rotation="varimax",
        ),
    ]

    for command in commands:
        result = command.execute()
        print("=" * 78)
        print(result.to_text())
        print()
    return 0


def run_sav_info(path: str) -> int:
    """Показывает, что удалось прочитать из файла .sav.

    Нужно для проверки без графического интерфейса: видно число переменных и
    случаев, имена и метки. Если файл не открывается, команда печатает понятную
    причину - это быстрее, чем выяснять её в окне.
    """
    from winnow.data.io.sav_reader import SavError, read_sav_native

    try:
        dataset = read_sav_native(path)
    except SavError as exc:
        print(f"Не удалось открыть файл: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Не удалось прочитать файл: {exc}", file=sys.stderr)
        return 1

    print(f"Набор: {dataset.name}")
    print(f"Случаев: {len(dataset.frame)}")
    print(f"Переменных: {len(dataset.variables)}")
    print()
    for name in dataset.names():
        variable = dataset.var(name)
        parts = [f"{name:16s}", variable.var_type.value, variable.measure.value]
        if variable.label:
            parts.append(variable.label)
        if variable.value_labels:
            parts.append(f"метки значений: {len(variable.value_labels)}")
        print("  " + " | ".join(parts))
    return 0


def run_advise(path: str, limit: int = 12) -> int:
    """Показывает профиль набора и подсказки «что можно сделать с этими данными».

    Нужно для двух вещей: посмотреть на подсказки без интерфейса и проверить, что
    они осмысленны на настоящих данных. Пустой список подсказок - тоже ответ:
    значит, набор к анализу не готов, и программа обязана объяснить почему.
    """
    from winnow.data.io.registry import read_dataset
    from winnow.stats.advisor import format_scenarios, suggest_scenarios
    from winnow.stats.profile import format_profile, profile_dataset

    try:
        dataset = read_dataset(path)
    except (ValueError, OSError) as exc:
        print(f"Не удалось открыть файл: {exc}", file=sys.stderr)
        return 1

    profile = profile_dataset(dataset)
    print(f"Набор: {dataset.name}")
    print()
    print(format_profile(profile, limit=limit))
    print()
    print("Что можно сделать с этими данными:")
    print()
    print(format_scenarios(suggest_scenarios(dataset)))
    return 0


def main(argv: list[str] | None = None) -> int:
    # Вывод готовится до всего остального: в оконной сборке консоли нет, и любая
    # попытка напечатать что-то без этого привела бы к падению при запуске.
    log_path = _prepare_output()

    try:
        return _run(argv)
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - сообщаем о любой ошибке запуска
        import traceback

        traceback.print_exc()
        if log_path is not None:
            print(f"\nЗапуск завершился ошибкой: {exc}")
            print(f"Подробности записаны в файл: {log_path}")
        return 1


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        prog="winnow",
        description="Winnow - статистический анализ данных с интерфейсом в духе SPSS",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("gui", help="запустить графический интерфейс (по умолчанию)")
    subparsers.add_parser("demo", help="выполнить демонстрационный анализ в консоли")
    subparsers.add_parser("version", help="показать версию")
    sav_parser = subparsers.add_parser(
        "sav-info", help="показать, что удалось прочитать из файла .sav"
    )
    sav_parser.add_argument("path", help="путь к файлу .sav")
    advise_parser = subparsers.add_parser(
        "advise", help="профиль данных и подсказки, что с ними можно сделать"
    )
    advise_parser.add_argument("path", help="путь к файлу с данными")

    # В оконной сборке аргументов может не быть вовсе: программа запускается
    # двойным щелчком, и это нормально - открывается интерфейс.
    args = parser.parse_args(argv)
    command = args.command or "gui"

    if command == "version":
        from winnow import __version__

        print(f"Winnow {__version__}")
        return 0

    if command == "demo":
        return run_demo()

    if command == "sav-info":
        return run_sav_info(args.path)

    if command == "advise":
        return run_advise(args.path)

    try:
        from winnow.ui.main_window import run as run_gui
    except ImportError as exc:
        print(
            "Не удалось запустить интерфейс: не установлен PySide6.\n"
            f"Подробность: {exc}\n"
            "Установите: pip install PySide6\n"
            "Или запустите консольный режим: winnow demo",
            file=sys.stderr,
        )
        return 2

    return run_gui()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
