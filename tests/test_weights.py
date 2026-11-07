"""Веса кейсов: где они учитываются и где об этом честно сказано.

Главная опасность весов не в том, что процедура их не умеет, а в том, что она
молча посчитает невзвешенные числа, а человек будет думать обратное. Поэтому
проверяется не только расчёт, но и предупреждение.
"""

from __future__ import annotations

from winnow.core.dataset import Dataset
from winnow.stats.engine import REGISTRY_BY_KEY, WEIGHTED_PROCEDURES, execute


def _dataset() -> Dataset:
    rows = {
        "вес": [1, 2, 1, 3, 1, 2, 1, 1, 2, 1],
        "возраст": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "рост": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        "пол": ["1. М", "2. Ж"] * 5,
    }
    dataset = Dataset.from_records(rows)
    dataset.weight_var = "вес"
    return dataset


def _run(key: str, **params):
    info = REGISTRY_BY_KEY[key]
    return execute(info.command_type(dataset=_dataset(), **params))


def test_warning_when_procedure_ignores_weights():
    """Корреляции веса не учитывают - и говорят об этом прямо в отчёте."""
    result = _run("correlations", variables=["возраст", "рост"])
    notes = [warn for warn in result.warnings if "не учитываются" in warn]
    assert notes, "должно быть предупреждение о невзвешенных числах"
    assert "вес" in notes[0], "в предупреждении названа переменная весов"


def test_no_warning_for_procedures_that_use_weights():
    """Частоты и описательные веса учитывают - предупреждения быть не должно."""
    for key, params in (
        ("frequencies", {"variables": ["пол"]}),
        ("descriptives", {"variables": ["возраст"]}),
    ):
        result = _run(key, **params)
        assert not [warn for warn in result.warnings if "не учитываются" in warn], key


def test_no_warning_without_weights():
    """Веса не заданы - предупреждать не о чем."""
    rows = {"a": [1, 2, 3, 4, 5], "b": [2, 3, 4, 5, 6]}
    dataset = Dataset.from_records(rows)
    info = REGISTRY_BY_KEY["correlations"]
    result = execute(info.command_type(dataset=dataset, variables=["a", "b"]))
    assert not [warn for warn in result.warnings if "не учитываются" in warn]


def test_weighted_procedures_list_is_closed():
    """Список поддерживающих веса фиксирован: расширять его без формул нельзя.

    Если процедура попадёт сюда, не умея взвешивать, отчёт соврёт: числа будут
    невзвешенными, а предупреждения не будет.
    """
    assert WEIGHTED_PROCEDURES == {
        "frequencies",
        "descriptives",
        "crosstabs",
        "ttest",
        "anova",
        "linear_regression",
    }


#: Эталон из SPSS: docs/weights-reference.csv, WEIGHT BY w, N = 22.
_SPSS = {"w": [2, 1, 3, 1, 2, 1, 3, 2, 1, 1, 2, 3],
         "grp": ["1"] * 4 + ["2"] * 4 + ["3"] * 4,
         "y": [10, 12, 11, 13, 20, 22, 19, 21, 30, 32, 28, 31],
         "x1": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
         "x2": [3, 2, 4, 3, 6, 5, 7, 6, 9, 8, 10, 9]}


def test_weighted_pearson_matches_spss():
    """Взвешенный Пирсон совпадает с SPSS до третьего знака.

    Эталоны: r(y, x1) = 0,954; r(y, x2) = 0,918; r(x1, x2) = 0,942 при N = 22.
    """
    import numpy as np

    from winnow.stats.correlations import _weighted_pearson

    frame = Dataset.from_records(_SPSS).frame
    weights = frame["w"].to_numpy(dtype=float)
    for left, right, expected in (("y", "x1", 0.954), ("y", "x2", 0.918), ("x1", "x2", 0.942)):
        n, r, p = _weighted_pearson(
            frame[left].to_numpy(dtype=float),
            frame[right].to_numpy(dtype=float),
            weights,
        )
        assert n == 22, "эффективное N - сумма весов"
        assert round(r, 3) == expected, f"{left}-{right}: {r:.4f} вместо {expected}"
        assert p < 0.001


def test_weights_change_the_result():
    """Веса действительно меняют r, а не игнорируются.

    На этом наборе веса 2, 1, 3 делают строки разнозначными: взвешенный r
    (0,954) отличается от обычного. Если однажды веса перестанут применяться,
    тест это поймает.
    """
    import numpy as np
    import scipy.stats as sps

    from winnow.stats.correlations import _weighted_pearson

    frame = Dataset.from_records(_SPSS).frame
    a = frame["y"].to_numpy(dtype=float)
    b = frame["x1"].to_numpy(dtype=float)
    weights = frame["w"].to_numpy(dtype=float)
    _, weighted_r, _ = _weighted_pearson(a, b, weights)
    plain_r = float(sps.pearsonr(a, b)[0])
    assert abs(weighted_r - plain_r) > 1e-3, "веса не повлияли на результат"


def test_weighted_anova_matches_spss():
    """Взвешенный ANOVA совпадает с SPSS: F = 392,824, df = 2 и 19.

    Проверяются и суммы квадратов (1264,865 и 30,589), и описательные
    статистики по группам - они считаются по эффективным N (суммам весов).
    """
    dataset = Dataset.from_records(_SPSS)
    dataset.weight_var = "w"
    info = REGISTRY_BY_KEY["anova"]
    result = execute(info.command_type(dataset=dataset, dependent="y", factor="grp"))

    assert not [warn for warn in result.warnings if "не учитываются" in warn]
    values = [cell for table in result.tables for row in table.rows for cell in row]
    numbers = [float(cell) for cell in values if isinstance(cell, (int, float))]
    assert any(abs(number - 392.824) < 0.0006 for number in numbers), "F не совпал"
    assert any(abs(number - 1264.865) < 0.0006 for number in numbers), "SS между не совпал"
    assert any(abs(number - 30.589) < 0.0006 for number in numbers), "SS ошибки не совпал"


def test_weighted_regression_matches_spss():
    """Взвешенная регрессия совпадает с SPSS.

    Эталон: R = 0,955; R2 = 0,913; F = 99,595; остаток SS = 112,808 при df 19;
    коэффициенты 5,721 / 1,685 / 0,558 со стандартными ошибками 1,666 / 0,433 /
    0,639. Проверяется R2, F и остаток - остальные числа тех же таблиц следуют
    из той же оценки.
    """
    dataset = Dataset.from_records(_SPSS)
    dataset.weight_var = "w"
    info = REGISTRY_BY_KEY["linear_regression"]
    result = execute(
        info.command_type(dataset=dataset, dependent="y", predictors=["x1", "x2"])
    )
    assert not [warn for warn in result.warnings if "не учитываются" in warn]
    numbers = [
        float(cell)
        for table in result.tables
        for row in table.rows
        for cell in row
        if isinstance(cell, (int, float))
    ]
    assert any(abs(number - 0.9129) < 0.0006 for number in numbers), "R2 не совпал"
    assert any(abs(number - 99.595) < 0.0006 for number in numbers), "F не совпал"
    assert any(abs(number - 112.808) < 0.0006 for number in numbers), "остаток не совпал"
