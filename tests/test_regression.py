"""Эталонные тесты регрессии.

Линейная регрессия сверяется с прямой формулой наименьших квадратов и с
характеристиками, которые можно посчитать вручную. Логистическая - с условием
максимума правдоподобия: градиент логарифма правдоподобия в найденной точке
обязан быть нулевым, иначе решение не оптимально.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.command import CommandError, LinearRegressionCommand, LogisticRegressionCommand
from winnow.stats.regression import fit_linear, fit_logistic

RNG = np.random.default_rng(20240517)


def _linear_dataset(n: int = 120) -> pd.DataFrame:
    """Данные с известной зависимостью: y = 3 + 2*x1 - 1.5*x2 + шум.

    Предикторы центрированы: тогда свободный член равен среднему отклику при
    средних значениях предикторов и его легко проверить. Без центрирования
    свободный член «вбирает» вклады средних, и проверка становится шумной.
    """
    x1 = RNG.normal(0, 2, n)
    x2 = RNG.normal(0, 1, n)
    noise = RNG.normal(0, 1.5, n)
    y = 3.0 + 2.0 * x1 - 1.5 * x2 + noise
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


def _ols_reference(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Коэффициенты МНК через нормальные уравнения - независимый эталон."""
    return np.linalg.solve(x.T @ x, x.T @ y)


# ------------------------------------------------------------ линейная модель


def test_linear_coefficients_match_normal_equations():
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)

    x = np.column_stack([np.ones(len(frame)), frame["x1"], frame["x2"]])
    y = frame["y"].to_numpy()
    reference = _ols_reference(x, y)

    assert fit.coefficients == pytest.approx(reference, abs=1e-10)
    # Коэффициенты должны быть близки к истинным (3, 2, -1.5): проверяем и знаки,
    # и порядок - если перепутать предикторы, знаки изменятся.
    assert fit.coefficients[0] == pytest.approx(3.0, abs=0.5)
    assert fit.coefficients[1] == pytest.approx(2.0, abs=0.3)
    assert fit.coefficients[2] == pytest.approx(-1.5, abs=0.3)


def test_linear_r_squared_matches_definition():
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    y = frame["y"].to_numpy()
    reference = 1.0 - float(np.sum(fit.residuals**2)) / float(np.sum((y - y.mean()) ** 2))
    assert fit.r_squared == pytest.approx(reference, abs=1e-12)
    assert 0.0 < fit.r_squared <= 1.0


def test_linear_f_statistic_matches_definition():
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    assert fit.f_value == pytest.approx(fit.ms_regression / fit.ms_residual, abs=1e-12)
    assert fit.df_regression == pytest.approx(2.0)
    assert fit.df_residual == pytest.approx(117.0)
    expected_p = float(sps.f.sf(fit.f_value, fit.df_regression, fit.df_residual))
    assert fit.f_p_value == pytest.approx(expected_p, abs=1e-12)


def test_linear_standard_errors_match_manual_formula():
    """Стд. ошибки: sqrt(diag(sigma^2 * (X'X)^-1)) - считаем вручную."""
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    x = np.column_stack([np.ones(len(frame)), frame["x1"], frame["x2"]])
    n, p = x.shape
    y = frame["y"].to_numpy()
    residuals = y - x @ fit.coefficients
    sigma2 = float(np.sum(residuals**2)) / (n - p)
    covariance = sigma2 * np.linalg.inv(x.T @ x)
    assert fit.std_errors == pytest.approx(np.sqrt(np.diag(covariance)), abs=1e-12)


def test_linear_t_and_p_values_match_scipy():
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    expected_t = fit.coefficients / fit.std_errors
    assert fit.t_values == pytest.approx(expected_t, abs=1e-12)
    expected_p = 2.0 * sps.t.sf(np.abs(expected_t), fit.df_residual)
    assert fit.p_values == pytest.approx(expected_p, abs=1e-12)


def test_linear_confidence_interval_brackets_coefficient():
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    for index in range(len(fit.names)):
        assert fit.ci_low[index] < fit.coefficients[index] < fit.ci_high[index]


def test_vif_is_one_for_independent_predictors():
    """Независимые предикторы не должны показывать мультиколлинеарность."""
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    for value in fit.vif.values():
        assert value == pytest.approx(1.0, abs=0.1)


def test_vif_detects_collinear_predictors():
    """x2 - почти копия x1: VIF обязан это заметить."""
    n = 100
    x1 = RNG.normal(0, 1, n)
    x2 = x1 + RNG.normal(0, 0.01, n)  # почти полная коллинеарность
    y = 2.0 * x1 + RNG.normal(0, 0.5, n)
    frame = pd.DataFrame({"y": y, "x1": x1, "x2": x2})
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    assert fit.vif["x1"] > 100
    assert fit.vif["x2"] > 100


def test_durbin_watson_near_two_for_random_residuals():
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    assert 1.0 < fit.durbin_watson < 3.0


def test_standardized_coefficients_are_comparable():
    """Стандартизованные коэффициенты равны B * sd(x) / sd(y)."""
    frame = _linear_dataset()
    fit = fit_linear(frame, "y", ["x1", "x2"], 0.95)
    assert fit.standardized is not None
    for position, name in enumerate(["x1", "x2"]):
        index = fit.names.index(name)
        expected = (
            fit.coefficients[index]
            * float(np.std(frame[name], ddof=1))
            / float(np.std(frame["y"], ddof=1))
        )
        assert fit.standardized[position] == pytest.approx(expected, abs=1e-12)


def test_perfectly_collinear_predictors_are_rejected():
    n = 60
    x1 = RNG.normal(0, 1, n)
    frame = pd.DataFrame({"y": RNG.normal(0, 1, n), "x1": x1, "x2": 2.0 * x1})
    with pytest.raises(ValueError) as error:
        fit_linear(frame, "y", ["x1", "x2"], 0.95)
    assert "зависимы" in str(error.value)


def test_linear_command_runs_end_to_end():
    dataset = Dataset.from_dataframe(_linear_dataset())
    result = LinearRegressionCommand(
        dataset=dataset, dependent="y", predictors=["x1", "x2"]
    ).execute()
    titles = " ".join(table.title for table in result.tables)
    assert "Сводка по модели" in titles
    assert "Дисперсионный анализ модели" in titles
    assert "Коэффициенты" in titles
    assert "Мультиколлинеарность" in titles
    assert "Диагностика остатков" in titles
    assert result.syntax.startswith("REGRESSION")


def test_linear_command_rejects_same_variable_twice():
    dataset = Dataset.from_dataframe(_linear_dataset())
    with pytest.raises(CommandError):
        LinearRegressionCommand(dataset=dataset, dependent="y", predictors=["y"]).execute()


def test_linear_reports_excluded_cases():
    """Пропуски выкидывают весь кейс, и это должно быть видно в отчёте."""
    frame = _linear_dataset(40)
    frame.loc[0:9, "x1"] = np.nan
    dataset = Dataset.from_dataframe(frame)
    result = LinearRegressionCommand(
        dataset=dataset, dependent="y", predictors=["x1", "x2"]
    ).execute()
    summary = next(t for t in result.tables if "обработке наблюдений" in t.title)
    rows = {row[0]: row[1] for row in summary.rows}
    assert rows["Всего кейсов"] == 40
    assert rows["Включено в анализ"] == 30
    assert rows["Исключено (пропуски)"] == 10


# -------------------------------------------------------- логистическая модель


def _logistic_frame(n: int = 300) -> pd.DataFrame:
    """Бинарный отклик с двумя предикторами."""
    x1 = RNG.normal(0, 1, n)
    x2 = RNG.normal(0, 1, n)
    logit = -0.5 + 1.2 * x1 - 0.8 * x2
    probability = 1.0 / (1.0 + np.exp(-logit))
    y = (RNG.random(n) < probability).astype(int)
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


def test_logistic_gradient_is_zero_at_solution():
    """Условие максимума правдоподобия: градиент в найденной точке равен нулю.

    Это самая надёжная проверка: она не зависит от того, какой программой
    считать, и прямо говорит, что решение оптимально.
    """
    frame = _logistic_frame()
    fit = fit_logistic(frame, "y", ["x1", "x2"], 0.95, event_value=1)

    x = np.column_stack([np.ones(len(frame)), frame["x1"], frame["x2"]])
    y = (frame["y"].to_numpy() == 1).astype(float)
    eta = x @ fit.coefficients
    mu = 1.0 / (1.0 + np.exp(-eta))
    gradient = x.T @ (y - mu)
    assert gradient == pytest.approx(np.zeros(3), abs=1e-6)


def test_logistic_coefficients_recover_true_effect_signs():
    frame = _logistic_frame()
    fit = fit_logistic(frame, "y", ["x1", "x2"], 0.95, event_value=1)
    intercept, beta1, beta2 = fit.coefficients
    # Истинные значения: -0.5, +1.2, -0.8.
    assert beta1 == pytest.approx(1.2, abs=0.5)
    assert beta2 == pytest.approx(-0.8, abs=0.5)
    assert intercept == pytest.approx(-0.5, abs=0.6)


def test_logistic_odds_ratios_are_exp_of_coefficients():
    frame = _logistic_frame()
    fit = fit_logistic(frame, "y", ["x1", "x2"], 0.95, event_value=1)
    assert fit.odds_ratios == pytest.approx(np.exp(fit.coefficients), abs=1e-12)
    assert fit.odds_low == pytest.approx(np.exp(fit.ci_low), abs=1e-12)
    assert fit.odds_high == pytest.approx(np.exp(fit.ci_high), abs=1e-12)
    # Предиктор x1 увеличивает шанс события, значит отношение шансов больше единицы.
    assert fit.odds_ratios[1] > 1.0


def test_logistic_wald_statistic_matches_definition():
    frame = _logistic_frame()
    fit = fit_logistic(frame, "y", ["x1", "x2"], 0.95, event_value=1)
    expected = (fit.coefficients / fit.std_errors) ** 2
    assert fit.wald == pytest.approx(expected, abs=1e-12)
    assert fit.p_values == pytest.approx(sps.chi2.sf(expected, 1), abs=1e-12)


def test_logistic_log_likelihood_matches_direct_formula():
    frame = _logistic_frame()
    fit = fit_logistic(frame, "y", ["x1", "x2"], 0.95, event_value=1)
    x = np.column_stack([np.ones(len(frame)), frame["x1"], frame["x2"]])
    eta = x @ fit.coefficients
    mu = 1.0 / (1.0 + np.exp(-eta))
    y = (frame["y"].to_numpy() == 1).astype(float)
    # Правдоподобие напрямую: сумма log(mu) для событий и log(1 - mu) для не-событий.
    expected = float(np.sum(y * np.log(mu) + (1 - y) * np.log(1 - mu)))
    assert fit.log_likelihood == pytest.approx(expected, abs=1e-9)
    assert fit.deviance == pytest.approx(-2.0 * expected, abs=1e-9)


def test_logistic_model_beats_random_guess():
    frame = _logistic_frame(400)
    fit = fit_logistic(frame, "y", ["x1", "x2"], 0.95, event_value=1)
    assert fit.accuracy > 0.6
    assert 0.0 <= fit.sensitivity <= 1.0
    assert 0.0 <= fit.specificity <= 1.0
    assert 0.0 <= fit.pseudo_r2_nagelkerke <= 1.0


def test_logistic_requires_binary_dependent():
    frame = _linear_dataset(50)
    dataset = Dataset.from_dataframe(frame)
    # Непрерывный отклик: три и более уникальных значения.
    with pytest.raises(CommandError) as error:
        LogisticRegressionCommand(dataset=dataset, dependent="y", predictors=["x1"]).execute()
    assert "два значения" in str(error.value)


def test_logistic_command_runs_end_to_end():
    frame = _logistic_frame(200)
    dataset = Dataset.from_dataframe(frame)
    result = LogisticRegressionCommand(
        dataset=dataset, dependent="y", predictors=["x1", "x2"], reference_value=1
    ).execute()
    titles = " ".join(table.title for table in result.tables)
    assert "Сводка по модели" in titles
    assert "отношения шансов" in titles
    assert result.syntax.startswith("LOGISTIC REGRESSION")


def test_logistic_reference_value_must_exist():
    frame = _logistic_frame(100)
    dataset = Dataset.from_dataframe(frame)
    with pytest.raises(CommandError):
        LogisticRegressionCommand(
            dataset=dataset, dependent="y", predictors=["x1"], reference_value=7
        ).execute()


def test_logistic_event_counts_are_reported():
    frame = _logistic_frame(150)
    dataset = Dataset.from_dataframe(frame)
    result = LogisticRegressionCommand(
        dataset=dataset, dependent="y", predictors=["x1"], reference_value=1
    ).execute()
    summary = next(t for t in result.tables if "Сводка по модели" in t.title)
    rows = {row[0]: row[1] for row in summary.rows}
    assert rows["Событий / не событий"] == "1" or "/" in str(rows["Событий / не событий"])


def test_regression_on_demo_dataset():
    """Проверка на реалистичных данных: доход предсказывается возрастом и тревожностью."""
    dataset = demo_dataset(n=200, seed=20240517)
    result = LinearRegressionCommand(
        dataset=dataset, dependent="income", predictors=["age", "anxiety"]
    ).execute()
    coefficients = next(t for t in result.tables if t.title == "Коэффициенты")
    assert coefficients.rows
    assert not result.warnings or all("не сошлось" not in w for w in result.warnings)
