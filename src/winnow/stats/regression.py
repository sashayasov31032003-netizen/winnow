"""Линейная и логистическая регрессия с диагностикой.

Зачем именно с диагностикой: регрессию в дипломной работе первым делом спросят
про условия применимости. Коэффициенты посчитать мало - нужно показать, что
модель адекватна, предикторы не дублируют друг друга и остатки ведут себя
прилично. Поэтому здесь сразу считаются:

* качество модели (R-квадрат, скорректированный R-квадрат, F-критерий);
* вклад каждого предиктора с доверительными интервалами;
* мультиколлинеарность (VIF и толерантность);
* автокорреляция остатков (Дарбин-Уотсон) и их нормальность;
* для логистической регрессии - отношение шансов и качество предсказания.

Числа сверяются со scipy и с формулами метода наименьших квадратов.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.stats import interpretation
from winnow.stats.command import (
    CommandError,
    LinearRegressionCommand,
    LogisticRegressionCommand,
)
from winnow.stats.result import Column, Result, Table

# ---------------------------------------------------------------------------
# Линейная регрессия
# ---------------------------------------------------------------------------


@dataclass
class LinearFit:
    """Результат подгонки линейной регрессии."""

    names: list[str]                 # имена предикторов, включая константу
    coefficients: np.ndarray
    std_errors: np.ndarray
    t_values: np.ndarray
    p_values: np.ndarray
    ci_low: np.ndarray
    ci_high: np.ndarray
    standardized: np.ndarray | None  # стандартизованные коэффициенты (бета)
    n: int
    df_regression: float
    df_residual: float
    r_squared: float
    adj_r_squared: float
    std_error_estimate: float
    ss_regression: float
    ss_residual: float
    ss_total: float
    ms_regression: float
    ms_residual: float
    f_value: float
    f_p_value: float
    durbin_watson: float
    residuals: np.ndarray
    fitted: np.ndarray
    vif: dict[str, float]
    condition_index: float


def _design_matrix(
    frame: pd.DataFrame, predictors: list[str], with_constant: bool
) -> np.ndarray:
    """Матрица предикторов со столбцом константы в начале."""
    columns = [frame[name].to_numpy(dtype=float) for name in predictors]
    if with_constant:
        columns.insert(0, np.ones(len(frame)))
    return np.column_stack(columns)


def fit_linear(
    frame: pd.DataFrame,
    dependent: str,
    predictors: list[str],
    confidence: float,
    with_constant: bool = True,
) -> LinearFit:
    """Подгоняет линейную регрессию методом наименьших квадратов."""
    y = frame[dependent].to_numpy(dtype=float)
    x = _design_matrix(frame, predictors, with_constant)
    n, p = x.shape
    if n <= p:
        raise ValueError(
            f"Наблюдений ({n}) должно быть больше, чем параметров модели ({p})"
        )

    # lstsq устойчив к почти вырожденным матрицам, но точную коллинеарность
    # всё равно нужно поймать: иначе стандартные ошибки окажутся бессмысленными.
    coefficients, _residuals, rank, _singular = np.linalg.lstsq(x, y, rcond=None)
    if rank < p:
        raise ValueError(
            "Предикторы линейно зависимы (один выражается через другие) - "
            "уберите лишнюю переменную"
        )

    fitted = x @ coefficients
    residuals = y - fitted
    df_residual = float(n - p)

    ss_residual = float(np.sum(residuals**2))
    mean_y = float(np.mean(y))
    ss_total = float(np.sum((y - mean_y) ** 2))
    ss_regression = ss_total - ss_residual
    ms_residual = ss_residual / df_residual
    df_regression = float(p - 1) if with_constant else float(p)
    ms_regression = ss_regression / df_regression if df_regression > 0 else float("nan")

    r_squared = 1.0 - ss_residual / ss_total if ss_total > 0 else float("nan")
    adj_r_squared = (
        1.0 - (1.0 - r_squared) * (n - (1 if with_constant else 0)) / df_residual
        if df_residual > 0
        else float("nan")
    )
    std_error_estimate = math.sqrt(ms_residual) if ms_residual >= 0 else float("nan")

    # Ковариационная матрица коэффициентов: sigma^2 * (X'X)^-1.
    covariance = ms_residual * np.linalg.inv(x.T @ x)
    std_errors = np.sqrt(np.diag(covariance))
    with np.errstate(divide="ignore", invalid="ignore"):
        t_values = coefficients / std_errors
    p_values = 2.0 * sps.t.sf(np.abs(t_values), df_residual)
    critical = float(sps.t.ppf(1.0 - (1.0 - confidence) / 2.0, df_residual))
    margin = critical * std_errors

    f_value = ms_regression / ms_residual if ms_residual > 0 else float("nan")
    f_p_value = (
        float(sps.f.sf(f_value, df_regression, df_residual))
        if math.isfinite(f_value) and df_regression > 0
        else float("nan")
    )

    names = (["(Константа)"] if with_constant else []) + list(predictors)

    # Стандартизованные коэффициенты: сравнимы между собой, потому что выражены
    # в стандартных отклонениях.
    standardized: np.ndarray | None = None
    if len(predictors) > 1 or True:
        std_y = float(np.std(y, ddof=1))
        if std_y > 0:
            betas = []
            for name in predictors:
                std_x = float(np.std(frame[name].to_numpy(dtype=float), ddof=1))
                index = names.index(name)
                betas.append(coefficients[index] * std_x / std_y if std_x > 0 else float("nan"))
            standardized = np.array(betas, dtype=float)

    durbin_watson = (
        float(np.sum(np.diff(residuals) ** 2) / ss_residual) if ss_residual > 0 else float("nan")
    )

    return LinearFit(
        names=names,
        coefficients=coefficients,
        std_errors=std_errors,
        t_values=t_values,
        p_values=p_values,
        ci_low=coefficients - margin,
        ci_high=coefficients + margin,
        standardized=standardized,
        n=n,
        df_regression=df_regression,
        df_residual=df_residual,
        r_squared=r_squared,
        adj_r_squared=adj_r_squared,
        std_error_estimate=std_error_estimate,
        ss_regression=ss_regression,
        ss_residual=ss_residual,
        ss_total=ss_total,
        ms_regression=ms_regression,
        ms_residual=ms_residual,
        f_value=f_value,
        f_p_value=f_p_value,
        durbin_watson=durbin_watson,
        residuals=residuals,
        fitted=fitted,
        vif=_vif(frame, predictors),
        condition_index=_condition_index(x),
    )


def _safe_exp(values: np.ndarray) -> np.ndarray:
    """Возводит в степень без переполнения.

    На вырожденных предикторах-отметках коэффициент бывает настолько велик, что
    exp даёт бесконечность, и в таблице появляется «inf» вместо числа. Предел
    стоит там, где ещё получается представимое число, поэтому обычные значения
    не меняются вовсе.
    """
    return np.exp(np.clip(values, -700.0, 700.0))


def _vif(frame: pd.DataFrame, predictors: list[str]) -> dict[str, float]:
    """Фактор инфляции дисперсии: показывает, дублируют ли предикторы друг друга.

    VIF больше 10 (в некоторых руководствах - больше 5) означает серьёзную
    мультиколлинеарность: коэффициенты становятся неустойчивыми.
    """
    result: dict[str, float] = {}
    for name in predictors:
        others = [other for other in predictors if other != name]
        if not others:
            result[name] = 1.0
            continue
        y = frame[name].to_numpy(dtype=float)
        x = _design_matrix(frame, others, with_constant=True)
        coefficients, _res, _rank, _s = np.linalg.lstsq(x, y, rcond=None)
        fitted = x @ coefficients
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if ss_tot <= 0:
            result[name] = float("nan")
            continue
        r_squared = 1.0 - ss_res / ss_tot
        result[name] = 1.0 / (1.0 - r_squared) if r_squared < 1.0 else float("inf")
    return result


def _condition_index(x: np.ndarray) -> float:
    """Число обусловленности: грубая мера вырожденности системы.

    Столбцы предварительно нормируются. Без нормировки показатель бесполезен:
    доход в десятках тысяч и возраст в годах дают огромное число при полном
    отсутствии мультиколлинеарности - это артефакт масштаба, а не проблема данных.
    """
    if x.size == 0:
        return float("nan")
    norms = np.linalg.norm(x, axis=0)
    norms[norms == 0] = 1.0
    scaled = x / norms
    singular = np.linalg.svd(scaled, compute_uv=False)
    if singular.size == 0 or singular[-1] == 0:
        return float("inf")
    return float(singular[0] / singular[-1])


# ---------------------------------------------------------------------------
# Логистическая регрессия
# ---------------------------------------------------------------------------


@dataclass
class LogisticFit:
    """Результат подгонки логистической регрессии."""

    names: list[str]
    coefficients: np.ndarray
    std_errors: np.ndarray
    wald: np.ndarray
    p_values: np.ndarray
    ci_low: np.ndarray
    ci_high: np.ndarray
    odds_ratios: np.ndarray
    odds_low: np.ndarray
    odds_high: np.ndarray
    n: int
    iterations: int
    converged: bool
    log_likelihood: float
    log_likelihood_null: float
    deviance: float
    aic: float
    bic: float
    pseudo_r2_cox: float
    pseudo_r2_nagelkerke: float
    accuracy: float
    sensitivity: float
    specificity: float
    event_value: Any
    non_event_value: Any
    n_events: int
    n_non_events: int


def fit_logistic(
    frame: pd.DataFrame,
    dependent: str,
    predictors: list[str],
    confidence: float,
    event_value: Any,
    max_iterations: int = 50,
    tolerance: float = 1e-8,
) -> LogisticFit:
    """Подгоняет логистическую регрессию методом максимального правдоподобия.

    Реализация через итерации Ньютона-Рафсона: сходится за 5-10 шагов и не
    требует внешних зависимостей. Числа сверяются со scipy/statsmodels.
    """
    events = (frame[dependent].to_numpy(dtype=float) == float(event_value)).astype(float)
    x = _design_matrix(frame, predictors, with_constant=True)
    n, p = x.shape
    n_events = int(events.sum())
    n_non_events = n - n_events
    if n_events == 0 or n_non_events == 0:
        raise ValueError("В данных есть только одно значение отклика - модель не построить")

    beta = np.zeros(p, dtype=float)

    def log_likelihood(values: np.ndarray) -> float:
        eta = x @ values
        # Логарифм правдоподобия в виде, устойчивом к переполнению.
        return float(np.sum(events * -np.logaddexp(0.0, -eta) + (1 - events) * -np.logaddexp(0.0, eta)))

    previous = log_likelihood(beta)
    converged = False
    iterations = 0

    for iteration in range(1, max_iterations + 1):
        iterations = iteration
        eta = x @ beta
        mu = 1.0 / (1.0 + np.exp(-eta))
        # Веса IRLS: mu * (1 - mu), защита от нуля на краях.
        weights = np.clip(mu * (1.0 - mu), 1e-10, None)
        gradient = x.T @ (events - mu)
        hessian = x.T @ (x * weights[:, None])
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            raise ValueError(
                "Матрица информации вырождена: предикторы линейно зависимы или "
                "полностью разделяют отклик"
            ) from None
        beta = beta + step
        current = log_likelihood(beta)
        if abs(current - previous) < tolerance:
            converged = True
            previous = current
            break
        previous = current

    eta = x @ beta
    mu = 1.0 / (1.0 + np.exp(-eta))
    weights = np.clip(mu * (1.0 - mu), 1e-10, None)
    hessian = x.T @ (x * weights[:, None])
    try:
        covariance = np.linalg.inv(hessian)
    except np.linalg.LinAlgError:
        covariance = np.linalg.pinv(hessian)

    std_errors = np.sqrt(np.diag(covariance))
    with np.errstate(divide="ignore", invalid="ignore"):
        wald = (beta / std_errors) ** 2
    p_values = sps.chi2.sf(wald, 1)
    critical = float(sps.norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    ci_low = beta - critical * std_errors
    ci_high = beta + critical * std_errors

    log_likelihood_value = log_likelihood(beta)
    rate = n_events / n
    log_likelihood_null = float(
        n_events * math.log(rate) + n_non_events * math.log(1.0 - rate)
    ) if 0 < rate < 1 else float("nan")
    deviance = -2.0 * log_likelihood_value
    aic = -2.0 * log_likelihood_value + 2.0 * p
    bic = -2.0 * log_likelihood_value + math.log(n) * p

    # Псевдо-R-квадраты: прямого аналога R-квадрата в логистической регрессии нет.
    cox = 1.0 - math.exp((log_likelihood_null - log_likelihood_value) * 2.0 / n) if math.isfinite(log_likelihood_null) else float("nan")
    nagelkerke = (
        cox / (1.0 - math.exp(2.0 * log_likelihood_null / n))
        if math.isfinite(cox) and log_likelihood_null < 0
        else float("nan")
    )

    predicted = (mu >= 0.5).astype(float)
    accuracy = float(np.mean(predicted == events))
    positives = events == 1
    negatives = events == 0
    sensitivity = float(np.mean(predicted[positives] == 1)) if positives.any() else float("nan")
    specificity = float(np.mean(predicted[negatives] == 0)) if negatives.any() else float("nan")

    unique = sorted(set(frame[dependent].dropna().tolist()), key=lambda value: str(value))
    non_event = next((value for value in unique if value != event_value), None)

    names = ["(Константа)"] + list(predictors)
    return LogisticFit(
        names=names,
        coefficients=beta,
        std_errors=std_errors,
        wald=wald,
        p_values=p_values,
        ci_low=ci_low,
        ci_high=ci_high,
        # Возведение в степень ограничивается: при большом коэффициенте (бывает
        # на вырожденных предикторах-отметках) exp переполняется, и в отчёте
        # появляется «inf» вместо числа. Предел берётся от максимального
        # представимого числа, поэтому настоящие значения не меняются.
        odds_ratios=_safe_exp(beta),
        odds_low=_safe_exp(ci_low),
        odds_high=_safe_exp(ci_high),
        n=n,
        iterations=iterations,
        converged=converged,
        log_likelihood=log_likelihood_value,
        log_likelihood_null=log_likelihood_null,
        deviance=deviance,
        aic=aic,
        bic=bic,
        pseudo_r2_cox=cox,
        pseudo_r2_nagelkerke=nagelkerke,
        accuracy=accuracy,
        sensitivity=sensitivity,
        specificity=specificity,
        event_value=event_value,
        non_event_value=non_event,
        n_events=n_events,
        n_non_events=n_non_events,
    )


# ---------------------------------------------------------------------------
# Таблицы вывода
# ---------------------------------------------------------------------------


def _clean_frame(
    dataset, dependent: str, predictors: list[str]
) -> tuple[pd.DataFrame, int, int]:
    """Готовит данные для регрессии: только полные наблюдения.

    Регрессия не терпит пропусков: одно пропущенное значение выкидывает весь
    кейс. Поэтому число исключённых кейсов сообщается в отчёте - пользователь
    должен видеть, сколько данных ушло.
    """
    frame = dataset.analysis_frame([dependent, *predictors])
    total = int(len(frame))
    numeric = pd.DataFrame(
        {name: pd.to_numeric(frame[name], errors="coerce") for name in [dependent, *predictors]}
    )
    complete = numeric.dropna()
    return complete, total, total - int(len(complete))


def _model_summary_table(fit: LinearFit, dependent_name: str) -> Table:
    table = Table(
        title=f"Сводка по модели: {dependent_name}",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", decimals=3),
        ],
    )
    table.add_row(["R", math.sqrt(fit.r_squared) if fit.r_squared >= 0 else float("nan")])
    table.add_row(["R-квадрат", fit.r_squared])
    table.add_row(["Скорректированный R-квадрат", fit.adj_r_squared])
    table.add_row(["Стд. ошибка оценки", fit.std_error_estimate])
    table.add_row(["Число наблюдений", float(fit.n)])
    table.footnote(
        "R-квадрат показывает долю разброса зависимой переменной, объяснённую "
        "моделью. Скорректированный R-квадрат штрафует за лишние предикторы."
    )
    return table


def _anova_regression_table(fit: LinearFit) -> Table:
    table = Table(
        title="Дисперсионный анализ модели",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Сумма квадратов", decimals=3),
            Column("ст. св.", decimals=0),
            Column("Средний квадрат", decimals=3),
            Column("F", decimals=3),
            Column("знач.", decimals=3),
        ],
    )
    table.add_row(
        [
            "Регрессия",
            fit.ss_regression,
            fit.df_regression,
            fit.ms_regression,
            fit.f_value,
            fit.f_p_value,
        ]
    )
    table.add_row(["Остатки", fit.ss_residual, fit.df_residual, fit.ms_residual, None, None])
    table.add_row(
        ["Всего", fit.ss_total, fit.df_regression + fit.df_residual, None, None, None]
    )
    table.footnote(
        "Нулевая гипотеза: все коэффициенты при предикторах равны нулю. "
        "Значимость меньше 0.05 означает, что модель в целом работает."
    )
    return table


def _coefficients_table(fit: LinearFit, confidence: float, standardize: bool) -> Table:
    columns = [
        Column("", align="left", is_metric=False),
        Column("B", decimals=3),
        Column("Стд. ошибка", decimals=3),
    ]
    if standardize and fit.standardized is not None:
        columns.append(Column("Бета", decimals=3))
    columns += [
        Column("t", decimals=3),
        Column("знач.", decimals=3),
        Column("Нижняя граница B", decimals=3),
        Column("Верхняя граница B", decimals=3),
    ]

    table = Table(title="Коэффициенты", columns=columns)
    has_constant = "(Константа)" in fit.names
    for index, name in enumerate(fit.names):
        row: list[Any] = [
            name,
            float(fit.coefficients[index]),
            float(fit.std_errors[index]),
        ]
        if standardize and fit.standardized is not None:
            if name == "(Константа)":
                row.append(None)
            else:
                # Индекс в списке предикторов: без константы он совпадает с
                # позицией в names, с константой - сдвинут на единицу.
                position = index - (1 if has_constant else 0)
                row.append(float(fit.standardized[position]))
        row += [
            float(fit.t_values[index]),
            float(fit.p_values[index]),
            float(fit.ci_low[index]),
            float(fit.ci_high[index]),
        ]
        table.add_row(row)

    table.footnote(
        f"B - ненормированный коэффициент: изменение зависимой переменной при "
        f"изменении предиктора на единицу. Доверительный интервал: {confidence * 100:.1f}%."
    )
    if standardize:
        table.footnote(
            "Бета - стандартизованные коэффициенты: их можно сравнивать между собой "
            "по силе влияния."
        )
    return table


def _collinearity_table(fit: LinearFit) -> Table:
    table = Table(
        title="Мультиколлинеарность",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Толерантность", decimals=3),
            Column("VIF", decimals=3),
        ],
    )
    for name, value in fit.vif.items():
        tolerance = 1.0 / value if value and math.isfinite(value) and value > 0 else 0.0
        table.add_row([name, tolerance, value if math.isfinite(value) else None])
    table.add_row(["Число обусловленности", None, fit.condition_index])
    table.footnote(
        "VIF больше 10 (в строгих руководствах - больше 5) означает, что предикторы "
        "дублируют друг друга и коэффициенты неустойчивы."
    )
    return table


def _residuals_table(fit: LinearFit) -> Table:
    table = Table(
        title="Диагностика остатков",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", decimals=3),
        ],
    )
    table.add_row(["Среднее остатков", float(np.mean(fit.residuals))])
    table.add_row(["Стд. отклонение остатков", float(np.std(fit.residuals, ddof=1))])
    table.add_row(["Минимум остатка", float(np.min(fit.residuals))])
    table.add_row(["Максимум остатка", float(np.max(fit.residuals))])
    table.add_row(["Дарбин-Уотсон", fit.durbin_watson])

    if fit.n > 3 and np.std(fit.residuals, ddof=1) > 0:
        shapiro = sps.shapiro(fit.residuals)
        table.add_row(["Шапиро-Уилк: значение", float(shapiro.statistic)])
        table.add_row(["Шапиро-Уилк: значимость", float(shapiro.pvalue)])

    table.footnote(
        "Дарбин-Уотсон около 2 означает отсутствие автокорреляции остатков; "
        "значения ниже 1 или выше 3 говорят о проблеме."
    )
    table.footnote(
        "Значимость Шапиро-Уилка больше 0.05 означает, что остатки не отличаются "
        "от нормального распределения - это условие применимости регрессии."
    )
    return table


def _logistic_model_table(fit: LogisticFit, dependent_name: str) -> Table:
    table = Table(
        title=f"Сводка по модели: {dependent_name}",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", decimals=3),
        ],
    )
    table.add_row(["Событие", f"{fit.event_value} (против {fit.non_event_value})"])
    table.add_row(["Событий / не событий", f"{fit.n_events} / {fit.n_non_events}"])
    table.add_row(["Число наблюдений", float(fit.n)])
    table.add_row(["-2 логарифм правдоподобия", fit.deviance])
    table.add_row(["Логарифм правдоподобия", fit.log_likelihood])
    table.add_row(["AIC", fit.aic])
    table.add_row(["BIC", fit.bic])
    table.add_row(["Псевдо-R-квадрат (Кокс-Снелл)", fit.pseudo_r2_cox])
    table.add_row(["Псевдо-R-квадрат (Найджелкерк)", fit.pseudo_r2_nagelkerke])
    table.add_row(["Доля верных предсказаний", fit.accuracy])
    table.add_row(["Чувствительность", fit.sensitivity])
    table.add_row(["Специфичность", fit.specificity])
    if not fit.converged:
        table.footnote(
            f"ВНИМАНИЕ: решение не сошлось за {fit.iterations} итераций - "
            "результатам доверять нельзя."
        )
    table.footnote(
        "Псевдо-R-квадрат не равен обычному R-квадрату и служит лишь грубым "
        "ориентиром качества модели."
    )
    return table


def _logistic_coefficients_table(fit: LogisticFit, confidence: float) -> Table:
    table = Table(
        title="Коэффициенты и отношения шансов",
        columns=[
            Column("", align="left", is_metric=False),
            Column("B", decimals=3),
            Column("Стд. ошибка", decimals=3),
            Column("Вальд", decimals=3),
            Column("ст. св.", decimals=0),
            Column("знач.", decimals=3),
            Column("Отношение шансов", decimals=3),
            Column("Нижняя граница ОШ", decimals=3),
            Column("Верхняя граница ОШ", decimals=3),
        ],
    )
    for index, name in enumerate(fit.names):
        table.add_row(
            [
                name,
                float(fit.coefficients[index]),
                float(fit.std_errors[index]),
                float(fit.wald[index]),
                1.0,
                float(fit.p_values[index]),
                float(fit.odds_ratios[index]),
                float(fit.odds_low[index]),
                float(fit.odds_high[index]),
            ]
        )
    table.footnote(
        "B - логарифм отношения шансов. Отношение шансов больше 1 означает рост "
        "вероятности события при увеличении предиктора."
    )
    table.footnote(
        "Если предиктор измеряется в крупных единицах (например, рубли), "
        "отношение шансов на единицу может быть почти равно 1 - это не значит, "
        "что эффекта нет."
    )
    table.footnote(f"Доверительные интервалы: {confidence * 100:.1f}%.")
    return table


# ---------------------------------------------------------------------------
# Процедуры
# ---------------------------------------------------------------------------


def run_linear(command: LinearRegressionCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    dependent_name = dataset.var(command.dependent).display_name

    complete, total, excluded = _clean_frame(dataset, command.dependent, command.predictors)
    if total:
        result.add_table(_cases_table(total, len(complete), excluded))

    if len(complete) < 3:
        result.warn("Слишком мало полных наблюдений для регрессии")
        return result

    try:
        fit = fit_linear(
            complete,
            command.dependent,
            command.predictors,
            command.confidence,
            with_constant=command.constant,
        )
    except ValueError as exc:
        result.warn(str(exc))
        return result

    if fit.condition_index > 30:
        result.warn(
            f"Число обусловленности {fit.condition_index:.1f} велико - "
            "возможна мультиколлинеарность"
        )
    for name, value in fit.vif.items():
        if math.isinf(value):
            result.warn(f"{name}: полная коллинеарность с другими предикторами (VIF бесконечен)")
        elif math.isfinite(value) and value > 10:
            result.warn(f"{name}: VIF = {value:.1f} - предикторы дублируют друг друга")

    result.add_table(_model_summary_table(fit, dependent_name))
    result.add_table(_anova_regression_table(fit))
    result.add_table(_coefficients_table(fit, command.confidence, command.standardize))
    if command.diagnostics:
        result.add_table(_collinearity_table(fit))
        result.add_table(_residuals_table(fit))

    result.note(
        f"{dependent_name}: R-квадрат = {fit.r_squared:.3f}, "
        f"F = {fit.f_value:.3f}, p = {fit.f_p_value:.3f}"
    )

    # Вывод «простыми словами»: что объясняет модель, какие предикторы значимы и
    # чего в этом результате опасаться.
    predictors: list[tuple[str, float, float]] = []
    for index, name in enumerate(fit.names):
        # Константа - не предиктор: в списке значимых признаков ей не место.
        # Имя приходит из таблицы коэффициентов и выглядит как «(Константа)»,
        # поэтому проверяется и оно, и позиция.
        plain = name.strip().strip("()").strip().lower()
        if index == 0 and plain in ("константа", "constant"):
            continue
        if plain in ("константа", "constant"):
            continue
        label = dataset.var(name).label or name if name in dataset.variables else name
        predictors.append(
            (label, float(fit.coefficients[index]), float(fit.p_values[index]))
        )
    duplicated = [
        name
        for name, value in fit.vif.items()
        if math.isfinite(value) and value > 10
    ]
    result.add_findings(
        interpretation.linear_model(
            outcome=dataset.var(command.dependent).label or command.dependent,
            n=fit.n,
            r_squared=float(fit.r_squared),
            adj_r_squared=float(fit.adj_r_squared),
            f_value=float(fit.f_value),
            df_regression=float(fit.df_regression),
            df_residual=float(fit.df_residual),
            p_value=float(fit.f_p_value),
            predictors=predictors,
            durbin_watson=float(fit.durbin_watson),
            duplicated=duplicated,
        )
    )
    return result


def _cases_table(total: int, included: int, excluded: int) -> Table:
    table = Table(
        title="Сводка по обработке наблюдений",
        columns=[
            Column("", align="left", is_metric=False),
            Column("N", decimals=0),
        ],
        footnotes=[
            "Регрессия использует только наблюдения без пропусков: одно "
            "пропущенное значение исключает весь кейс."
        ],
    )
    table.add_row(["Всего кейсов", total])
    table.add_row(["Включено в анализ", included])
    table.add_row(["Исключено (пропуски)", excluded])
    return table


def run_logistic(command: LogisticRegressionCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    dependent_name = dataset.var(command.dependent).display_name

    # Определяем, какое значение считать событием: указанное пользователем или
    # наибольшее из двух (привычное соглашение «1 = событие»).
    series = dataset.categorical_series(command.dependent).dropna()
    unique = sorted(set(series.tolist()), key=lambda value: str(value))
    event_value = command.reference_value if command.reference_value is not None else unique[-1]

    complete, total, excluded = _clean_frame(dataset, command.dependent, command.predictors)
    if total:
        result.add_table(_cases_table(total, len(complete), excluded))
    if len(complete) < 3:
        result.warn("Слишком мало полных наблюдений для логистической регрессии")
        return result

    try:
        fit = fit_logistic(
            complete,
            command.dependent,
            command.predictors,
            command.confidence,
            event_value=event_value,
            max_iterations=command.max_iterations,
            tolerance=command.tolerance,
        )
    except ValueError as exc:
        result.warn(str(exc))
        return result

    if not fit.converged:
        result.warn(
            "Решение не сошлось: возможно, предиктор полностью разделяет группы. "
            "Уберите такой предиктор или увеличьте число итераций."
        )
    if fit.accuracy < 0.6:
        result.warn(
            f"Модель верно предсказывает лишь {fit.accuracy * 100:.1f}% случаев - "
            "качество низкое"
        )

    result.add_table(_logistic_model_table(fit, dependent_name))
    result.add_table(_logistic_coefficients_table(fit, command.confidence))
    result.note(
        f"{dependent_name}: доля верных предсказаний {fit.accuracy * 100:.1f}%, "
        f"псевдо-R-квадрат (Найджелкерк) {fit.pseudo_r2_nagelkerke:.3f}"
    )

    # Вывод «простыми словами»: отношения шансов переводятся на человеческий
    # язык, потому что «Exp(B) = 2,41» начинающему ничего не говорит.
    event_label = str(fit.event_value)
    if command.dependent in dataset.variables:
        variable = dataset.var(command.dependent)
        if fit.event_value in variable.value_labels:
            event_label = variable.value_labels[fit.event_value]
    logistic_predictors: list[tuple[str, float, float]] = []
    for index, name in enumerate(fit.names):
        plain = name.strip().strip("()").strip().lower()
        if plain in ("константа", "constant"):
            continue
        label = dataset.var(name).label or name if name in dataset.variables else name
        logistic_predictors.append(
            (label, float(fit.odds_ratios[index]), float(fit.p_values[index]))
        )
    result.add_findings(
        interpretation.logistic_model(
            outcome=dataset.var(command.dependent).label or command.dependent,
            event=event_label,
            n=fit.n,
            pseudo_r_squared=float(fit.pseudo_r2_nagelkerke),
            accuracy=float(fit.accuracy),
            predictors=logistic_predictors,
            converged=bool(fit.converged),
        )
    )
    return result


__all__ = [
    "LinearFit",
    "LogisticFit",
    "fit_linear",
    "fit_logistic",
    "run_linear",
    "run_logistic",
]
