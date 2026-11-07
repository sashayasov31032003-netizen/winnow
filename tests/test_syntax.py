"""Тесты синтаксиса: сохранение и разбор файлов `.sps`.

Главная проверка - круговая: команда превращается в текст, текст разбирается
обратно, и поля восстановленной команды сверяются с исходными. Это ловит и
ошибки записи, и ошибки разбора сразу.

Отдельно проверяются места, где разбор легко ломается: точка внутри числа,
кавычки, комментарии, неизвестная команда.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.command import (
    AnovaCommand,
    CommandError,
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
from winnow.syntax.sps import (
    SyntaxError_,
    build_syntax,
    execute_syntax,
    load_syntax,
    parse_subcommands,
    parse_syntax,
    save_syntax,
    split_commands,
)


def _dataset() -> Dataset:
    return demo_dataset(n=60, seed=11)


# --------------------------------------------------------------- разбиение


def test_split_commands_by_period():
    text = "FREQUENCIES VARIABLES=gender.\nDESCRIPTIVES VARIABLES=age."
    commands = split_commands(text)
    assert len(commands) == 2
    assert commands[0][1].startswith("FREQUENCIES")
    assert commands[1][1].startswith("DESCRIPTIVES")


def test_split_ignores_period_inside_number():
    """Точка в десятичном числе не должна разрывать команду."""
    text = "COMPUTE x = y / 1.5.\nFREQUENCIES VARIABLES=x."
    commands = split_commands(text)
    assert len(commands) == 2
    assert "1.5" in commands[0][1]


def test_split_ignores_period_inside_quotes():
    text = "COMPUTE label = 'Среднее. Итог'.\nFREQUENCIES VARIABLES=x."
    commands = split_commands(text)
    assert len(commands) == 2


def test_split_skips_comment_lines():
    text = "* Это комментарий.\nFREQUENCIES VARIABLES=gender."
    commands = split_commands(text)
    assert len(commands) == 1
    assert commands[0][1].strip().startswith("FREQUENCIES")


def test_split_reports_line_numbers():
    text = "* комментарий\n* ещё один\nFREQUENCIES VARIABLES=gender."
    commands = split_commands(text)
    assert commands[0][0] == 3


# ------------------------------------------------------------- подкоманды


def test_parse_subcommands_extracts_keys():
    name, subcommands, positional = parse_subcommands(
        "REGRESSION\n  /DEPENDENT income\n  /METHOD=ENTER age anxiety."
    )
    assert name == "REGRESSION"
    assert subcommands["DEPENDENT"] == "income"
    assert "age" in subcommands["METHOD"]


def test_parse_subcommands_rejects_empty():
    with pytest.raises(CommandError):
        parse_subcommands("   ")


# --------------------------------------------------------------- круговая


def test_frequencies_roundtrip():
    dataset = _dataset()
    original = FrequenciesCommand(dataset=dataset, variables=["gender", "education"])
    text = build_syntax([original])
    restored = parse_syntax(text, dataset)
    assert len(restored) == 1
    assert isinstance(restored[0], FrequenciesCommand)
    assert restored[0].variables == original.variables


def test_descriptives_roundtrip():
    dataset = _dataset()
    original = DescriptivesCommand(dataset=dataset, variables=["age", "income"])
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], DescriptivesCommand)
    assert restored[0].variables == original.variables


def test_correlations_roundtrip():
    dataset = _dataset()
    original = CorrelationsCommand(dataset=dataset, variables=["age", "income"])
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], CorrelationsCommand)
    assert restored[0].variables == original.variables


def test_crosstabs_roundtrip():
    dataset = _dataset()
    original = CrosstabsCommand(dataset=dataset, row_vars=["gender"], col_vars=["education"])
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], CrosstabsCommand)
    assert restored[0].row_vars == ["gender"]
    assert restored[0].col_vars == ["education"]


def test_ttest_roundtrip():
    dataset = _dataset()
    original = TTestCommand(
        dataset=dataset, kind="independent", test_vars=["anxiety"], group_var="gender",
        group_values=[1, 2],
    )
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], TTestCommand)
    assert restored[0].test_vars == ["anxiety"]


def test_anova_roundtrip():
    dataset = _dataset()
    original = AnovaCommand(dataset=dataset, dependent=["income"], factor="education")
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], AnovaCommand)
    assert restored[0].dependent == ["income"]
    assert restored[0].factor == "education"


def test_nonparametric_roundtrip():
    dataset = _dataset()
    original = NonparametricCommand(
        dataset=dataset, kind="independent", test_vars=["anxiety"], group_var="education"
    )
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], NonparametricCommand)
    assert restored[0].test_vars == ["anxiety"]


def test_linear_regression_roundtrip():
    dataset = _dataset()
    original = LinearRegressionCommand(
        dataset=dataset, dependent="income", predictors=["age", "anxiety"]
    )
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], LinearRegressionCommand)
    assert restored[0].dependent == "income"
    assert restored[0].predictors == ["age", "anxiety"]


def test_logistic_regression_roundtrip():
    dataset = _dataset()
    original = LogisticRegressionCommand(
        dataset=dataset, dependent="special_software", predictors=["age", "income"]
    )
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], LogisticRegressionCommand)
    assert restored[0].dependent == "special_software"


def test_compute_roundtrip():
    dataset = _dataset()
    original = ComputeCommand(
        dataset=dataset, target="income_k", expression="income / 1000"
    )
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], ComputeCommand)
    assert restored[0].target == "income_k"
    assert restored[0].expression == "income / 1000"


def test_reliability_roundtrip():
    dataset = _dataset()
    original = ReliabilityCommand(
        dataset=dataset, items=["stress1", "stress2", "stress3", "stress4"]
    )
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], ReliabilityCommand)
    assert restored[0].items == original.items


def test_factor_roundtrip():
    dataset = _dataset()
    original = FactorCommand(
        dataset=dataset, variables=["stress1", "stress2", "stress3", "stress4"]
    )
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], FactorCommand)
    assert restored[0].variables == original.variables


def test_graph_histogram_roundtrip():
    from winnow.stats.charts import ChartCommand

    dataset = _dataset()
    original = ChartCommand(dataset=dataset, kind="histogram", variables=["income"])
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], ChartCommand)
    assert restored[0].kind == "histogram"
    assert restored[0].variables == ["income"]


def test_graph_scatter_roundtrip():
    from winnow.stats.charts import ChartCommand

    dataset = _dataset()
    original = ChartCommand(dataset=dataset, kind="scatter", variables=["age", "income"])
    restored = parse_syntax(build_syntax([original]), dataset)
    assert isinstance(restored[0], ChartCommand)
    assert restored[0].kind == "scatter"
    assert restored[0].variables == ["age", "income"]


def test_several_commands_roundtrip():
    dataset = _dataset()
    commands = [
        FrequenciesCommand(dataset=dataset, variables=["gender"]),
        DescriptivesCommand(dataset=dataset, variables=["age", "income"]),
        CorrelationsCommand(dataset=dataset, variables=["age", "income"]),
    ]
    restored = parse_syntax(build_syntax(commands), dataset)
    assert len(restored) == 3
    assert [type(command).__name__ for command in restored] == [
        "FrequenciesCommand",
        "DescriptivesCommand",
        "CorrelationsCommand",
    ]


# ------------------------------------------------------------ файлы


def test_save_and_load_syntax(tmp_path):
    dataset = _dataset()
    commands = [
        FrequenciesCommand(dataset=dataset, variables=["gender"]),
        DescriptivesCommand(dataset=dataset, variables=["age"]),
    ]
    path = save_syntax(commands, tmp_path / "анализ.sps", title="Проверка гипотез")
    assert path.exists()

    loaded = load_syntax(path, dataset)
    assert len(loaded) == 2
    assert isinstance(loaded[0], FrequenciesCommand)


def test_saved_file_has_readable_text(tmp_path):
    """Файл должен читаться глазами: ради этого синтаксис и сохраняют."""
    dataset = _dataset()
    path = save_syntax(
        [FrequenciesCommand(dataset=dataset, variables=["gender"])],
        tmp_path / "test.sps",
    )
    text = path.read_text(encoding="utf-8")
    assert "FREQUENCIES" in text
    assert "gender" in text


def test_loaded_syntax_can_be_executed(tmp_path):
    dataset = _dataset()
    path = save_syntax(
        [DescriptivesCommand(dataset=dataset, variables=["age", "income"])],
        tmp_path / "run.sps",
    )
    commands = load_syntax(path, dataset)
    results = [command.execute() for command in commands]
    assert results
    assert results[0].tables


def test_execute_syntax_runs_all_commands():
    dataset = _dataset()
    text = build_syntax(
        [
            FrequenciesCommand(dataset=dataset, variables=["gender"]),
            DescriptivesCommand(dataset=dataset, variables=["age"]),
        ]
    )
    results = execute_syntax(text, dataset)
    assert len(results) == 2
    assert all(result.tables for result in results)


# --------------------------------------------------------------- ошибки


def test_unknown_command_is_reported_with_line():
    dataset = _dataset()
    text = "* комментарий\nFREQUENCIES VARIABLES=gender.\nUNKNOWNPROC x=1."
    with pytest.raises(SyntaxError_) as error:
        parse_syntax(text, dataset)
    assert error.value.line == 3
    assert "не поддерживается" in str(error.value)


def test_missing_variable_is_reported_with_line():
    dataset = _dataset()
    text = "FREQUENCIES VARIABLES=нетакой_переменной."
    with pytest.raises(SyntaxError_) as error:
        parse_syntax(text, dataset)
    assert error.value.line == 1
    assert "не найдена" in str(error.value).lower() or "не найдена" in str(error.value)


def test_syntax_error_is_command_error():
    """Ошибку синтаксиса можно ловить общим типом: вызывающему коду это удобно."""
    dataset = _dataset()
    with pytest.raises(CommandError):
        parse_syntax("НЕТТАКОЙ x=1.", dataset)


def test_empty_syntax_gives_no_commands():
    dataset = _dataset()
    assert parse_syntax("", dataset) == []
    assert parse_syntax("* только комментарий.", dataset) == []


def test_build_syntax_without_commands_is_empty():
    assert build_syntax([]) == ""


def test_build_syntax_adds_final_period():
    """Команды в файле разделяются точкой: без неё следующая не прочитается."""
    dataset = _dataset()
    text = build_syntax([FrequenciesCommand(dataset=dataset, variables=["gender"])])
    assert text.strip().endswith(".")


def test_title_is_written_as_comment():
    dataset = _dataset()
    text = build_syntax(
        [FrequenciesCommand(dataset=dataset, variables=["gender"])], title="Мой анализ"
    )
    assert "Мой анализ" in text


def test_roundtrip_keeps_compute_expression(tmp_path):
    """Выражение вычисляемой переменной должно пережить сохранение дословно."""
    dataset = _dataset()
    original = ComputeCommand(
        dataset=dataset, target="ratio", expression="(age + income) / 2"
    )
    path = save_syntax([original], tmp_path / "compute.sps")
    restored = load_syntax(path, dataset)
    assert restored[0].expression == "(age + income) / 2"
