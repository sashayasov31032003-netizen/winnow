"""Ищет крупные светлые пятна: настоящие фоны, а не сглаживание текста.

Отличие от предыдущей проверки: светлым считается не отдельный пиксель, а
область, где светлые пиксели идут подряд. Одиночные светлые точки рядом с
текстом - это сглаживание шрифта, и они игнорируются.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from winnow.samples import demo_dataset  # noqa: E402
from winnow.ui.dialogs import ProcedureDialog  # noqa: E402
from winnow.ui.fonts import apply_base_font  # noqa: E402
from winnow.ui.main_window import MainWindow  # noqa: E402
from winnow.ui.procedure_specs import DIALOG_SPECS  # noqa: E402
from winnow.ui.theme import design_system  # noqa: E402
from winnow.ui.variable_dialog import VariableDialog  # noqa: E402


def scan(widget, label: str) -> None:
    """Считает пиксели светлого фона и находит их координаты.

    Порог по горизонтали небольшой: белым может оказаться узкий элемент -
    угловая кнопка таблицы, полоса прокрутки, разделитель, - и пропустить его
    нельзя.
    """
    image = widget.grab().toImage()
    width, height = image.width(), image.height()
    light_rows: Counter = Counter()
    colors: Counter = Counter()
    samples: dict[int, tuple[int, int]] = {}

    for y in range(0, height, 2):
        run = 0
        run_start = 0
        for x in range(0, width, 2):
            color = image.pixelColor(x, y)
            bright = color.red() + color.green() + color.blue()
            if bright > 660 and color.saturation() < 30:
                if run == 0:
                    run_start = x
                run += 1
                colors[color.name()] += 1
            else:
                if run >= 4:  # подряд >= 8 пикселей
                    light_rows[y] += run
                    samples.setdefault(y, (run_start, run))
                run = 0
        if run >= 4:
            light_rows[y] += run
            samples.setdefault(y, (run_start, run))

    total = sum(light_rows.values())
    print(f"{label}: светлых пикселей фона {total}")
    if light_rows:
        rows = sorted(light_rows)
        bands = []
        start = previous = rows[0]
        for y in rows[1:]:
            if y - previous > 6:
                bands.append((start, previous))
                start = y
            previous = y
        bands.append((start, previous))
        for begin, end in bands:
            xs = [samples[y][0] for y in range(begin, end + 1) if y in samples]
            widths = [samples[y][1] for y in range(begin, end + 1) if y in samples]
            where = f"x от {min(xs)}" if xs else "x неизвестен"
            print(f"   полоса y {begin}..{end}, {where}, ширина до {max(widths) * 2 if widths else 0}")
        print(f"   частые цвета: {[c for c, _ in colors.most_common(5)]}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_base_font(app)
    dataset = demo_dataset(n=60, seed=1)

    window = MainWindow(theme="dark")
    window.resize(1400, 880)
    window.set_dataset(dataset)
    window.show()
    app.processEvents()
    scan(window, "главное окно (данные, без вывода)")

    from winnow.stats.command import CrosstabsCommand, DescriptivesCommand

    window._append_result(
        DescriptivesCommand(
            dataset=dataset, variables=["age"], statistics=["n", "mean", "std"]
        ).execute()
    )
    window._append_result(
        CrosstabsCommand(dataset=dataset, row_vars=["gender"], col_vars=["education"]).execute()
    )
    app.processEvents()
    scan(window, "главное окно (с выводом)")
    window.close()

    dialog = VariableDialog(dataset.var("gender"), theme="dark")
    dialog.resize(640, 620)
    dialog.show()
    app.processEvents()
    scan(dialog, "диалог свойств переменной")
    print(f"   ожидаемый surface: {design_system('dark').palette.surface}")
    dialog.close()

    proc = ProcedureDialog(DIALOG_SPECS["crosstabs"], dataset, None)
    proc.resize(860, 520)
    proc.show()
    app.processEvents()
    scan(proc, "диалог процедуры")
    proc.close()

    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
