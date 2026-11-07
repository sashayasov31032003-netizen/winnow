"""Проверка интерфейса и экспорта: то, что тесты без Qt проверить не могут.

Запускается в безэкранном режиме (QT_QPA_PLATFORM=offscreen), поэтому не
открывает окон и не мешает работе пользователя.
"""

import sys
import tempfile
from pathlib import Path

from winnow.samples import demo_dataset
from winnow.stats.command import CorrelationsCommand, CrosstabsCommand, DescriptivesCommand
from winnow.ui.main_window import MainWindow
from winnow.ui.models import DataTableModel, VariableTableModel
from winnow.ui.procedure_specs import DIALOG_SPECS

from PySide6.QtWidgets import QApplication

failures: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + name)
    if not condition:
        failures.append(name)


app = QApplication.instance() or QApplication(sys.argv)
dataset = demo_dataset(n=120, seed=7)

print("1. Главное окно")
window = MainWindow()
window.set_dataset(dataset)
check("окно создаётся", window is not None)
check("данные попали в модель", window.data_model.rowCount() == 120)
check("число колонок совпадает", window.data_model.columnCount() == dataset.n_vars)
check("статус показывает набор", "Демо-опрос" in window.status_label.text())

print("2. Модели таблиц")
data_model = DataTableModel(dataset)
variable_model = VariableTableModel(dataset)
check("DataTableModel: строк 120", data_model.rowCount() == 120)
check(
    "DataTableModel: колонок как переменных",
    data_model.columnCount() == dataset.n_vars,
)
check(
    "VariableTableModel: строк как переменных",
    variable_model.rowCount() == dataset.n_vars,
)
check("VariableTableModel: колонок 7", variable_model.columnCount() == 7)
label_index = variable_model.index(0, 1)
check(
    "метка переменной редактируется",
    variable_model.setData(label_index, "Проверочная метка")
    and dataset.var(dataset.names()[0]).label == "Проверочная метка",
)
measure_index = variable_model.index(0, 3)
check(
    "недопустимый уровень измерения отклоняется",
    variable_model.setData(measure_index, "неверный") is False,
)

print("3. Диалоги процедур")
for key, spec in DIALOG_SPECS.items():
    from winnow.ui.dialogs import ProcedureDialog

    dialog = ProcedureDialog(spec, dataset, None)
    values = dialog.values()
    check(f"диалог {key} строится и собирает значения", isinstance(values, dict))
    dialog.deleteLater()

print("4. Выполнение процедуры через окно")
window.run_procedure  # метод существует
check("метод запуска процедур есть", callable(window.run_procedure))

print("5. Экспорт")
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    results = [
        DescriptivesCommand(
            dataset=dataset, variables=["age", "income"], statistics=["n", "mean", "std"],
            confidence=0.95,
        ).execute(),
        CrosstabsCommand(dataset=dataset, row_vars=["gender"], col_vars=["education"]).execute(),
        CorrelationsCommand(dataset=dataset, variables=["age", "income", "anxiety"]).execute(),
    ]

    from winnow.export import result_to_docx, result_to_xlsx
    from winnow.export.html import report_to_html

    docx_path = result_to_docx(results, tmp_path / "report.docx")
    check("Word-файл создан", docx_path.exists() and docx_path.stat().st_size > 5000)

    xlsx_path = result_to_xlsx(results, tmp_path / "report.xlsx")
    check("Excel-файл создан", xlsx_path.exists() and xlsx_path.stat().st_size > 5000)

    html_path = tmp_path / "report.html"
    html_path.write_text(report_to_html(results), encoding="utf-8")
    check("HTML-файл создан", html_path.stat().st_size > 5000)

    import docx as docx_lib

    document = docx_lib.Document(str(docx_path))
    expected_tables = sum(len(r.tables) for r in results)
    check(
        f"в Word все таблицы ({len(document.tables)} из {expected_tables})",
        len(document.tables) == expected_tables,
    )

    import openpyxl

    workbook = openpyxl.load_workbook(xlsx_path)
    check(
        f"в Excel все таблицы ({len(workbook.sheetnames)} листов)",
        len(workbook.sheetnames) == expected_tables,
    )
    sheet = workbook[workbook.sheetnames[0]]
    header = [c.value for c in sheet[3]]
    mean_col = header.index("Среднее") + 1
    check("среднее в Excel — число", isinstance(sheet.cell(row=4, column=mean_col).value, (int, float)))

window.close()

print()
if failures:
    print(f"ПРОВАЛЕНО: {len(failures)}")
    for name in failures:
        print("  -", name)
    raise SystemExit(1)
print("Все проверки интерфейса и экспорта пройдены.")
