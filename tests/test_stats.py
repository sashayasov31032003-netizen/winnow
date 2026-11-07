"""Эталонные тесты статистических процедур.

Смысл этого файла: числа должны совпадать с известными правильными ответами.
Любое расхождение со SPSS в третьем знаке вызывает письмо в поддержку, поэтому
ключевые значения здесь посчитаны независимо (формулой или другим пакетом) и
зафиксированы как эталон.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats as sps

from winnow.core.dataset import Dataset
from winnow.core.variable import MissingSpec
from winnow.stats.command import (
    CommandError,
    CorrelationsCommand,
    CrosstabsCommand,
    DescriptivesCommand,
    FrequenciesCommand,
    TTestCommand,
)
from winnow.stats.crosstabs import compute_independence
from winnow.stats.ttest import levene_test


def _as_dict(table, row_index: int = 0) -> dict[str, object]:
    """Превращает строку таблицы в словарь по подписям колонок."""
    header = [c.label for c in table.columns]
    return dict(zip(header, table.rows[row_index]))


# ---------------------------------------------------------------- описательные


def test_descriptives_match_numpy_reference():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    dataset = Dataset.from_records({"x": values})
    result = DescriptivesCommand(
        dataset=dataset,
        variables=["x"],
        statistics=["n", "mean", "median", "std", "variance", "min", "max", "range"],
        confidence=0.0,
    ).execute()
    cell = _as_dict(result.tables[0])

    assert cell["N"] == 8
    assert cell["Среднее"] == pytest.approx(np.mean(values), abs=1e-9)
    assert cell["Медиана"] == pytest.approx(np.median(values), abs=1e-9)
    # Знаменатель (N-1) - так же, как в SPSS.
    assert cell["Стд. отклонение"] == pytest.approx(np.std(values, ddof=1), abs=1e-9)
    assert cell["Дисперсия"] == pytest.approx(np.var(values, ddof=1), abs=1e-9)
    assert cell["Размах"] == pytest.approx(7.0)


def test_descriptives_skewness_uses_sample_correction():
    """Асимметрия должна совпадать со scipy при bias=False (как в SPSS)."""
    rng = np.random.default_rng(7)
    values = rng.normal(10, 3, 50)
    dataset = Dataset.from_records({"x": values})
    result = DescriptivesCommand(
        dataset=dataset, variables=["x"], statistics=["skewness", "kurtosis"], confidence=0.0
    ).execute()
    cell = _as_dict(result.tables[0])

    assert cell["Асимметрия"] == pytest.approx(sps.skew(values, bias=False), abs=1e-9)
    assert cell["Эксцесс"] == pytest.approx(sps.kurtosis(values, bias=False), abs=1e-9)


def test_descriptives_rejects_non_numeric_variable():
    dataset = Dataset.from_records({"name": ["a", "b", "c"]})
    with pytest.raises(CommandError):
        DescriptivesCommand(dataset=dataset, variables=["name"]).execute()


def test_descriptives_requires_at_least_one_variable():
    dataset = Dataset.from_records({"x": [1.0, 2.0]})
    with pytest.raises(CommandError):
        DescriptivesCommand(dataset=dataset, variables=[]).execute()


def test_confidence_interval_brackets_the_mean():
    values = [10.0, 12.0, 14.0, 16.0, 18.0]
    dataset = Dataset.from_records({"x": values})
    result = DescriptivesCommand(
        dataset=dataset, variables=["x"], statistics=["mean"], confidence=0.95
    ).execute()

    # Таблица ищется по названию, а не по номеру: рядом со средними процедура
    # добавляет распределения ответов, и порядок таблиц от этого меняется.
    ci_table = next(
        table
        for table in result.tables
        if "Доверительные интервалы" in table.title
    )
    _name, mean, low, high, _std = ci_table.rows[0]
    assert low < mean < high

    sem = np.std(values, ddof=1) / math.sqrt(len(values))
    critical = sps.t.ppf(0.975, df=len(values) - 1)
    assert low == pytest.approx(np.mean(values) - critical * sem, abs=1e-9)
    assert high == pytest.approx(np.mean(values) + critical * sem, abs=1e-9)


def test_missing_code_is_excluded_from_descriptives():
    dataset = Dataset.from_records({"x": [1.0, 2.0, 3.0, -99.0]})
    dataset.var("x").missing = MissingSpec(discrete={-99.0})
    result = DescriptivesCommand(
        dataset=dataset, variables=["x"], statistics=["n", "missing", "mean"], confidence=0.0
    ).execute()
    cell = _as_dict(result.tables[0])

    assert cell["N"] == 3
    assert cell["Пропущено"] == 1
    assert cell["Среднее"] == pytest.approx(2.0)


# ---------------------------------------------------------------- хи-квадрат


def test_chi_square_matches_hand_computed_reference():
    """Таблица 2x2 [[10, 20], [30, 40]]: эталон посчитан вручную по формуле."""
    table = np.array([[10.0, 20.0], [30.0, 40.0]])
    values = compute_independence(table, chi_square_ok=True)

    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / 100.0
    chi2_reference = float(np.sum((table - expected) ** 2 / expected))

    assert values["n"] == pytest.approx(100.0)
    assert values["df"] == 1
    assert values["value"] == pytest.approx(chi2_reference, abs=1e-9)
    assert values["value"] == pytest.approx(0.79365, abs=1e-4)
    assert values["p"] == pytest.approx(sps.chi2.sf(chi2_reference, 1), abs=1e-12)
    assert values["cramers_v"] == pytest.approx(math.sqrt(chi2_reference / 100.0), abs=1e-9)
    assert values["min_expected"] == pytest.approx(12.0)


def test_chi_square_degenerate_table_returns_nan():
    values = compute_independence(np.array([[5.0], [7.0]]), chi_square_ok=True)
    assert math.isnan(values["value"])


def test_crosstabs_end_to_end_counts_and_percent():
    dataset = Dataset.from_records(
        {
            "gender": [1] * 10 + [2] * 5,
            "choice": [0] * 10 + [1] * 5,
        }
    )
    result = CrosstabsCommand(
        dataset=dataset, row_vars=["gender"], col_vars=["choice"], chi_square=True, row_percent=True
    ).execute()

    crosstab = next(t for t in result.tables if "сопряжённости" in t.title)
    first_row = crosstab.rows[0]
    assert first_row[1].startswith("10")
    assert first_row[2].startswith("0")
    # Процент по строке печатается один раз и ровно с одним знаком "%".
    assert "100.0%" in first_row[1]
    assert "%%" not in first_row[1]

    chi_table = next(t for t in result.tables if "хи-квадрат" in t.title.lower())
    assert chi_table.rows[0][0] == "Хи-квадрат Пирсона"
    assert chi_table.rows[0][1] > 0
    assert chi_table.rows[0][2] == 1


def test_crosstabs_warns_when_expected_counts_are_small():
    dataset = Dataset.from_records({"a": [1, 1, 1, 1, 2, 2], "b": [1, 1, 2, 2, 1, 1]})
    result = CrosstabsCommand(
        dataset=dataset, row_vars=["a"], col_vars=["b"], chi_square=True
    ).execute()
    chi_table = next(t for t in result.tables if "хи-квадрат" in t.title.lower())
    assert any("ожидаемая частота" in note.lower() for note in chi_table.footnotes)


def test_crosstabs_requires_both_axes():
    dataset = Dataset.from_records({"a": [1, 2], "b": [1, 2]})
    with pytest.raises(CommandError):
        CrosstabsCommand(dataset=dataset, row_vars=["a"], col_vars=[]).execute()


def test_crosstabs_uses_value_labels_in_headers():
    dataset = Dataset.from_records({"gender": [1, 1, 2, 2], "yes": [0, 1, 0, 1]})
    dataset.var("gender").value_labels = {1: "мужской", 2: "женский"}
    result = CrosstabsCommand(dataset=dataset, row_vars=["gender"], col_vars=["yes"]).execute()
    crosstab = next(t for t in result.tables if "сопряжённости" in t.title)
    assert crosstab.rows[0][0] == "1 (мужской)"


# ---------------------------------------------------------------- t-критерий


def test_levene_matches_scipy_median_centered():
    rng = np.random.default_rng(11)
    first = rng.normal(0, 1, 30)
    second = rng.normal(0, 3, 30)

    f_value, df1, p_value = levene_test([first, second])
    reference = sps.levene(first, second, center="median")

    assert f_value == pytest.approx(reference.statistic, abs=1e-9)
    assert p_value == pytest.approx(reference.pvalue, abs=1e-12)
    # У scipy новые версии не отдают dfbn/dfwn, поэтому проверяем по формуле.
    assert df1 == pytest.approx(len([first, second]) - 1)


def test_independent_t_test_matches_scipy_welch():
    rng = np.random.default_rng(3)
    a = rng.normal(10, 2, 40)
    b = rng.normal(11, 3, 45)
    dataset = Dataset.from_records(
        {"score": np.concatenate([a, b]).tolist(), "grp": [1] * 40 + [2] * 45}
    )
    result = TTestCommand(
        dataset=dataset,
        kind="independent",
        test_vars=["score"],
        group_var="grp",
        group_values=[1, 2],
        effect_size=True,
    ).execute()

    test_table = next(t for t in result.tables if t.title.startswith("Критерий для независимых"))
    welch_row = test_table.rows[1]
    reference = sps.ttest_ind(a, b, equal_var=False)

    assert welch_row[3] == pytest.approx(reference.statistic, abs=1e-9)
    assert welch_row[4] == pytest.approx(reference.df, abs=1e-9)
    assert welch_row[5] == pytest.approx(reference.pvalue, abs=1e-12)
    assert welch_row[6] == pytest.approx(float(np.mean(a) - np.mean(b)), abs=1e-9)

    effect_table = next(t for t in result.tables if t.title == "Размеры эффекта")
    d_value = effect_table.rows[0][1]
    pooled = math.sqrt(
        ((len(a) - 1) * np.var(a, ddof=1) + (len(b) - 1) * np.var(b, ddof=1))
        / (len(a) + len(b) - 2)
    )
    assert d_value == pytest.approx((np.mean(a) - np.mean(b)) / pooled, abs=1e-9)


def test_paired_t_test_matches_scipy():
    """Пары должны различаться: если разность всюду ноль, критерий не определен."""
    before = np.array([10.0, 12.0, 9.0, 15.0, 11.0, 13.0, 8.0])
    after = np.array([11.5, 13.0, 8.0, 17.5, 12.0, 12.0, 10.5])
    dataset = Dataset.from_records({"before": before.tolist(), "after": after.tolist()})

    result = TTestCommand(
        dataset=dataset, kind="paired", test_vars=["before"], pair_with=["after"]
    ).execute()

    # Именно таблица критерия, а не таблица описательных статистик: у них похожие
    # названия, и поиск по подстроке "парных выборок" даёт не ту таблицу.
    diff_table = next(t for t in result.tables if t.title.startswith("Критерий для парных"))
    row = diff_table.rows[0]
    reference = sps.ttest_rel(before, after)

    assert row[6] == pytest.approx(reference.statistic, abs=1e-9)
    assert row[8] == pytest.approx(reference.pvalue, abs=1e-12)
    assert row[1] == pytest.approx(float(np.mean(before - after)), abs=1e-9)


def test_one_sample_t_test_matches_scipy():
    values = np.array([5.1, 4.8, 5.5, 5.0, 4.9, 5.2, 5.3])
    dataset = Dataset.from_records({"x": values.tolist()})
    result = TTestCommand(
        dataset=dataset, kind="one_sample", test_vars=["x"], test_value=5.0
    ).execute()

    row = result.tables[0].rows[0]
    reference = sps.ttest_1samp(values, 5.0)
    assert row[7] == pytest.approx(reference.statistic, abs=1e-9)
    assert row[9] == pytest.approx(reference.pvalue, abs=1e-12)


def test_independent_t_test_needs_two_groups():
    dataset = Dataset.from_records({"score": [1.0, 2.0], "grp": [1, 1]})
    with pytest.raises(CommandError):
        TTestCommand(
            dataset=dataset,
            kind="independent",
            test_vars=["score"],
            group_var="grp",
            group_values=[1],
        ).execute()


def test_empty_group_produces_warning_not_crash():
    dataset = Dataset.from_records({"score": [1.0, 2.0, 3.0], "grp": [1, 1, 1]})
    result = TTestCommand(
        dataset=dataset,
        kind="independent",
        test_vars=["score"],
        group_var="grp",
        group_values=[1, 2],
    ).execute()
    assert any("пуста" in warning for warning in result.warnings)


# ---------------------------------------------------------------- частоты


def test_frequencies_percent_from_valid_and_total():
    dataset = Dataset.from_records({"answer": [1, 1, 2, -99]})
    dataset.var("answer").missing = MissingSpec(discrete={-99.0})
    dataset.var("answer").value_labels = {1: "Да", 2: "Нет"}

    result = FrequenciesCommand(
        dataset=dataset, variables=["answer"], show_cumulative=True
    ).execute()

    table = next(t for t in result.tables if t.title.startswith("Частоты"))
    header = [c.label for c in table.columns]
    assert header[0] == "answer"

    row_no = next(row for row in table.rows if str(row[0]).startswith("2"))
    cell = dict(zip(header, row_no))
    assert cell["answer"] == "2 (Нет)"
    assert cell["Частота"] == 1
    assert cell["Процент"] == pytest.approx(25.0)
    assert cell["Валидный процент"] == pytest.approx(100.0 / 3.0)
    assert cell["Накопленный процент"] == pytest.approx(100.0)


def test_frequencies_shows_total_row():
    dataset = Dataset.from_records({"x": [1, 2, 2]})
    result = FrequenciesCommand(dataset=dataset, variables=["x"]).execute()
    table = next(t for t in result.tables if t.title.startswith("Частоты"))
    assert table.rows[-1][0] == "Всего"


def test_frequencies_percent_is_a_number_for_export():
    """Проценты обязаны быть числами: иначе Excel получит текст вместо числа."""
    dataset = Dataset.from_records({"x": [1, 1, 2, 2]})
    result = FrequenciesCommand(dataset=dataset, variables=["x"]).execute()
    table = next(t for t in result.tables if t.title.startswith("Частоты"))
    percent_column = [c.label for c in table.columns].index("Процент")
    for row in table.rows:
        assert isinstance(row[percent_column], (int, float))


# ---------------------------------------------------------------- корреляции


def test_pearson_correlation_matches_scipy_and_is_symmetric():
    rng = np.random.default_rng(21)
    x = rng.normal(0, 1, 60)
    y = 0.6 * x + rng.normal(0, 1, 60)
    dataset = Dataset.from_records({"x": x.tolist(), "y": y.tolist()})

    result = CorrelationsCommand(dataset=dataset, variables=["x", "y"]).execute()
    matrix_table = next(t for t in result.tables if t.title.startswith("Корреляции"))
    reference = sps.pearsonr(x, y)

    assert matrix_table.rows[0][1] == pytest.approx(1.0, abs=1e-12)
    # Значение может быть помечено звёздочкой значимости - сравниваем число.
    assert float(str(matrix_table.rows[0][2]).rstrip("*")) == pytest.approx(
        reference.statistic, abs=1e-3
    )
    assert str(matrix_table.rows[0][2]).rstrip("*") == str(matrix_table.rows[1][1]).rstrip("*")

    p_table = next(t for t in result.tables if t.title.startswith("Значимость"))
    assert p_table.rows[0][3] == pytest.approx(reference.pvalue, abs=1e-12)


def test_spearman_correlation_matches_scipy():
    x = [1, 2, 3, 4, 5, 6, 7, 8]
    y = [2, 1, 4, 3, 6, 5, 8, 7]
    dataset = Dataset.from_records({"x": x, "y": y})
    result = CorrelationsCommand(
        dataset=dataset, variables=["x", "y"], method="spearman"
    ).execute()
    p_table = next(t for t in result.tables if t.title.startswith("Значимость"))
    reference = sps.spearmanr(x, y)
    assert p_table.rows[0][2] == pytest.approx(reference.statistic, abs=1e-9)
    assert p_table.rows[0][3] == pytest.approx(reference.pvalue, abs=1e-12)


def test_correlations_needs_two_variables():
    dataset = Dataset.from_records({"x": [1, 2, 3]})
    with pytest.raises(CommandError):
        CorrelationsCommand(dataset=dataset, variables=["x"]).execute()


def test_correlations_warn_about_constant_variable():
    """С постоянной переменной связь не считается - и об этом надо сказать.

    На реальной базе таких переменных-отметок десятки: программа раньше молча
    показывала таблицу с точками, без предупреждения и без объяснения.
    """
    from winnow.stats.command import CorrelationsCommand

    dataset = Dataset.from_records(
        {"const": [1.0] * 12, "x": [float(index) for index in range(12)]}
    )
    result = CorrelationsCommand(dataset=dataset, variables=["const", "x"]).execute()

    assert result.warnings, "должно быть предупреждение"
    assert "не меняется" in result.warnings[0]
    assert result.findings, "и объяснение простыми словами"
    assert any("не из чего построить" in item.text for item in result.findings)
