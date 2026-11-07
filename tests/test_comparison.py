"""Эталонные тесты сравнения групп: ANOVA и непараметрические критерии.

Ключевые числа сверяются со scipy: F и значимость ANOVA, статистики Манна-Уитни,
Краскела-Уоллиса, Уилкоксона и Фридмана. Это тот случай, когда «примерно верно»
не считается: на защите могут проверить числа другой программой.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats as sps

from winnow.core.dataset import Dataset
from winnow.stats.anova import (
    GroupData,
    anova_table,
    post_hoc_comparisons,
    split_groups,
    welch_anova,
)
from winnow.stats.command import AnovaCommand, CommandError, NonparametricCommand
from winnow.stats.common import bonferroni_adjust, holm_adjust, rank_biserial_from_u
from winnow.stats.nonparametric import (
    friedman_test,
    kruskal_wallis,
    mann_whitney,
    run as run_nonparametric,
    wilcoxon_test,
)

# Три группы с разными средними - на них проверяется и ANOVA, и непараметрика.
GROUP_A = [12.0, 14.0, 15.0, 13.0, 16.0, 14.5, 15.5, 13.5]
GROUP_B = [18.0, 19.5, 17.0, 20.0, 18.5, 21.0, 17.5, 19.0]
GROUP_C = [25.0, 24.0, 26.5, 23.5, 27.0, 25.5, 24.5, 26.0]


def _three_group_dataset() -> Dataset:
    factor: list[int] = []
    values: list[float] = []
    for index, group in enumerate((GROUP_A, GROUP_B, GROUP_C), start=1):
        factor.extend([index] * len(group))
        values.extend(group)
    return Dataset.from_records({"score": values, "group": factor})


def _groups() -> list[GroupData]:
    return [
        GroupData(label="A", values=np.array(GROUP_A)),
        GroupData(label="B", values=np.array(GROUP_B)),
        GroupData(label="C", values=np.array(GROUP_C)),
    ]


# ------------------------------------------------------------------- ANOVA


def test_anova_matches_scipy_reference():
    """F и значимость должны совпадать со scipy. ANOVA."""
    reference = sps.f_oneway(GROUP_A, GROUP_B, GROUP_C)
    table = anova_table(_groups())

    assert table["f"] == pytest.approx(reference.statistic, abs=1e-9)
    assert table["p"] == pytest.approx(reference.pvalue, abs=1e-12)
    assert table["df_between"] == pytest.approx(2.0)
    assert table["df_within"] == pytest.approx(21.0)


def test_anova_sums_of_squares_add_up():
    """Суммы квадратов между и внутри групп должны давать общую - иначе ошибка в формулах."""
    table = anova_table(_groups())
    assert table["ss_between"] + table["ss_within"] == pytest.approx(table["ss_total"], abs=1e-9)
    assert table["ms_between"] == pytest.approx(table["ss_between"] / table["df_between"])
    assert table["ms_within"] == pytest.approx(table["ss_within"] / table["df_within"])
    assert table["f"] == pytest.approx(table["ms_between"] / table["ms_within"])


def test_anova_eta_squared_matches_definition():
    table = anova_table(_groups())
    eta = table["ss_between"] / table["ss_total"]
    assert 0.0 < eta < 1.0
    # Группы сильно различаются, поэтому эффект должен быть большим.
    assert eta > 0.8


def test_welch_anova_matches_scipy():
    reference = sps.f_oneway(GROUP_A, GROUP_B, GROUP_C, equal_var=False)
    values = welch_anova(_groups())
    assert values["f"] == pytest.approx(reference.statistic, abs=1e-9)
    assert values["p"] == pytest.approx(reference.pvalue, abs=1e-9)
    assert values["df1"] == pytest.approx(2.0)


def test_welch_anova_with_equal_variances_approaches_usual():
    """При равных дисперсиях Уэлч близок к обычному F - проверка знака и порядка."""
    rng = np.random.default_rng(5)
    groups = [GroupData(label=str(i), values=rng.normal(10, 2, 40) + i) for i in range(3)]
    usual = anova_table(groups)
    welch = welch_anova(groups)
    assert welch["f"] == pytest.approx(usual["f"], rel=0.5)
    assert welch["df2"] > 50


def test_tukey_post_hoc_finds_separated_groups():
    table = anova_table(_groups())
    rows = post_hoc_comparisons(_groups(), table, "tukey", 0.95)
    assert len(rows) == 3  # три пары из трёх групп
    # Все пары в этом примере различаются значимо.
    for row in rows:
        assert row["p"] < 0.001
        assert row["difference"] != 0
        assert row["low"] < row["difference"] < row["high"]


def test_tukey_q_matches_manual_formula():
    """Проверка q через ручную формулу: q = |разность| / sqrt(MS_внутри * (1/n1 + 1/n2))."""
    groups = _groups()
    table = anova_table(groups)
    rows = post_hoc_comparisons(groups, table, "tukey", 0.95)
    first = rows[0]
    manual_se = math.sqrt(table["ms_within"] * (1 / 8 + 1 / 8))
    assert first["se"] == pytest.approx(manual_se, abs=1e-9)
    # Тьюки считает значимость по стьюдентизированному размаху.
    from winnow.stats.common import tukey_p_value

    q_value = abs(first["difference"]) / manual_se
    assert first["p"] == pytest.approx(
        tukey_p_value(q_value, len(groups), table["df_within"]), abs=1e-12
    )


def test_bonferroni_and_holm_are_more_conservative_than_raw():
    """Поправки должны увеличивать значимость относительно нескорректированной.

    Важно: у Тьюки и у Бонферрони значимость считается по-разному (стьюдентизированный
    размах против парного t-критерия), поэтому сравнивать их напрямую нельзя -
    сравниваем каждую с её же нескорректированным значением.
    """
    groups = _groups()
    table = anova_table(groups)

    for method in ("bonferroni", "holm"):
        rows = post_hoc_comparisons(groups, table, method, 0.95)
        assert len(rows) == 3
        # В этом примере группы сильно различаются, поэтому исходная значимость
        # мала, а поправка её только увеличивает (не уменьшает).
        for row in rows:
            assert row["p"] >= row["p_raw"] - 1e-15
            assert row["p"] <= 1.0


def test_bonferroni_multiplies_by_number_of_comparisons():
    """Поправка Бонферрони умножает значимость на число парных сравнений."""
    groups = _groups()
    table = anova_table(groups)
    rows = post_hoc_comparisons(groups, table, "bonferroni", 0.95)
    count = len(rows)
    for row in rows:
        expected = min(1.0, row["p_raw"] * count)
        assert row["p"] == pytest.approx(expected, abs=1e-12)


def test_anova_command_runs_end_to_end():
    dataset = _three_group_dataset()
    result = AnovaCommand(
        dataset=dataset, dependent=["score"], factor="group", post_hoc="tukey"
    ).execute()
    titles = [table.title for table in result.tables]
    assert any("Описательные" in title for title in titles)
    assert any("ANOVA" in title for title in titles)
    assert any("Апостериорные" in title for title in titles)
    assert any("подмножества" in title for title in titles)
    assert result.syntax.startswith("ONEWAY")


def test_anova_needs_factor_and_dependent():
    dataset = _three_group_dataset()
    with pytest.raises(CommandError):
        AnovaCommand(dataset=dataset, dependent=["score"], factor=None).execute()
    with pytest.raises(CommandError):
        AnovaCommand(dataset=dataset, dependent=[], factor="group").execute()


def test_anova_factor_cannot_be_dependent():
    dataset = _three_group_dataset()
    with pytest.raises(CommandError):
        AnovaCommand(dataset=dataset, dependent=["score", "group"], factor="group").execute()


def test_anova_warns_when_group_is_single():
    dataset = Dataset.from_records({"score": [1.0, 2.0, 3.0], "group": [1, 1, 1]})
    result = AnovaCommand(dataset=dataset, dependent=["score"], factor="group").execute()
    assert any("меньше двух" in warning for warning in result.warnings)


def test_split_groups_uses_value_labels():
    dataset = _three_group_dataset()
    dataset.var("group").value_labels = {1: "Контроль", 2: "Терапия А", 3: "Терапия Б"}
    groups = split_groups(dataset, "score", "group")
    assert groups[0].label == "1 (Контроль)"
    assert groups[1].label == "2 (Терапия А)"
    assert groups[0].n == 8


# ---------------------------------------------------- непараметрические


def test_mann_whitney_matches_scipy():
    first = np.array(GROUP_A)
    second = np.array(GROUP_B)
    from winnow.stats.nonparametric import RankGroup

    groups = [RankGroup(label="A", values=first), RankGroup(label="B", values=second)]
    values = mann_whitney(groups)
    reference = sps.mannwhitneyu(first, second, alternative="two-sided")

    assert values["u"] == pytest.approx(reference.statistic, abs=1e-9)
    assert values["p"] == pytest.approx(reference.pvalue, abs=1e-12)
    assert values["rank_biserial"] == pytest.approx(
        rank_biserial_from_u(values["u"], first.size, second.size), abs=1e-12
    )


def test_kruskal_wallis_matches_scipy():
    from winnow.stats.nonparametric import RankGroup

    groups = [
        RankGroup(label=name, values=np.array(values))
        for name, values in (("A", GROUP_A), ("B", GROUP_B), ("C", GROUP_C))
    ]
    values = kruskal_wallis(groups)
    reference = sps.kruskal(GROUP_A, GROUP_B, GROUP_C)

    assert values["h"] == pytest.approx(reference.statistic, abs=1e-9)
    assert values["p"] == pytest.approx(reference.pvalue, abs=1e-12)
    assert values["df"] == pytest.approx(2.0)
    # Размер эффекта определён как H / (N - k): проверяем именно это соотношение.
    n_total = len(GROUP_A) + len(GROUP_B) + len(GROUP_C)
    assert values["epsilon_squared"] == pytest.approx(values["h"] / (n_total - 3), abs=1e-12)
    assert 0.0 <= values["epsilon_squared"] <= 1.0


def test_wilcoxon_matches_scipy():
    before = np.array([10.0, 12.0, 9.0, 15.0, 11.0, 13.0, 8.0, 14.0])
    after = np.array([12.0, 13.5, 10.0, 16.0, 12.5, 15.0, 9.5, 15.5])
    values = wilcoxon_test(before, after)
    reference = sps.wilcoxon(before, after, zero_method="wilcox", alternative="two-sided")

    assert values["t"] == pytest.approx(reference.statistic, abs=1e-9)
    assert values["p"] == pytest.approx(reference.pvalue, abs=1e-12)


def test_wilcoxon_reports_identical_samples_as_not_applicable():
    values = np.array([1.0, 2.0, 3.0, 4.0])
    result = wilcoxon_test(values, values.copy())
    assert result["applicable"] is False
    assert "нулю" in result["reason"]


def test_friedman_matches_scipy():
    rng = np.random.default_rng(17)
    base = rng.normal(10, 2, 25)
    first = base + rng.normal(0, 0.5, 25)
    second = base + 1.5 + rng.normal(0, 0.5, 25)
    third = base + 3.0 + rng.normal(0, 0.5, 25)

    values = friedman_test([first, second, third])
    reference = sps.friedmanchisquare(first, second, third)
    assert values["chi2"] == pytest.approx(reference.statistic, abs=1e-9)
    assert values["p"] == pytest.approx(reference.pvalue, abs=1e-12)
    assert values["df"] == pytest.approx(2.0)


def test_friedman_needs_three_related_variables():
    values = friedman_test([np.array([1.0, 2.0]), np.array([2.0, 3.0])])
    assert values["applicable"] is False


def test_nonparametric_command_auto_picks_kruskal_for_three_groups():
    dataset = _three_group_dataset()
    result = NonparametricCommand(
        dataset=dataset, kind="independent", test_vars=["score"], group_var="group"
    ).execute()
    titles = " ".join(table.title for table in result.tables)
    assert "Краскела-Уоллиса" in titles
    assert any("Ранги" in table.title for table in result.tables)
    assert any("Парные сравнения" in table.title for table in result.tables)


def test_nonparametric_command_auto_picks_mann_whitney_for_two_groups():
    dataset = Dataset.from_records(
        {"score": GROUP_A + GROUP_B, "group": [1] * len(GROUP_A) + [2] * len(GROUP_B)}
    )
    result = NonparametricCommand(
        dataset=dataset, kind="independent", test_vars=["score"], group_var="group"
    ).execute()
    titles = " ".join(table.title for table in result.tables)
    assert "Манна-Уитни" in titles
    assert "Краскела" not in titles


def test_nonparametric_command_related_wilcoxon():
    dataset = Dataset.from_records(
        {
            "before": [10.0, 12.0, 9.0, 15.0, 11.0, 13.0, 8.0],
            "after": [12.0, 13.5, 10.0, 16.0, 12.5, 15.0, 9.5],
        }
    )
    result = NonparametricCommand(
        dataset=dataset, kind="related", test_vars=["before"], pair_with=["after"]
    ).execute()
    titles = " ".join(table.title for table in result.tables)
    assert "Уилкоксона" in titles


def test_nonparametric_rejects_wrong_method_for_kind():
    dataset = _three_group_dataset()
    with pytest.raises(CommandError):
        NonparametricCommand(
            dataset=dataset,
            kind="independent",
            test_vars=["score"],
            group_var="group",
            method="wilcoxon",
        ).execute()
    with pytest.raises(CommandError):
        NonparametricCommand(
            dataset=dataset,
            kind="related",
            test_vars=["score"],
            pair_with=["score"],
            method="kruskal_wallis",
        ).execute()


def test_pairwise_mann_whitney_adjusts_significance():
    from winnow.stats.nonparametric import RankGroup, pairwise_mann_whitney

    groups = [
        RankGroup(label=name, values=np.array(values))
        for name, values in (("A", GROUP_A), ("B", GROUP_B), ("C", GROUP_C))
    ]
    rows = pairwise_mann_whitney(groups, "bonferroni")
    assert len(rows) == 3
    for row in rows:
        assert row["p"] >= row["p_raw"] - 1e-12


def test_nonparametric_run_is_callable_directly():
    """Регистрация в движке не должна ломать прямой вызов процедуры."""
    dataset = _three_group_dataset()
    command = NonparametricCommand(
        dataset=dataset, kind="independent", test_vars=["score"], group_var="group"
    )
    result = run_nonparametric(command)
    assert result.tables


# ------------------------------------------------------------- поправки


def test_bonferroni_never_exceeds_one():
    adjusted = bonferroni_adjust([0.04, 0.03, 0.02])
    assert all(value <= 1.0 for value in adjusted)
    assert adjusted == pytest.approx([0.12, 0.09, 0.06])


def test_holm_is_less_conservative_than_bonferroni():
    raw = [0.001, 0.008, 0.039, 0.041]
    bonferroni = bonferroni_adjust(raw)
    holm = holm_adjust(raw)
    assert all(h <= b + 1e-12 for h, b in zip(holm, bonferroni))
    assert holm[0] == pytest.approx(raw[0] * 4)


def test_rank_biserial_bounds():
    assert rank_biserial_from_u(0.0, 5, 5) == pytest.approx(1.0)
    assert rank_biserial_from_u(25.0, 5, 5) == pytest.approx(-1.0)
    assert rank_biserial_from_u(12.5, 5, 5) == pytest.approx(0.0)
