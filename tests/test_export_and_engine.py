"""Тесты экспорта вывода и реестра процедур.

Экспорт проверяется по существу: числа в Excel должны быть числами, а не
строками, а таблицы в Word - присутствовать все. Это те свойства, из-за которых
пользователи и ругаются на плохой экспорт.
"""

from __future__ import annotations

import math

import pytest

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.command import CrosstabsCommand, DescriptivesCommand, TTestCommand
from winnow.stats.engine import REGISTRY, REGISTRY_BY_KEY, execute


def _demo_result():
    dataset = demo_dataset(n=80, seed=1)
    return DescriptivesCommand(
        dataset=dataset,
        variables=["age", "income"],
        statistics=["n", "missing", "mean", "std"],
        confidence=0.95,
    ).execute()


def test_html_contains_all_tables():
    from winnow.export.html import report_to_html

    result = _demo_result()
    html = report_to_html([result])
    assert "<table>" in html
    for table in result.tables:
        assert table.title in html


def test_excel_export_keeps_numbers_as_numbers(tmp_path):
    openpyxl = pytest.importorskip("openpyxl", reason="openpyxl не установлен")
    from winnow.export.xlsx import result_to_xlsx

    result = _demo_result()
    path = result_to_xlsx([result], tmp_path / "out.xlsx")
    workbook = openpyxl.load_workbook(path)

    assert len(workbook.sheetnames) == len(result.tables)
    sheet = workbook[workbook.sheetnames[0]]
    # Строка заголовков - 3-я (1-я - заголовок таблицы, 2-я - пустая).
    header = [cell.value for cell in sheet[3]]
    assert "Среднее" in header
    mean_column = header.index("Среднее") + 1
    value = sheet.cell(row=4, column=mean_column).value
    assert isinstance(value, (int, float))
    assert not isinstance(value, str)


def test_docx_export_creates_file_with_tables(tmp_path):
    docx = pytest.importorskip("docx", reason="python-docx не установлен")
    from winnow.export.docx import result_to_docx

    result = _demo_result()
    path = result_to_docx([result], tmp_path / "out.docx")
    document = docx.Document(str(path))

    assert path.exists()
    assert len(document.tables) == len(result.tables)


def test_docx_export_accepts_single_result(tmp_path):
    pytest.importorskip("docx", reason="python-docx не установлен")
    from winnow.export.docx import result_to_docx

    path = result_to_docx(_demo_result(), tmp_path / "single.docx")
    assert path.exists()


# ------------------------------------------------------------- реестр процедур


def test_registry_keys_are_unique_and_consistent():
    keys = [info.key for info in REGISTRY]
    assert len(keys) == len(set(keys))
    for info in REGISTRY:
        assert info.command_type.KEY == info.key, (
            f"{info.command_type.__name__}.KEY={info.command_type.KEY!r} "
            f"не совпадает с ключом реестра {info.key!r}"
        )
        assert info.key in REGISTRY_BY_KEY


def test_execute_dispatches_by_command_key():
    dataset = demo_dataset(n=40, seed=5)
    result = CrosstabsCommand(
        dataset=dataset, row_vars=["gender"], col_vars=["education"]
    ).execute()
    assert result.procedure == "CROSSTABS"
    assert result.tables


def test_execute_fills_syntax_when_runner_does_not():
    dataset = Dataset.from_records({"x": [1.0, 2.0, 3.0], "g": [1, 1, 2]})
    command = TTestCommand(
        dataset=dataset, kind="independent", test_vars=["x"], group_var="g", group_values=[1, 2]
    )
    result = execute(command)
    assert "T-TEST" in result.syntax
    assert "/GROUPS=g(1 2)" in result.syntax


def test_all_procedures_have_dialog_specs():
    """Каждая зарегистрированная процедура должна быть доступна из интерфейса."""
    from winnow.ui.procedure_specs import DIALOG_SPECS

    for info in REGISTRY:
        assert info.key in DIALOG_SPECS, f"нет описания окна для {info.key}"


def test_dialog_specs_build_commands_without_gui():
    """Сборщики команд должны работать без Qt - это позволяет их тестировать."""
    from winnow.ui.procedure_specs import DIALOG_SPECS

    dataset = demo_dataset(n=50, seed=9)
    cases = {
        "descriptives": {"variables": ["age"], "statistics": ["n", "mean"]},
        "frequencies": {"variables": ["gender"]},
        "crosstabs": {"row_vars": ["gender"], "col_vars": ["education"]},
        "ttest": {
            "kind": "independent",
            "test_vars": ["anxiety"],
            "group_var": "gender",
            "group_values": "1, 2",
            "confidence": 0.95,
        },
        "correlations": {"variables": ["age", "income"], "method": "pearson"},
        "anova": {
            "dependent": ["anxiety"],
            "factor": "education",
            "post_hoc": "tukey",
            "confidence": 0.95,
        },
        "nonparametric": {
            "kind": "independent",
            "method": "auto",
            "test_vars": ["anxiety"],
            "group_var": "education",
        },
        "linear_regression": {
            "dependent": "income",
            "predictors": ["age", "anxiety"],
            "confidence": 0.95,
        },
        "logistic_regression": {
            "dependent": "special_software",
            "predictors": ["age", "income"],
            "reference_value": "1",
            "confidence": 0.95,
        },
        "compute": {
            "target": "income_thousands",
            "expression": "income / 1000",
            "label": "Доход в тысячах",
        },
        "recode": {
            "source": "education",
            "target": "higher_education",
            "label": "Есть высшее образование",
            "rules": [
                {"kind": "value", "value": 3, "new_value": 1},
                {"kind": "else", "new_value": 0},
            ],
        },
        "reliability": {
            "items": ["age", "income", "anxiety"],
            "model": "alpha",
        },
        "factor": {
            "variables": ["age", "income", "anxiety", "life_satisfaction"],
            "method": "pca",
            "rotation": "varimax",
            "n_factors": 0,
        },
        "graph": {
            "kind": "histogram",
            "variables": ["income"],
            "bins": 0,
        },
    }
    # Проверка на полноту: у каждой процедуры должно быть и окно, и пример значений.
    # Так новая процедура не останется без теста.
    assert set(cases) == set(DIALOG_SPECS), (
        f"без примера значений: {sorted(set(DIALOG_SPECS) - set(cases))}; "
        f"лишние примеры: {sorted(set(cases) - set(DIALOG_SPECS))}"
    )
    for key, spec in DIALOG_SPECS.items():
        command = spec.build(cases[key], dataset)
        command.validate()
        assert command.syntax()


def test_group_values_parsing_is_tolerant():
    from winnow.ui.procedure_specs import _parse_group_values

    assert _parse_group_values("1, 2") == [1.0, 2.0]
    assert _parse_group_values("1;2") == [1.0, 2.0]
    assert _parse_group_values(" 3 ") == [3.0]
    assert _parse_group_values("") == []
    with pytest.raises(ValueError):
        _parse_group_values("мужской")


def test_demo_dataset_is_reproducible():
    first = demo_dataset(n=30, seed=42)
    second = demo_dataset(n=30, seed=42)
    assert first.frame.equals(second.frame)
    assert first.var("gender").value_labels == second.var("gender").value_labels


def test_demo_dataset_has_valid_metadata():
    dataset = demo_dataset(n=60, seed=3)
    assert dataset.n_cases == 60
    hours = dataset.var("hours_data")
    assert not hours.missing.is_empty
    # Пропущенные коды не должны попадать в расчёт среднего.
    values = dataset.analysis_series("hours_data").dropna()
    assert (values >= 0).all()
    assert not math.isnan(float(values.mean()))
