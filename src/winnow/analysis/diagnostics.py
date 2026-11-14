"""Общие диагностические расчёты для регрессии.

Здесь лежит то, что нужно и проверке качества, и Research Stress Test:
ковариационные матрицы робастных стандартных ошибок, тесты на
гетероскедастичность, меры влияния наблюдений. Формулы не зависят от отчёта и
от интерфейса, поэтому их можно проверить на синтетических данных.

Ничего не меняет в данных и не знает про HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats as scipy_stats


@dataclass(frozen=True)
class InfluenceMeasures:
    """Меры влияния наблюдений."""

    leverage: np.ndarray
    cooks: np.ndarray
    standardized_residuals: np.ndarray
    cooks_max: float
    influential: tuple[int, ...]
    high_leverage: tuple[int, ...]

    @property
    def n_influential(self) -> int:
        return len(self.influential)

    @property
    def n_high_leverage(self) -> int:
        return len(self.high_leverage)


@dataclass(frozen=True)
class HeteroscedasticityTest:
    """Результат теста на гетероскедастичность."""

    statistic: float | None
    df: int
    p_value: float | None
    kind: str


def design_matrix(
    predictors: np.ndarray | list[np.ndarray], *, with_constant: bool = True
) -> np.ndarray:
    """Собирает матрицу предикторов; константа — первый столбец."""
    columns = (
        [np.asarray(item, dtype=float) for item in predictors]
        if isinstance(predictors, list)
        else [np.asarray(predictors, dtype=float)]
    )
    if with_constant:
        columns.insert(0, np.ones(len(columns[0]), dtype=float))
    return np.column_stack(columns)


def leverage_values(x: np.ndarray) -> np.ndarray:
    """Диагональ матрицы шляпы X(X'X)^-1 X'."""
    inverse = np.linalg.pinv(x.T @ x)
    return np.einsum("ij,jk,ik->i", x, inverse, x)


def influence_measures(
    x: np.ndarray, residuals: np.ndarray, mse: float
) -> InfluenceMeasures:
    """Cook's Distance, leverage и стандартизованные остатки.

    Порог Кука 4/n — распространённое правило для поиска точек, которые стоит
    проверить; это не «выброс» и не повод автоматически удалять строку.
    """
    n, parameters = x.shape
    leverage = leverage_values(x)
    safe = np.clip(leverage, 0.0, 1.0 - 1e-12)

    cooks = np.zeros(n, dtype=float)
    if mse > 0:
        cooks = (residuals**2 / (parameters * mse)) * (
            safe / (1.0 - safe) ** 2
        )

    standardized = np.zeros(n, dtype=float)
    if mse > 0:
        standardized = residuals / np.sqrt(mse) / np.sqrt(1.0 - safe)

    cooks_threshold = 4.0 / n if n else float("inf")
    leverage_threshold = 2.0 * parameters / n if n else float("inf")
    influential = tuple(
        int(index) for index in np.where(cooks > cooks_threshold)[0]
    )
    high_leverage = tuple(
        int(index) for index in np.where(leverage > leverage_threshold)[0]
    )
    return InfluenceMeasures(
        leverage=leverage,
        cooks=cooks,
        standardized_residuals=standardized,
        cooks_max=float(np.nanmax(cooks)) if n else 0.0,
        influential=influential,
        high_leverage=high_leverage,
    )


def robust_covariance(
    x: np.ndarray, residuals: np.ndarray, kind: str
) -> np.ndarray:
    """Ковариационная матрица коэффициентов HC0–HC3.

    HC0 — базовая «сэндвич»-оценка; HC1 умножает её на n/(n-p); HC2 и HC3
    делят квадраты остатков на (1-h) и (1-h)^2 соответственно. Робастные
    ошибки не предполагают одинаковой дисперсии ошибок, но и не исправляют
    плохую спецификацию модели.
    """
    normalized = kind.strip().upper()
    if normalized not in {"HC0", "HC1", "HC2", "HC3"}:
        raise ValueError(f"Неизвестный тип робастных ошибок: {kind!r}")

    n, parameters = x.shape
    if n <= parameters:
        raise ValueError(
            f"Для робастных ошибок нужно больше наблюдений ({n}), "
            f"чем параметров ({parameters})"
        )

    leverage = np.clip(leverage_values(x), 0.0, 1.0 - 1e-12)
    squared = residuals**2
    if normalized == "HC0":
        weights = squared
    elif normalized == "HC1":
        weights = squared * n / (n - parameters)
    elif normalized == "HC2":
        weights = squared / (1.0 - leverage)
    else:
        weights = squared / (1.0 - leverage) ** 2

    inverse = np.linalg.pinv(x.T @ x)
    meat = x.T @ (weights[:, None] * x)
    return inverse @ meat @ inverse


def robust_standard_errors(
    x: np.ndarray, residuals: np.ndarray, kind: str
) -> np.ndarray:
    """Стандартные ошибки из робастной ковариационной матрицы."""
    return np.sqrt(np.diag(robust_covariance(x, residuals, kind)))


def breusch_pagan(
    residuals: np.ndarray, design: np.ndarray
) -> HeteroscedasticityTest:
    """Тест Бреуша-Пегана: квадраты остатков на предикторы.

    LM = n·R² вспомогательной регрессии, распределение — хи-квадрат.
    """
    n = len(residuals)
    if n <= design.shape[1] + 1:
        return HeteroscedasticityTest(None, 0, None, "Breusch-Pagan")
    squared = residuals**2
    try:
        coefficients, *_ = np.linalg.lstsq(design, squared, rcond=None)
    except np.linalg.LinAlgError:
        return HeteroscedasticityTest(None, 0, None, "Breusch-Pagan")
    predicted = design @ coefficients
    ss_residual = float(np.sum((squared - predicted) ** 2))
    ss_total = float(np.sum((squared - squared.mean()) ** 2))
    if ss_total <= 0:
        return HeteroscedasticityTest(None, 0, None, "Breusch-Pagan")
    r_squared = 1.0 - ss_residual / ss_total
    lm = n * max(0.0, min(1.0, r_squared))
    df = max(1, design.shape[1] - 1)
    return HeteroscedasticityTest(
        statistic=float(lm),
        df=df,
        p_value=float(scipy_stats.chi2.sf(lm, df)),
        kind="Breusch-Pagan",
    )


def white_test(
    residuals: np.ndarray, design: np.ndarray
) -> HeteroscedasticityTest:
    """Тест Уайта: квадраты остатков на предикторы, их квадраты и произведения.

    Это более общая проверка, чем Бреуш-Пеган: она ловит и нелинейную связь
    дисперсии с факторами. На большом числе предикторов вспомогательная
    регрессия быстро растёт, поэтому тест ограничивается разумным числом
    столбцов.
    """
    n, parameters = design.shape
    if parameters < 2 or n <= parameters + 1:
        return HeteroscedasticityTest(None, 0, None, "White")

    predictors = design[:, 1:]
    if predictors.shape[1] > 8:
        # Иначе aux-матрица становится шире числа наблюдений и тест теряет смысл.
        predictors = predictors[:, :8]

    columns = [np.ones(n, dtype=float)]
    columns.extend(predictors[:, index] for index in range(predictors.shape[1]))
    columns.extend(predictors[:, index] ** 2 for index in range(predictors.shape[1]))
    for first in range(predictors.shape[1]):
        for second in range(first + 1, predictors.shape[1]):
            columns.append(predictors[:, first] * predictors[:, second])
    auxiliary = np.column_stack(columns)

    squared = residuals**2
    try:
        coefficients, *_ = np.linalg.lstsq(auxiliary, squared, rcond=None)
    except np.linalg.LinAlgError:
        return HeteroscedasticityTest(None, 0, None, "White")
    predicted = auxiliary @ coefficients
    ss_residual = float(np.sum((squared - predicted) ** 2))
    ss_total = float(np.sum((squared - squared.mean()) ** 2))
    if ss_total <= 0:
        return HeteroscedasticityTest(None, 0, None, "White")
    r_squared = 1.0 - ss_residual / ss_total
    lm = n * max(0.0, min(1.0, r_squared))
    df = max(1, auxiliary.shape[1] - 1)
    return HeteroscedasticityTest(
        statistic=float(lm),
        df=df,
        p_value=float(scipy_stats.chi2.sf(lm, df)),
        kind="White",
    )


__all__ = [
    "HeteroscedasticityTest",
    "InfluenceMeasures",
    "breusch_pagan",
    "design_matrix",
    "influence_measures",
    "leverage_values",
    "robust_covariance",
    "robust_standard_errors",
    "white_test",
]
