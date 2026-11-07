"""Снимает скриншоты интерфейса Winnow в файлы.

Нужен для проверки внешнего вида без ручного запуска: окно рисуется в
безэкранном режиме и сохраняется в PNG. Так же удобно готовить картинки для
текста дипломной работы.

Использование:
    $env:QT_QPA_PLATFORM = "offscreen"
    python tools/screenshot.py [папка_вывода]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winnow.samples import demo_dataset  # noqa: E402
from winnow.stats.command import (  # noqa: E402
    AnovaCommand,
    CorrelationsCommand,
    CrosstabsCommand,
    DescriptivesCommand,
    FactorCommand,
    LinearRegressionCommand,
    LogisticRegressionCommand,
    NonparametricCommand,
    ReliabilityCommand,
    TTestCommand,
)
from winnow.ui.fonts import apply_base_font  # noqa: E402
from winnow.ui.main_window import MainWindow  # noqa: E402
from winnow.ui.variable_dialog import VariableDialog  # noqa: E402


def _shoot(window, path: Path) -> None:
    """Сохраняет текущее состояние окна в файл."""
    window.grab().save(str(path))
    print(f"  сохранено: {path.name}")


def _flush(app: QApplication, rounds: int = 6) -> None:
    """Даёт Qt время выполнить отложенные перерисовки."""
    for _ in range(rounds):
        app.processEvents()
        QTimer.singleShot(0, lambda: None)
        app.processEvents()


def _prepare_dialog(dialog, app: QApplication, min_width: int = 1140, min_height: int = 560):
    """Показывает диалог в размере, в котором он открывается у пользователя.

    Ширина берётся с запасом: диалог сам считает её по содержимому (сколько
    нужно спискам переменных под самые длинные метки), но безэкранный режим
    сообщает экран 800x800, и размер урезается до него. На настоящем мониторе
    окно открывается шире, поэтому снимок задаёт ширину явно - иначе он показал
    бы обрезанные метки, которых в программе уже нет.
    """
    dialog.show()
    _flush(app)
    hint = dialog.sizeHint()
    dialog.resize(max(hint.width(), min_width), max(hint.height(), min_height))
    _flush(app)
    return dialog


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    # Безэкранный режим часто не имеет шрифтов: без этой строки весь текст
    # отрисуется пустыми прямоугольниками и снимки будут бесполезны.
    loaded = apply_base_font(app)
    window = MainWindow()
    window.resize(1440, 900)
    window.show()
    _flush(app)

    print(f"Шрифт: {loaded.family()} {loaded.pointSize()}pt")
    print("Снимаю экраны:")

    # 1. Приветственный экран.
    window.theme_name = "light"
    window.apply_theme("light")
    # Режим задаётся напрямую, а не через переключатель: снимки должны быть
    # одинаковыми независимо от того, какой режим выбрал тот, кто их снимает, и
    # настройки его машины трогать нельзя.
    window.interface_mode = "simple"
    window._apply_interface_mode()
    window._show_welcome()
    _flush(app)
    _shoot(window, out_dir / "01-welcome-light.png")

    # 2. Загруженный набор данных: в простом режиме это панель подсказок - лицо
    # программы для начинающего, а таблица данных уступает ей место.
    window.set_dataset(demo_dataset())
    _flush(app)
    _shoot(window, out_dir / "02-data-light.png")

    # 2b. Результаты, полученные прямо из подсказок: в выводе первым идёт
    # объяснение простыми словами. Запускаются два исследования подряд - так
    # видно, что результаты не сливаются в одно полотно.
    from PySide6.QtCore import QElapsedTimer

    for scenario_key in ("compare_two_groups", "reliability"):
        scenario = next(
            item for item in window.advisor_panel.scenarios if item.key == scenario_key
        )
        before = len(window.results)
        window.run_scenario(scenario.procedure, dict(scenario.params))
        timer = QElapsedTimer()
        timer.start()
        while len(window.results) == before and timer.elapsed() < 20000:
            app.processEvents()
    _flush(app)
    _shoot(window, out_dir / "02b-advisor-result.png")
    window.results.clear()
    window._refresh_output()
    _flush(app)

    # 2c. Вопросы с несколькими ответами: программа замечает их сама.
    from winnow.core.dataset import Dataset as _Dataset

    multi = _Dataset.from_records(
        {
            "1. Ваш пол": ["1. Мужской", "2. Женский"] * 6,
            "10. Источники информации": [
                "2. Соцсети (YouTube, Telegram);7. Форумы",
                "2. Соцсети (YouTube, Telegram);6. Вебинары;7. Форумы",
                "6. Вебинары",
                "7. Форумы",
                "2. Соцсети (YouTube, Telegram)",
                "6. Вебинары;7. Форумы",
            ]
            * 2,
        }
    )
    window.set_dataset(multi)
    _flush(app)
    _shoot(window, out_dir / "02c-multi-answer.png")
    # Дальше снимаются окна по демо-набору, поэтому его нужно вернуть.
    window.set_dataset(demo_dataset())
    _flush(app)

    # Дальше снимаются экраны, которых в простом режиме не видно: вкладка
    # паспортов переменных и синтаксис. Для них включается экспертный режим.
    window.interface_mode = "expert"
    window._apply_interface_mode()
    _flush(app)

    # 3. Вкладка переменных.
    window.data_tabs.setCurrentIndex(1)
    _flush(app)
    _shoot(window, out_dir / "03-variables-light.png")
    window.data_tabs.setCurrentIndex(0)

    # 4. Диалог процедуры.
    from winnow.ui.dialogs import ProcedureDialog
    from winnow.ui.procedure_specs import DIALOG_SPECS

    dialog = _prepare_dialog(
        ProcedureDialog(DIALOG_SPECS["crosstabs"], window.dataset, window), app
    )
    dialog.grab().save(str(out_dir / "04-dialog-light.png"))
    print("  сохранено: 04-dialog-light.png")
    dialog.close()

    # 4b. Сообщение о неверных параметрах: показывается в самом окне, рядом с
    # полями, которые нужно исправить, и не стирает введённое.
    bad = ProcedureDialog(DIALOG_SPECS["ttest"], window.dataset, window)
    bad.set_value("test_vars", ["anxiety"])
    bad.set_value("group_var", "gender")
    bad.set_value("group_values", "1")
    try:
        bad.spec.build(bad.values(), window.dataset).validate()
    except Exception as exc:  # сообщение берётся настоящее, а не переписанное
        bad.show_error(str(exc))
    _prepare_dialog(bad, app)
    bad.grab().save(str(out_dir / "04b-dialog-error.png"))
    print("  сохранено: 04b-dialog-error.png")
    bad.close()

    # 5. Диалог свойств переменной.
    var_dialog = _prepare_dialog(
        VariableDialog(window.dataset.var("gender"), theme="light", parent=window), app
    )
    var_dialog.grab().save(str(out_dir / "05-variable-light.png"))
    print("  сохранено: 05-variable-light.png")
    var_dialog.close()

    # 5б. Диалог разбиения файла.
    from winnow.ui.split_dialog import SplitFileDialog

    split_dialog = _prepare_dialog(
        SplitFileDialog(window.dataset, theme="light", parent=window), app,
        min_width=560, min_height=460,
    )
    split_dialog.grab().save(str(out_dir / "05b-split-light.png"))
    print("  сохранено: 05b-split-light.png")
    split_dialog.close()

    # 6. Вывод с результатами.
    dataset = window.dataset
    for command in (
        DescriptivesCommand(
            dataset=dataset,
            variables=["age", "income", "anxiety"],
            statistics=["n", "missing", "mean", "std", "min", "max", "skewness"],
            confidence=0.95,
        ),
        AnovaCommand(dataset=dataset, dependent=["income"], factor="education", post_hoc="tukey"),
        CrosstabsCommand(dataset=dataset, row_vars=["gender"], col_vars=["education"]),
        TTestCommand(
            dataset=dataset, kind="independent", test_vars=["anxiety"],
            group_var="gender", group_values=[1, 2],
        ),
        NonparametricCommand(
            dataset=dataset, kind="independent", test_vars=["anxiety"], group_var="education"
        ),
        CorrelationsCommand(dataset=dataset, variables=["age", "income", "anxiety"]),
        LinearRegressionCommand(
            dataset=dataset, dependent="income", predictors=["age", "education", "anxiety"]
        ),
        LogisticRegressionCommand(
            dataset=dataset,
            dependent="special_software",
            predictors=["age", "income"],
            reference_value=1,
        ),
        ReliabilityCommand(
            dataset=dataset, items=["stress1", "stress2", "stress3", "stress4"]
        ),
        FactorCommand(
            dataset=dataset,
            variables=["stress1", "stress2", "stress3", "stress4"],
            rotation="varimax",
        ),
    ):
        window._append_result(command.execute())
    _flush(app)
    window.viewer_tabs.setCurrentIndex(0)
    _flush(app)
    _shoot(window, out_dir / "06-output-light.png")

    # 7. Синтаксис.
    window.viewer_tabs.setCurrentIndex(1)
    _flush(app)
    _shoot(window, out_dir / "07-syntax-light.png")
    window.viewer_tabs.setCurrentIndex(0)

    # 8-11. Тёмная тема.
    window.apply_theme("dark")
    _flush(app)
    _shoot(window, out_dir / "08-output-dark.png")

    window.data_tabs.setCurrentIndex(1)
    _flush(app)
    _shoot(window, out_dir / "09-variables-dark.png")
    window.data_tabs.setCurrentIndex(0)

    dark_dialog = _prepare_dialog(
        ProcedureDialog(DIALOG_SPECS["ttest"], window.dataset, window), app
    )
    dark_dialog.grab().save(str(out_dir / "10-dialog-dark.png"))
    print("  сохранено: 10-dialog-dark.png")
    dark_dialog.close()

    # 11-12. Графики. Они рисуются не через таблицы, а отдельным холстом, поэтому
    # снимаются как самостоятельные окна.
    from winnow.stats.charts import ChartCommand, build_chart_data
    from winnow.ui.chart_window import ChartWindow

    chart_jobs = [
        (
            "11-chart-histogram-light.png",
            "light",
            ChartCommand(
                dataset=window.dataset,
                kind="histogram",
                variables=["income"],
                show_normal=True,
            ),
        ),
        (
            "12-chart-scatter-light.png",
            "light",
            ChartCommand(
                dataset=window.dataset, kind="scatter", variables=["age", "income"]
            ),
        ),
        (
            "13-chart-pie-light.png",
            "light",
            ChartCommand(
                dataset=window.dataset, kind="pie", variables=["income"], category="city"
            ),
        ),
        (
            "14-chart-bar-dark.png",
            "dark",
            ChartCommand(
                dataset=window.dataset, kind="bar", variables=["income"], category="education"
            ),
        ),
    ]
    for filename, theme, command in chart_jobs:
        window.apply_theme(theme)
        data = build_chart_data(command)
        chart_window = ChartWindow(data, theme=theme, parent=window)
        chart_window.resize(1000, 640)
        chart_window.show()
        _flush(app)
        chart_window.grab().save(str(out_dir / filename))
        print(f"  сохранено: {filename}")
        chart_window.close()
    window.apply_theme("light")

    window.close()
    print(f"\nВсе скриншоты в: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
