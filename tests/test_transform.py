"""Тесты вычисления и перекодирования переменных.

Здесь важны две вещи: что вычисления правильные и что выражение не может
сделать ничего лишнего. Безопасность выражения - не теория: пользователь вводит
его сам, и оно вычисляется на его машине.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.command import (
    CommandError,
    ComputeCommand,
    RecodeCommand,
    RecodeRule,
)
from winnow.stats.expressions import check_expression, evaluate
from winnow.stats.transform import apply_recode, run_compute, run_recode


def _dataset() -> Dataset:
    return Dataset.from_records(
        {
            "age": [20, 30, 40, 50, 60],
            "income": [10000.0, 20000.0, 30000.0, 40000.0, 50000.0],
            "gender": [1, 2, 1, 2, 1],
        }
    )


# ------------------------------------------------------------- выражения


def test_expression_arithmetic():
    variables = {"a": np.array([1.0, 2.0]), "b": np.array([3.0, 4.0])}
    assert evaluate("a + b", variables).tolist() == [4.0, 6.0]
    assert evaluate("a * 2 - 1", variables).tolist() == [1.0, 3.0]
    assert evaluate("(a + b) / 2", variables).tolist() == [2.0, 3.0]
    assert evaluate("b // a", variables).tolist() == [3.0, 2.0]
    assert evaluate("b % a", variables).tolist() == [0.0, 0.0]
    assert evaluate("a ** 2", variables).tolist() == [1.0, 4.0]


def test_expression_comparisons_and_logic():
    variables = {"age": np.array([20.0, 40.0, 60.0])}
    assert evaluate("age >= 40", variables).tolist() == [False, True, True]
    assert evaluate("age > 20 and age < 60", variables).tolist() == [False, True, False]
    assert evaluate("age < 30 or age > 50", variables).tolist() == [True, False, True]
    assert evaluate("not age == 40", variables).tolist() == [True, False, True]


def test_expression_functions():
    variables = {"x": np.array([-4.0, 9.0])}
    assert evaluate("abs(x)", variables).tolist() == [4.0, 9.0]
    assert evaluate("sqrt(abs(x))", variables).tolist() == [2.0, 3.0]
    assert evaluate("round(sqrt(abs(x)))", variables).tolist() == [2.0, 3.0]
    assert evaluate("max(x, 0)", variables).tolist() == [0.0, 9.0]
    assert evaluate("log(exp(1))", variables) == pytest.approx(1.0)


def test_expression_reports_unknown_name():
    with pytest.raises(CommandError) as error:
        evaluate("нет_такой + 1", {"age": np.array([1.0])})
    assert "Неизвестное имя" in str(error.value)


def test_expression_rejects_attribute_access():
    """Обращение к атрибутам - это попытка выйти за пределы данных."""
    with pytest.raises(CommandError):
        evaluate("age.__class__", {"age": np.array([1.0])})


def test_expression_rejects_unknown_function():
    with pytest.raises(CommandError) as error:
        evaluate("eval('1+1')", {"age": np.array([1.0])})
    assert "не поддерживается" in str(error.value) or "нельзя" in str(error.value)


def test_expression_rejects_import_and_lambda():
    for dangerous in ("__import__('os')", "lambda x: x", "[i for i in range(3)]"):
        with pytest.raises(CommandError):
            evaluate(dangerous, {"age": np.array([1.0])})


def test_expression_hints_about_single_equals():
    with pytest.raises(CommandError) as error:
        evaluate("age = 30", {"age": np.array([30.0])})
    assert "==" in str(error.value)


def test_expression_reports_syntax_error():
    with pytest.raises(CommandError):
        evaluate("age +", {"age": np.array([1.0])})


def test_expression_reports_division_by_zero():
    with pytest.raises(CommandError) as error:
        evaluate("1 / 0", {})
    assert "ноль" in str(error.value)


def test_check_expression_lists_used_variables():
    used = check_expression("income / age + age", ["age", "income", "gender"])
    # Порядок — как в наборе данных, а не как обошёл разборщик.
    assert used == ["age", "income"]
    assert "gender" not in used


def test_expression_empty_is_rejected():
    with pytest.raises(CommandError):
        check_expression("   ", ["age"])


# -------------------------------------------------------------- вычисление


def test_compute_creates_variable_with_correct_values():
    dataset = _dataset()
    result = ComputeCommand(
        dataset=dataset,
        target="income_thousands",
        expression="income / 1000",
        label="Доход в тысячах",
    ).execute()

    assert "income_thousands" in dataset.variables
    assert dataset.frame["income_thousands"].tolist() == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert dataset.var("income_thousands").label == "Доход в тысячах"
    assert result.tables


def test_compute_supports_index_from_several_variables():
    """Типичная задача: среднее из нескольких пунктов опросника."""
    dataset = Dataset.from_records(
        {"q1": [1.0, 2.0, 3.0], "q2": [3.0, 4.0, 5.0], "q3": [2.0, 3.0, 4.0]}
    )
    ComputeCommand(
        dataset=dataset,
        target="scale",
        expression="(q1 + q2 + q3) / 3",
    ).execute()
    assert dataset.frame["scale"].tolist() == [2.0, 3.0, 4.0]


def test_compute_boolean_expression_gives_zero_one():
    dataset = _dataset()
    ComputeCommand(
        dataset=dataset, target="senior", expression="age >= 40"
    ).execute()
    values = dataset.frame["senior"].tolist()
    assert values == [False, False, True, True, True]


def test_compute_refuses_existing_name_without_overwrite():
    dataset = _dataset()
    with pytest.raises(CommandError) as error:
        ComputeCommand(
            dataset=dataset, target="age", expression="age * 2"
        ).execute()
    assert "уже существует" in str(error.value)


def test_compute_overwrite_replaces_values():
    dataset = _dataset()
    ComputeCommand(
        dataset=dataset, target="age", expression="age + 1", overwrite=True
    ).execute()
    assert dataset.frame["age"].tolist() == [21, 31, 41, 51, 61]


def test_compute_rejects_bad_name():
    dataset = _dataset()
    for bad in ("1возраст", "с пробелом", "знак-дефис", ""):
        with pytest.raises(CommandError):
            ComputeCommand(dataset=dataset, target=bad, expression="age").execute()


def test_compute_marks_missing_on_failure():
    """Деление на ноль даёт бесконечность - она становится пропуском.

    Конечное значение от деления на ноль статистически бессмысленно: среднее по
    такой переменной было бы бесконечным. Поэтому бесконечность приравнивается
    к пропуску.
    """
    dataset = Dataset.from_records({"a": [1.0, 0.0, 2.0]})
    result = ComputeCommand(
        dataset=dataset, target="ratio", expression="1 / a"
    ).execute()
    values = dataset.frame["ratio"]
    assert values.notna().sum() == 2
    assert values.isna().sum() == 1
    table = result.tables[0]
    rows = {row[0]: row[1] for row in table.rows}
    assert rows["Пропущено значений"] == "1"


def test_compute_counts_values_in_report():
    dataset = _dataset()
    result = ComputeCommand(
        dataset=dataset, target="double_age", expression="age * 2"
    ).execute()
    table = result.tables[0]
    rows = {row[0]: row[1] for row in table.rows}
    assert rows["Вычислено значений"] == "5"
    assert rows["Пропущено значений"] == "0"


def test_compute_works_with_real_demo_data():
    dataset = demo_dataset(n=50, seed=3)
    ComputeCommand(
        dataset=dataset,
        target="income_per_age",
        expression="income / age",
    ).execute()
    values = dataset.frame["income_per_age"].dropna()
    assert len(values) == 50
    assert (values > 0).all()


# ---------------------------------------------------------- перекодирование


def test_recode_value_rules():
    dataset = _dataset()
    result = RecodeCommand(
        dataset=dataset,
        source="gender",
        target="gender_label",
        rules=[
            RecodeRule(kind="value", value=1, new_value=10, new_label="Мужской"),
            RecodeRule(kind="value", value=2, new_value=20, new_label="Женский"),
        ],
    ).execute()
    assert dataset.frame["gender_label"].tolist() == [10, 20, 10, 20, 10]
    assert dataset.var("gender_label").value_labels == {10: "Мужской", 20: "Женский"}
    assert result.tables


def test_recode_range_rule_is_lower_inclusive_upper_exclusive():
    """Диапазон [a; b) - нижняя граница входит, верхняя нет, как в SPSS."""
    dataset = _dataset()
    RecodeCommand(
        dataset=dataset,
        source="age",
        target="age_group",
        rules=[RecodeRule(kind="range", low=30, high=50, new_value=1)],
    ).execute()
    # Возраст 30 и 40 попали, 50 - нет.
    values = dataset.frame["age_group"].tolist()
    assert math.isnan(values[0])  # 20 не попал
    assert values[1] == 1         # 30 попал
    assert values[2] == 1         # 40 попал
    assert math.isnan(values[3])  # 50 не попал (верхняя граница не входит)
    assert math.isnan(values[4])  # 60 не попал


def test_recode_else_rule_catches_the_rest():
    dataset = _dataset()
    RecodeCommand(
        dataset=dataset,
        source="age",
        target="age_group",
        rules=[
            RecodeRule(kind="range", low=30, high=50, new_value=1),
            RecodeRule(kind="else", new_value=0),
        ],
    ).execute()
    assert dataset.frame["age_group"].tolist() == [0, 1, 1, 0, 0]


def test_recode_last_matching_rule_wins():
    dataset = _dataset()
    RecodeCommand(
        dataset=dataset,
        source="age",
        target="age_group",
        rules=[
            RecodeRule(kind="range", low=0, high=100, new_value=1),
            RecodeRule(kind="range", low=40, high=100, new_value=2),
        ],
    ).execute()
    # Кейс 40 подходит под оба правила, действует последнее.
    assert dataset.frame["age_group"].tolist() == [1, 1, 2, 2, 2]


def test_recode_counts_rules_in_report():
    """Кейсы считаются с учётом уже присвоенных: правило «все остальные» берёт остаток."""
    dataset = _dataset()
    result = RecodeCommand(
        dataset=dataset,
        source="age",
        target="age_group",
        rules=[
            RecodeRule(kind="range", low=20, high=40, new_value=1),
            RecodeRule(kind="else", new_value=2),
        ],
    ).execute()
    counts_table = result.tables[0]
    counts = [row[2] for row in counts_table.rows]
    # Диапазон [20; 40) охватывает 20 и 30, остальные три кейса берёт «все остальные».
    assert counts == [2, 3]
    assert sum(counts) == len(dataset.frame)


def test_recode_warns_about_uncovered_cases():
    dataset = _dataset()
    result = RecodeCommand(
        dataset=dataset,
        source="age",
        target="age_group",
        rules=[RecodeRule(kind="range", low=30, high=50, new_value=1)],
    ).execute()
    assert any("не попали ни под одно правило" in warning for warning in result.warnings)


def test_recode_system_missing_rule():
    dataset = Dataset.from_records({"x": [1.0, np.nan, 3.0]})
    RecodeCommand(
        dataset=dataset,
        source="x",
        target="x_filled",
        rules=[
            RecodeRule(kind="system_missing", new_value=0),
            RecodeRule(kind="else", new_value=-1),
        ],
    ).execute()
    values = dataset.frame["x_filled"].tolist()
    assert values[1] == 0  # пропуск заменён нулём
    assert values[0] == -1 and values[2] == -1  # остальные получили -1


def test_recode_refuses_existing_name():
    dataset = _dataset()
    with pytest.raises(CommandError):
        RecodeCommand(
            dataset=dataset,
            source="age",
            target="income",
            rules=[RecodeRule(kind="else", new_value=0)],
        ).execute()


def test_recode_validates_range_bounds():
    dataset = _dataset()
    with pytest.raises(CommandError) as error:
        RecodeCommand(
            dataset=dataset,
            source="age",
            target="grp",
            rules=[RecodeRule(kind="range", low=50, high=30, new_value=1)],
        ).execute()
    assert "меньше верхней" in str(error.value)


def test_apply_recode_keeps_nan_for_unmatched():
    series = pd.Series([1.0, 2.0, 3.0])
    recoded = apply_recode(series, [RecodeRule(kind="value", value=2, new_value=99)])
    assert recoded.tolist()[0] != recoded.tolist()[0]  # NaN для непопавших
    assert recoded.tolist()[1] == 99


def test_recode_on_demo_dataset_groups_education():
    dataset = demo_dataset(n=100, seed=5)
    RecodeCommand(
        dataset=dataset,
        source="education",
        target="higher_education",
        rules=[
            RecodeRule(kind="range", low=3, high=5, new_value=1, new_label="Есть высшее"),
            RecodeRule(kind="else", new_value=0, new_label="Нет высшего"),
        ],
    ).execute()
    values = dataset.frame["higher_education"]
    assert values.isin([0, 1]).all()
    assert values.sum() > 0
    assert dataset.var("higher_education").value_labels[1] == "Есть высшее"


def test_transform_runners_are_callable_directly():
    dataset = _dataset()
    result = run_compute(
        ComputeCommand(dataset=dataset, target="x2", expression="age * 2")
    )
    assert result.tables
    result = run_recode(
        RecodeCommand(
            dataset=dataset,
            source="age",
            target="age_flag",
            rules=[RecodeRule(kind="else", new_value=1)],
        )
    )
    assert result.tables
