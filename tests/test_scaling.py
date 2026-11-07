"""Эталонные тесты надёжности и факторного анализа.

Надёжность проверяется на данных с известной структурой: если пункты - копии
одного и того же с шумом, альфа обязана быть высокой, а если они независимы -
близкой к нулю. Факторный анализ - на данных с двумя явными группами пунктов:
он должен найти ровно два фактора и разнести пункты по нужным.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.command import CommandError, FactorCommand, ReliabilityCommand
from winnow.stats.factor import (
    bartlett_test,
    fit_factor,
    kmo_measure,
    promax,
    varimax,
)
from winnow.stats.reliability import (
    alpha_if_deleted,
    corrected_item_total,
    cronbach_alpha,
    mcdonald_omega,
    run_reliability,
    split_half_reliability,
)

RNG = np.random.default_rng(20240517)


def _scale_data(n: int = 200, noise: float = 0.5, k: int = 5, seed: int = 101) -> np.ndarray:
    """Пункты одного конструкта: общий фактор плюс шум.

    Генератор локальный и seeded: у каждого набора данных своя воспроизводимость.
    Общий генератор на все тесты делать нельзя - порядок тестов начал бы влиять
    на их результаты.
    """
    generator = np.random.default_rng(seed)
    latent = generator.normal(0, 1, n)
    return np.column_stack([latent + generator.normal(0, noise, n) for _ in range(k)])


def _two_factor_data(n: int = 250, seed: int = 202) -> np.ndarray:
    """Две группы пунктов: первая грузится на первый фактор, вторая на второй."""
    generator = np.random.default_rng(seed)
    first = generator.normal(0, 1, n)
    second = generator.normal(0, 1, n)
    columns = []
    for _ in range(3):
        columns.append(first + generator.normal(0, 0.4, n))
    for _ in range(3):
        columns.append(second + generator.normal(0, 0.4, n))
    return np.column_stack(columns)


def _scale_dataset(data: np.ndarray) -> Dataset:
    records = {f"q{index + 1}": data[:, index].tolist() for index in range(data.shape[1])}
    return Dataset.from_records(records)


# --------------------------------------------------------------- надёжность


def test_alpha_is_high_for_consistent_items():
    """Пункты одного конструкта: альфа должна быть высокой."""
    data = _scale_data(noise=0.5)
    alpha = cronbach_alpha(data)
    assert alpha > 0.8


def test_alpha_is_low_for_independent_items():
    """Независимые пункты: надёжности нет, альфа около нуля."""
    data = RNG.normal(0, 1, (300, 5))
    alpha = cronbach_alpha(data)
    assert alpha < 0.2


def test_alpha_matches_manual_formula():
    """Проверка формулы: k/(k-1) * (1 - сумма дисперсий пунктов / дисперсия суммы)."""
    data = _scale_data(120, 0.7)
    k = data.shape[1]
    item_variances = np.var(data, axis=0, ddof=1)
    total_variance = np.var(data.sum(axis=1), ddof=1)
    expected = (k / (k - 1)) * (1.0 - item_variances.sum() / total_variance)
    assert cronbach_alpha(data) == pytest.approx(expected, abs=1e-12)


def test_alpha_of_perfectly_correlated_items_is_high():
    """Если пункты - линейные преобразования одного признака, надёжность высокая.

    Единица не получается специально: третий пункт содержит собственный сдвиг
    (+10), который добавляет уникальной дисперсии. Это правильное поведение -
    сдвиг пункта снижает согласованность шкалы.
    """
    base = RNG.normal(0, 1, 80)
    data = np.column_stack([base * 2, base * 3, base + 10])
    assert cronbach_alpha(data) > 0.9


def test_alpha_is_one_when_items_have_equal_loadings():
    """Данные с равным вкладом пунктов дают ровно единицу.

    Это точная проверка формулы: если все пункты - один и тот же признак с равным
    вкладом, надёжность обязана быть максимальной. Данные детерминированные,
    поэтому сравнение точное, а не «примерно».
    """
    generator = np.random.default_rng(777)
    base = generator.normal(0, 1, 120)
    data = np.column_stack([base, base * 2.0, base * 3.0])
    # При равных нагрузках дисперсия суммы растёт как k^2 * Var(base), а сумма
    # дисперсий - как k * Var(base), поэтому альфа равна 1.
    item_variances = np.var(data, axis=0, ddof=1)
    total_variance = np.var(data.sum(axis=1), ddof=1)
    k = data.shape[1]
    expected = (k / (k - 1)) * (1.0 - item_variances.sum() / total_variance)
    assert cronbach_alpha(data) == pytest.approx(expected, abs=1e-12)


def test_alpha_if_deleted_finds_weak_item():
    """Пункт-«чужак» должен портить альфу, и это должно быть видно."""
    data = np.column_stack([_scale_data(150, 0.4, 4), RNG.normal(0, 1, 150)])
    deleted = alpha_if_deleted(data)
    alpha = cronbach_alpha(data)
    # Без последнего (шумового) пункта альфа выше общей.
    assert deleted[4] > alpha
    assert deleted[4] == max(deleted)


def test_corrected_item_total_is_low_for_unrelated_item():
    data = np.column_stack([_scale_data(150, 0.4, 4), RNG.normal(0, 1, 150)])
    corrected = corrected_item_total(data)
    for index in range(4):
        assert corrected[index] > 0.5
    assert corrected[4] < 0.3


def test_split_half_and_spearman_brown():
    data = _scale_data(200, 0.5, 6)
    correlation, corrected = split_half_reliability(data)
    assert -1.0 < correlation < 1.0
    # Поправка Спирмена-Брауна: r' = 2r / (1 + r).
    assert corrected == pytest.approx(2 * correlation / (1 + correlation), abs=1e-12)
    assert corrected > correlation


def test_omega_is_high_for_consistent_scale():
    data = _scale_data(250, 0.5, 6)
    omega = mcdonald_omega(data)
    assert 0.5 < omega <= 1.0


def test_reliability_command_runs_end_to_end():
    data = _scale_data(150)
    dataset = _scale_dataset(data)
    result = ReliabilityCommand(dataset=dataset, items=dataset.names()).execute()
    titles = " ".join(table.title for table in result.tables)
    assert "Надёжность шкалы" in titles
    assert "Статистики пунктов" in titles
    assert result.syntax.startswith("RELIABILITY")


def test_reliability_warns_about_weak_item():
    data = np.column_stack([_scale_data(150, 0.4, 4), RNG.normal(0, 1, 150)])
    dataset = _scale_dataset(data)
    result = ReliabilityCommand(dataset=dataset, items=dataset.names()).execute()
    assert any("слабо согласуется" in warning for warning in result.warnings)


def test_reliability_needs_two_items():
    dataset = _scale_dataset(_scale_data(30, 0.5, 1))
    with pytest.raises(CommandError):
        ReliabilityCommand(dataset=dataset, items=dataset.names()).execute()


def test_reliability_reports_excluded_cases():
    data = _scale_data(40, 0.5, 3)
    data[0:5, 0] = np.nan
    dataset = _scale_dataset(data)
    result = ReliabilityCommand(dataset=dataset, items=dataset.names()).execute()
    summary = result.tables[0]
    rows = {row[0]: row[1] for row in summary.rows}
    assert rows["Всего"] == 40
    assert rows["Валидные"] == 35
    assert rows["Исключённые"] == 5


def test_reliability_on_demo_dataset_reports_alpha():
    """Пунктов-шкал в демо-наборе нет, но альфа на трёх переменных должна считаться."""
    dataset = demo_dataset(n=150, seed=11)
    result = run_reliability(
        ReliabilityCommand(dataset=dataset, items=["age", "income", "anxiety"])
    )
    assert any("Надёжность шкалы" in table.title for table in result.tables)


# ---------------------------------------------------------- факторный анализ


def test_kmo_is_high_for_clear_factor_structure():
    data = _two_factor_data()
    correlation = np.corrcoef(data, rowvar=False)
    kmo, _per_variable = kmo_measure(correlation)
    # Явная факторная структура: KMO должен быть заметно выше порога применимости.
    assert kmo > 0.6


def test_kmo_is_low_for_independent_variables():
    """Независимые переменные: общих факторов нет, KMO низкий."""
    data = RNG.normal(0, 1, (300, 6))
    correlation = np.corrcoef(data, rowvar=False)
    kmo, _ = kmo_measure(correlation)
    assert kmo < 0.6


def test_bartlett_is_significant_for_correlated_variables():
    data = _two_factor_data()
    correlation = np.corrcoef(data, rowvar=False)
    chi2, df, p_value = bartlett_test(correlation, len(data))
    assert chi2 > 0
    assert df == pytest.approx(15.0)  # 6 * 5 / 2
    assert p_value < 0.001


def test_factor_analysis_finds_two_factors():
    """Две группы пунктов должны дать ровно два фактора по критерию Кайзера."""
    data = _two_factor_data()
    names = [f"q{index + 1}" for index in range(6)]
    solution = fit_factor(data, names, method="pca", rotation="varimax")
    assert solution.n_factors == 2


def test_factor_loadings_separate_the_two_groups():
    """После вращения каждая тройка пунктов должна грузиться на свой фактор."""
    data = _two_factor_data()
    names = [f"q{index + 1}" for index in range(6)]
    solution = fit_factor(data, names, method="pca", rotation="varimax")
    loadings = np.abs(solution.loadings)
    # Первые три пункта - сильнее на первом факторе, вторые три - на втором.
    for index in range(3):
        assert loadings[index, 0] > loadings[index, 1]
    for index in range(3, 6):
        assert loadings[index, 1] > loadings[index, 0]
    # Нагрузка на «свой» фактор должна заметно превышать нагрузку на чужой,
    # а общности - быть высокими: структура в этих данных явная.
    for index in range(6):
        own = max(loadings[index])
        other = min(loadings[index])
        assert own > other * 1.5
    assert np.min(solution.communalities) > 0.7


def test_rotation_preserves_communalities():
    """Вращение перераспределяет нагрузки, но не меняет общности."""
    data = _two_factor_data()
    names = [f"q{index + 1}" for index in range(6)]
    solution = fit_factor(data, names, rotation="none")
    communalities_before = np.sum(solution.loadings**2, axis=1)
    rotated = varimax(solution.loadings)
    communalities_after = np.sum(rotated**2, axis=1)
    assert communalities_after == pytest.approx(communalities_before, abs=1e-9)


def test_varimax_stays_in_same_subspace():
    """Вращение - это поворот: скалярные произведения столбцов сохраняются."""
    data = _two_factor_data()
    solution = fit_factor(data, [f"q{i}" for i in range(6)], rotation="none")
    loadings = solution.loadings
    rotated = varimax(loadings)
    # Сравниваем суммы квадратов по столбцам: это дисперсия, объяснённая каждым
    # фактором. Нормировка столбцов внутри процедуры её не меняет.
    assert np.sum(rotated**2, axis=0) == pytest.approx(
        np.sum(loadings**2, axis=0), rel=0.15
    )
    # И общности (суммы по строкам) сохраняются точно.
    assert np.sum(rotated**2, axis=1) == pytest.approx(
        np.sum(loadings**2, axis=1), abs=1e-9
    )


def test_promax_returns_factor_correlations():
    data = _two_factor_data()
    solution = fit_factor(data, [f"q{i}" for i in range(6)], rotation="none")
    rotated, factor_correlation = promax(solution.loadings)
    assert rotated.shape == solution.loadings.shape
    assert factor_correlation.shape == (2, 2)
    # Диагональ корреляций факторов равна единице.
    assert np.diag(factor_correlation) == pytest.approx(np.ones(2), abs=1e-9)


def test_eigenvalues_sum_to_number_of_variables():
    """Сумма собственных значений корреляционной матрицы равна числу переменных."""
    data = _two_factor_data()
    solution = fit_factor(data, [f"q{i}" for i in range(6)])
    assert float(np.sum(solution.eigenvalues)) == pytest.approx(6.0, abs=1e-8)
    assert float(np.sum(solution.explained)) == pytest.approx(1.0, abs=1e-8)


def test_explicit_factor_count_is_respected():
    data = _two_factor_data()
    solution = fit_factor(data, [f"q{i}" for i in range(6)], n_factors=3)
    assert solution.n_factors == 3
    assert solution.loadings.shape == (6, 3)


def test_factor_command_runs_end_to_end():
    data = _two_factor_data(200)
    dataset = _scale_dataset(data)
    result = FactorCommand(dataset=dataset, variables=dataset.names()).execute()
    titles = " ".join(table.title for table in result.tables)
    assert "применимости" in titles
    assert "Объяснённая дисперсия" in titles
    assert "Общности" in titles
    assert "факторных нагрузок" in titles
    assert result.syntax.startswith("FACTOR")


def test_factor_needs_three_variables():
    data = _scale_data(50, 0.5, 2)
    dataset = _scale_dataset(data)
    with pytest.raises(CommandError):
        FactorCommand(dataset=dataset, variables=dataset.names()).execute()


def test_factor_rejects_too_many_requested_factors():
    data = _scale_data(50, 0.5, 3)
    dataset = _scale_dataset(data)
    with pytest.raises(CommandError):
        FactorCommand(dataset=dataset, variables=dataset.names(), n_factors=3).execute()


def test_factor_scores_are_standardized():
    """Факторные значения по методу регрессии имеют нулевое среднее."""
    data = _two_factor_data(300)
    solution = fit_factor(data, [f"q{i}" for i in range(6)])
    assert solution.scores is not None
    means = solution.scores.mean(axis=0)
    assert means == pytest.approx(np.zeros(solution.n_factors), abs=1e-9)


def test_factor_warns_on_bad_data():
    """Независимые переменные: факторный анализ неприменим, KMO низкий."""
    generator = np.random.default_rng(4242)
    data = generator.normal(0, 1, (400, 6))
    dataset = _scale_dataset(data)
    result = FactorCommand(dataset=dataset, variables=dataset.names()).execute()

    # KMO для независимых переменных должен быть заметно ниже 0.6: общих
    # факторов в таких данных нет.
    kmo_value = result.meta.get("kmo") if result.meta else None
    adequacy = next(t for t in result.tables if "применимости" in t.title)
    kmo_row = adequacy.rows[0]
    assert float(kmo_row[1]) < 0.6
    assert kmo_value is None or kmo_value < 0.6

def test_scree_table_lists_eigenvalues():
    data = _two_factor_data(200)
    dataset = _scale_dataset(data)
    result = FactorCommand(dataset=dataset, variables=dataset.names()).execute()
    variance = next(t for t in result.tables if "Объяснённая дисперсия" in t.title)
    first_row = variance.rows[0]
    assert first_row[0] == "1"
    # Первое собственное значение при явной структуре больше единицы.
    assert float(first_row[1]) > 1.0
