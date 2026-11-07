"""Измеряет кнопки диалогов: хватает ли им ширины для текста.

Помогает найти «надкусанные» подписи: если ширина кнопки меньше, чем нужно
тексту с учётом отступов из таблицы стилей, буквы обрезаются.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton  # noqa: E402

from winnow.samples import demo_dataset  # noqa: E402
from winnow.ui.fonts import apply_base_font  # noqa: E402
from winnow.ui.styles import stylesheet  # noqa: E402
from winnow.ui.variable_dialog import VariableDialog  # noqa: E402


def report(button: QPushButton, label: str) -> None:
    """Сравнивает ширину кнопки с шириной текста.

    Считается не «запас по стилю», а фактический: сколько точек остаётся сверх
    текста. Именно этот запас защищает от обрезки первой буквы при подмене шрифта.
    """
    metrics = button.fontMetrics()
    text = button.text()
    needed = metrics.horizontalAdvance(text)
    reserve = button.width() - needed
    print(
        f"{label}\n"
        f"   ширина кнопки {button.width()}\n"
        f"   ширина текста {needed}\n"
        f"   фактический запас {reserve}\n"
        f"   высота {button.height()}, минимум {button.minimumHeight()}"
    )
    # С каждой стороны должно оставаться не меньше 10 точек.
    if reserve < 20:
        print("   !! ЗАПАСА МАЛО — первая буква может быть обрезана")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_base_font(app)
    app.setStyleSheet(stylesheet("light"))

    dataset = demo_dataset(n=20, seed=1)
    dialog = VariableDialog(dataset.var("gender"), theme="light")
    dialog.resize(640, 620)
    dialog.show()
    app.processEvents()

    box = dialog.findChild(QDialogButtonBox)
    if box is None:
        print("Не найден QDialogButtonBox")
        return 1
    for button in box.buttons():
        report(button, f"кнопка «{button.text()}»")

    dialog.close()
    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
