"""Research Stress Test для линейной регрессии.

Проверяет, насколько результат зависит от наблюдений, предпосылок, спецификации
и случайной выборки. Все альтернативы считаются заново на копиях данных;
исходный набор не меняется.

ИИ здесь не нужен: отчёт строится из чисел. Модуль не знает про HTTP.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from winnow.analysis.diagnostics import (
    breusch_pagan,
    design_matrix,
    influence_measures,
    robust_covariance,
    white_test,
)
from winnow.core.dataset import Dataset
from winnow.stats.regression import LinearFit, fit_linear
from winnow.stats.result import Column, Finding, Result, Table

#: Доступные проверки для режима «выбрать вручную».
CHECKS = (
    "diagnostics",
    "influence",
    "robust",
    "specifications",
    "sensitivity",
    "bootstrap",
)

DEFAULT_BOOTSTRAP = 500
MAX_BOOTSTRAP = 2000
DEFAULT_SEED = 42
#: Порог Кука для «влиятельных» наблюдений; тот же, что в Quality Inspector.
COOKS_FACTOR = 4.0
#: Сколько наблюдений максимум исключать в сценарии влияния.
MAX_DROP_SHARE = 0.05


@dataclass(frozen=True)
class StressConfig:
    """Параметры прогона. Сохраняются вместе с результатом."""

    target: str
    predictors: tuple[str, ...]
    checks: tuple[str, ...] = CHECKS
    bootstrap: int = DEFAULT_BOOTSTRAP
    seed: int = DEFAULT_SEED
    confidence: float = 0.95
    alpha: float = 0.05
    add_controls: tuple[str, ...] = ()
    auto: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "predictors": list(self.predictors),
            "checks": list(self.checks),
            "bootstrap": self.bootstrap,
            "seed": self.seed,
            "confidence": self.confidence,
            "alpha": self.alpha,
            "add_controls": list(self.add_controls),
            "auto": self.auto,
        }


@dataclass
class ModelScenario:
    """Одна модель: исходная или альтернативная."""

    id: str
    title: str
    description: str
    kind: str
    n: int
    coefficients: list[dict[str, Any]]
    r_squared: float
    adj_r_squared: float
    f_p_value: float
    notes: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "n": self.n,
            "coefficients": _safe(self.coefficients),
            "r_squared": _round(self.r_squared),
            "adj_r_squared": _round(self.adj_r_squared),
            "f_p_value": _finite(self.f_p_value),
            "notes": list(self.notes),
        }


@dataclass
class BootstrapReport:
    """Сводка Bootstrap: распределения коэффициентов, без хранения всех выборок."""

    b: int
    valid: int
    seed: int
    coefficients: dict[str, dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "b": self.b,
            "valid": self.valid,
            "seed": self.seed,
            "coefficients": {
                name: _safe(values) for name, values in self.coefficients.items()
            },
            "notes": list(self.notes),
        }


@dataclass
class StressReport:
    """Полный отчёт Research Stress Test."""

    target: str
    predictors: list[str]
    config: StressConfig
    n_cases: int
    baseline: ModelScenario
    diagnostics: dict[str, Any]
    influence: dict[str, Any] | None
    robust: dict[str, list[dict[str, Any]]]
    scenarios: list[ModelScenario]
    bootstrap: BootstrapReport | None
    overview: dict[str, Any]
    findings: list[Finding]
    methodology: dict[str, Any]
    run_id: int | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target": self.target,
            "predictors": list(self.predictors),
            "config": self.config.as_payload(),
            "n_cases": self.n_cases,
            "overview": _safe(self.overview),
            "baseline": self.baseline.as_payload(),
            "diagnostics": _safe(self.diagnostics),
            "influence": _safe(self.influence) if self.influence else None,
            "robust": _safe(self.robust),
            "scenarios": [
                _with_changes(scenario.as_payload(), self.baseline)
                for scenario in self.scenarios
            ],
            "bootstrap": self.bootstrap.as_payload() if self.bootstrap else None,
            "findings": [
                {"kind": item.kind, "text": item.text, "source": item.source}
                for item in self.findings
            ],
            "methodology": _safe(self.methodology),
        }

    def as_result(self) -> Result:
        """Таблицы для печати/выгрузки в существующий отчёт."""
        result = Result(procedure="stress_test", title="Research Stress Test")

        overview = Table(
            title="Обзор устойчивости",
            columns=[
                Column("Показатель", align="left", is_metric=False),
                Column("Значение", align="right"),
            ],
        )
        overview.add_row(["Случаев в модели", self.baseline.n])
        overview.add_row(["R² исходной модели", self.baseline.r_squared])
        overview.add_row(
            ["Сценариев", len(self.scenarios)]
        )
        overview.add_row(
            [
                "Сохранили знак",
                f"{self.overview.get('same_sign', 0)} из "
                f"{self.overview.get('sign_checked', 0)}",
            ]
        )
        overview.add_row(
            [
                "Сохранили значимость",
                f"{self.overview.get('same_significance', 0)} из "
                f"{self.overview.get('significance_checked', 0)}",
            ]
        )
        result.tables.append(overview)

        diagnostics = Table(
            title="Диагностика",
            columns=[
                Column("Проверка", align="left", is_metric=False),
                Column("Результат", align="left", is_metric=False),
            ],
        )
        diagnostics.add_row(
            ["VIF, максимум", _fmt(self.diagnostics.get("max_vif"), 2)]
        )
        diagnostics.add_row(
            [
                "Бреуш-Пеган, p",
                _fmt_p(self.diagnostics.get("breusch_pagan_p")),
            ]
        )
        diagnostics.add_row(
            ["Уайт, p", _fmt_p(self.diagnostics.get("white_p"))]
        )
        diagnostics.add_row(
            ["Дарбин-Уотсон", _fmt(self.diagnostics.get("durbin_watson"), 2)]
        )
        diagnostics.add_row(
            ["Шапиро-Уилк, p", _fmt_p(self.diagnostics.get("shapiro_p"))]
        )
        diagnostics.add_row(
            ["Кука, максимум", _fmt(self.diagnostics.get("cooks_max"), 2)]
        )
        diagnostics.add_row(
            [
                "Влиятельных наблюдений",
                str(self.diagnostics.get("influential_count", 0)),
            ]
        )
        result.tables.append(diagnostics)

        comparison = Table(
            title="Сравнение моделей",
            columns=[
                Column("Сценарий", align="left", is_metric=False),
                Column("N", decimals=0),
                Column("R²", decimals=3),
                Column("Скорр. R²", decimals=3),
                Column("Сменили знак", decimals=0),
                Column("Сменили значимость", decimals=0),
            ],
        )
        for scenario in self.scenarios:
            changes = _changes(scenario, self.baseline)
            comparison.add_row(
                [
                    scenario.title,
                    scenario.n,
                    _finite(scenario.r_squared),
                    _finite(scenario.adj_r_squared),
                    len(changes["sign"]),
                    len(changes["significance"]),
                ]
            )
        result.tables.append(comparison)

        coefficients = Table(
            title="Коэффициенты по сценариям",
            columns=[
                Column("Сценарий", align="left", is_metric=False),
                Column("Переменная", align="left", is_metric=False),
                Column("b", decimals=3),
                Column("SE", decimals=3),
                Column("p", decimals=3),
                Column(
                    f"{round(self.config.confidence * 100)} % ДИ",
                    align="left",
                    is_metric=False,
                ),
            ],
        )
        for scenario in self.scenarios:
            for item in scenario.coefficients:
                coefficients.add_row(
                    [
                        scenario.title,
                        item["name"],
                        item["b"],
                        item["se"],
                        item["p"],
                        f"[{_fmt(item['ci_low'], 3)}; {_fmt(item['ci_high'], 3)}]",
                    ]
                )
        result.tables.append(coefficients)

        if self.robust:
            robust = Table(
                title="Робастные стандартные ошибки",
                columns=[
                    Column("Тип", align="left", is_metric=False),
                    Column("Переменная", align="left", is_metric=False),
                    Column("b", decimals=3),
                    Column("SE", decimals=3),
                    Column("p", decimals=3),
                ],
            )
            for kind, rows in self.robust.items():
                for item in rows:
                    robust.add_row(
                        [kind, item["name"], item["b"], item["se"], item["p"]]
                    )
            result.tables.append(robust)

        if self.bootstrap:
            boot = Table(
                title=f"Bootstrap ({self.bootstrap.valid} из {self.bootstrap.b})",
                columns=[
                    Column("Переменная", align="left", is_metric=False),
                    Column("Среднее", decimals=3),
                    Column("SD", decimals=3),
                    Column(
                        f"{round(self.config.confidence * 100)} % ДИ",
                        align="left",
                        is_metric=False,
                    ),
                    Column("Доля знака", decimals=3),
                    Column("Доля p < 0,05", decimals=3),
                ],
            )
            for name, values in self.bootstrap.coefficients.items():
                boot.add_row(
                    [
                        name,
                        values.get("mean"),
                        values.get("sd"),
                        f"[{_fmt(values.get('ci_low'), 3)}; "
                        f"{_fmt(values.get('ci_high'), 3)}]",
                        values.get("sign_share"),
                        values.get("significance_share"),
                    ]
                )
            result.tables.append(boot)

        result.findings.extend(self.findings)
        result.warnings.extend(
            item.text for item in self.findings if item.kind == "caution"
        )
        result.notes.append(
            "Stress Test проверяет устойчивость, а не доказывает причинность. "
            "Все альтернативы посчитаны отдельно; исходные данные не изменялись."
        )
        return result


# ------------------------------------------------------------------ публичный вход


def run_stress_test(dataset: Dataset, config: StressConfig) -> StressReport:
    """Считает baseline, диагностику, альтернативы и Bootstrap."""
    target = config.target
    if not target:
        raise ValueError("Не выбрана зависимая переменная")
    if target not in dataset.names():
        raise ValueError(f"Переменной «{target}» нет в наборе")
    if not dataset.var(target).is_numeric:
        raise ValueError(f"Зависимая переменная «{target}» должна быть числовой")

    predictors = _unique_predictors(target, config.predictors)
    for name in predictors:
        if name not in dataset.names():
            raise ValueError(f"Переменной «{name}» нет в наборе")
        if not dataset.var(name).is_numeric:
            raise ValueError(f"Предиктор «{name}» должен быть числовым")

    controls = _unique_predictors(target, (*predictors, *config.add_controls))
    controls = [name for name in controls if name not in predictors]
    for name in controls:
        if name not in dataset.names():
            raise ValueError(f"Переменной «{name}» нет в наборе")
        if not dataset.var(name).is_numeric:
            raise ValueError(f"Контрольная переменная «{name}» должна быть числовой")

    frame = dataset.analysis_frame([target, *predictors]).dropna()
    if len(frame) <= len(predictors) + 2:
        raise ValueError(
            f"Слишком мало полных наблюдений: {len(frame)} на "
            f"{len(predictors)} предикторов"
        )

    checks = _resolve_checks(
        dataset, target, predictors, config.checks, config.auto
    )
    confidence = min(0.999, max(0.5, float(config.confidence)))
    alpha = min(0.5, max(0.001, float(config.alpha)))
    bootstrap_count = max(0, min(MAX_BOOTSTRAP, int(config.bootstrap)))

    baseline_fit, baseline_x = _fit(frame, target, predictors, confidence)
    baseline = _scenario(
        "baseline",
        "Исходная модель",
        "Все выбранные переменные, полные наблюдения.",
        "baseline",
        frame,
        target,
        predictors,
        confidence,
        alpha,
    )

    diagnostics = _diagnostics(baseline_fit, baseline_x, frame, alpha)
    influence = None
    if "influence" in checks or "sensitivity" in checks:
        measures = influence_measures(
            baseline_x, baseline_fit.residuals, baseline_fit.ms_residual
        )
        influence = {
            "cooks_max": _round(measures.cooks_max),
            "influential_count": measures.n_influential,
            "leverage_count": measures.n_high_leverage,
            "influential_rows": [index + 1 for index in measures.influential[:20]],
            "leverage_rows": [index + 1 for index in measures.high_leverage[:20]],
            "thresholds": {
                "cooks": f"4/n = {4.0 / len(frame):.4f}",
                "leverage": f"2p/n = {2.0 * baseline_x.shape[1] / len(frame):.4f}",
            },
        }

    robust: dict[str, list[dict[str, Any]]] = {}
    if "robust" in checks:
        robust = _robust(baseline_fit, baseline_x, confidence, alpha)

    scenarios: list[ModelScenario] = [baseline]
    if "influence" in checks:
        scenario = _drop_influential(frame, target, predictors, confidence, alpha)
        if scenario:
            scenarios.append(scenario)
    if "sensitivity" in checks or "influence" in checks:
        scenario = _drop_outliers(frame, target, predictors, confidence, alpha)
        if scenario:
            scenarios.append(scenario)
    if "specifications" in checks:
        control_frame = frame
        if controls:
            control_frame = dataset.analysis_frame(
                [target, *predictors, *controls]
            ).dropna()
        scenarios.extend(
            _specifications(
                frame,
                control_frame,
                target,
                predictors,
                controls,
                confidence,
                alpha,
            )
        )

    bootstrap = None
    if "bootstrap" in checks and bootstrap_count >= 20:
        bootstrap = _bootstrap(
            frame,
            target,
            predictors,
            bootstrap_count,
            int(config.seed),
            confidence,
            alpha,
        )

    overview = _overview(baseline, scenarios, robust, bootstrap)
    findings = _findings(
        baseline,
        scenarios,
        diagnostics,
        influence,
        robust,
        bootstrap,
        overview,
        alpha,
    )
    methodology = {
        "method": "OLS, робастные SE HC0–HC3, Bootstrap",
        "confidence": confidence,
        "alpha": alpha,
        "bootstrap": bootstrap_count,
        "seed": int(config.seed),
        "missing": "complete_case",
        "checks": list(checks),
        "thresholds": {
            "cooks": "4/n",
            "leverage": "2p/n",
            "vif_warning": 5,
            "vif_critical": 10,
            "alpha": alpha,
        },
        "limitations": [
            "Проверяется устойчивость, а не причинность.",
            "Пропуски обрабатываются попарным исключением строк (complete case).",
            "Веса случаев не используются.",
            "Робастные ошибки не исправляют неверную спецификацию модели.",
            "Bootstrap-интервалы — перцентильные, число повторов фиксировано seed.",
        ],
    }
    return StressReport(
        target=target,
        predictors=predictors,
        config=config,
        n_cases=len(frame),
        baseline=baseline,
        diagnostics=diagnostics,
        influence=influence,
        robust=robust,
        scenarios=scenarios,
        bootstrap=bootstrap,
        overview=overview,
        findings=findings,
        methodology=methodology,
    )


def suggest_checks(
    dataset: Dataset, target: str, predictors: Iterable[str]
) -> list[str]:
    """Какие проверки уместны для этих данных (для авто-режима)."""
    names = _unique_predictors(target, tuple(predictors))
    frame = dataset.analysis_frame([target, *names]).dropna()
    checks = ["diagnostics", "robust"]
    if len(frame) >= 12:
        checks.append("influence")
    if len(names) >= 2:
        checks.append("specifications")
    if len(frame) >= 30:
        checks.append("bootstrap")
    return checks


# ------------------------------------------------------------------ модели


def _fit(
    frame: pd.DataFrame, target: str, predictors: list[str], confidence: float
) -> tuple[LinearFit, np.ndarray]:
    fit = fit_linear(frame, target, predictors, confidence=confidence)
    x = design_matrix([frame[name].to_numpy(dtype=float) for name in predictors])
    return fit, x


def _scenario(
    identifier: str,
    title: str,
    description: str,
    kind: str,
    frame: pd.DataFrame,
    target: str,
    predictors: list[str],
    confidence: float,
    alpha: float,
) -> ModelScenario:
    fit, _x = _fit(frame, target, predictors, confidence)
    return ModelScenario(
        id=identifier,
        title=title,
        description=description,
        kind=kind,
        n=fit.n,
        coefficients=_coefficients(
            fit.names, fit.coefficients, fit.std_errors, fit.df_residual,
            confidence, alpha,
        ),
        r_squared=float(fit.r_squared),
        adj_r_squared=float(fit.adj_r_squared),
        f_p_value=float(fit.f_p_value),
    )


def _coefficients(
    names: list[str],
    coefficients: np.ndarray,
    std_errors: np.ndarray,
    df: float,
    confidence: float,
    alpha: float,
) -> list[dict[str, Any]]:
    critical = float(scipy_stats.t.ppf(1.0 - (1.0 - confidence) / 2.0, df))
    rows: list[dict[str, Any]] = []
    for name, value, error in zip(names, coefficients, std_errors):
        value = float(value)
        error = float(error)
        with np.errstate(divide="ignore", invalid="ignore"):
            t_value = value / error if error > 0 else float("nan")
        p_value = (
            float(2.0 * scipy_stats.t.sf(abs(t_value), df))
            if math.isfinite(t_value)
            else float("nan")
        )
        rows.append(
            {
                "name": name,
                "b": value,
                "se": error,
                "t": t_value,
                "p": p_value,
                "ci_low": value - critical * error,
                "ci_high": value + critical * error,
                "significant": bool(p_value < alpha) if math.isfinite(p_value) else False,
                "direction": _direction(value),
            }
        )
    return rows


def _diagnostics(
    fit: LinearFit, x: np.ndarray, frame: pd.DataFrame, alpha: float
) -> dict[str, Any]:
    bp = breusch_pagan(fit.residuals, x)
    white = white_test(fit.residuals, x)
    normality = None
    if 8 <= fit.n <= 5000:
        try:
            normality = float(scipy_stats.shapiro(fit.residuals).pvalue)
        except (ValueError, TypeError):
            normality = None
    return {
        "vif": {name: _round(value) for name, value in fit.vif.items()},
        "max_vif": _round(max(fit.vif.values(), default=0.0)),
        "breusch_pagan_p": _finite(bp.p_value),
        "breusch_pagan_lm": _finite(bp.statistic),
        "white_p": _finite(white.p_value),
        "white_lm": _finite(white.statistic),
        "durbin_watson": _round(fit.durbin_watson),
        "shapiro_p": _finite(normality),
        "condition_index": _round(fit.condition_index),
        "r_squared": _round(fit.r_squared),
        "adj_r_squared": _round(fit.adj_r_squared),
        "n": int(fit.n),
        "df_residual": _round(fit.df_residual),
        "alpha": alpha,
    }


def _robust(
    fit: LinearFit, x: np.ndarray, confidence: float, alpha: float
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for kind in ("HC0", "HC1", "HC2", "HC3"):
        covariance = robust_covariance(x, fit.residuals, kind)
        errors = np.sqrt(np.diag(covariance))
        result[kind] = _coefficients(
            fit.names, fit.coefficients, errors, fit.df_residual, confidence, alpha
        )
    return result


def _drop_influential(
    frame: pd.DataFrame,
    target: str,
    predictors: list[str],
    confidence: float,
    alpha: float,
) -> ModelScenario | None:
    fit, x = _fit(frame, target, predictors, confidence)
    measures = influence_measures(x, fit.residuals, fit.ms_residual)
    if not measures.influential:
        return None
    limit = max(1, int(len(frame) * MAX_DROP_SHARE))
    order = np.argsort(measures.cooks)[::-1]
    drop = sorted(int(index) for index in order[:limit] if int(index) in measures.influential)
    if not drop:
        drop = [int(order[0])]
    reduced = frame.drop(frame.index[drop]).reset_index(drop=True)
    if len(reduced) <= len(predictors) + 2:
        return None
    scenario = _scenario(
        "drop_influential",
        f"Без влиятельных наблюдений ({len(drop)})",
        "Исключены точки с наибольшим расстоянием Кука.",
        "influence",
        reduced,
        target,
        predictors,
        confidence,
        alpha,
    )
    scenario.notes.append(
        "Исключение точек — диагностический сценарий, а не рекомендация удалять данные."
    )
    scenario.notes.append("Строки: " + ", ".join(str(index + 1) for index in drop))
    return scenario


def _drop_outliers(
    frame: pd.DataFrame,
    target: str,
    predictors: list[str],
    confidence: float,
    alpha: float,
) -> ModelScenario | None:
    mask = pd.Series(False, index=frame.index)
    for name in predictors:
        series = frame[name]
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        mask |= (series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)
    if not bool(mask.any()):
        return None
    reduced = frame.loc[~mask].reset_index(drop=True)
    if len(reduced) <= len(predictors) + 2:
        return None
    scenario = _scenario(
        "drop_outliers",
        f"Без выбросов по предикторам ({int(mask.sum())})",
        "Исключены строки, где хотя бы один предиктор вне 1.5 IQR.",
        "sensitivity",
        reduced,
        target,
        predictors,
        confidence,
        alpha,
    )
    scenario.notes.append(
        "Выбросы определяются только по предикторам, без использования зависимой переменной."
    )
    return scenario


def _specifications(
    frame: pd.DataFrame,
    control_frame: pd.DataFrame,
    target: str,
    predictors: list[str],
    controls: list[str],
    confidence: float,
    alpha: float,
) -> list[ModelScenario]:
    scenarios: list[ModelScenario] = []
    if len(predictors) >= 2:
        for name in predictors:
            remaining = [item for item in predictors if item != name]
            try:
                scenario = _scenario(
                    f"drop_{name}",
                    f"Без предиктора «{name}»",
                    "Проверка чувствительности к составу переменных.",
                    "specification",
                    frame,
                    target,
                    remaining,
                    confidence,
                    alpha,
                )
            except (ValueError, np.linalg.LinAlgError):
                continue
            scenario.notes.append(
                f"Удалён предиктор «{name}»; модель пересчитана заново."
            )
            scenarios.append(scenario)

    if controls:
        all_predictors = [*predictors, *controls]
        try:
            scenario = _scenario(
                "add_controls",
                "С контрольными переменными",
                "Добавлены: " + ", ".join(controls),
                "specification",
                control_frame,
                target,
                all_predictors,
                confidence,
                alpha,
            )
        except (ValueError, np.linalg.LinAlgError):
            return scenarios
        scenario.notes.append(
            "Добавлены контрольные переменные: " + ", ".join(controls)
        )
        scenarios.append(scenario)
    return scenarios


def _bootstrap(
    frame: pd.DataFrame,
    target: str,
    predictors: list[str],
    count: int,
    seed: int,
    confidence: float,
    alpha: float,
) -> BootstrapReport:
    rng = np.random.default_rng(seed)
    n = len(frame)
    samples: dict[str, list[float]] = {}
    p_values: dict[str, list[float]] = {}
    valid = 0
    for _ in range(count):
        indices = rng.integers(0, n, n)
        sample = frame.iloc[indices]
        try:
            fit, _ = _fit(sample, target, predictors, confidence)
        except (ValueError, np.linalg.LinAlgError):
            continue
        valid += 1
        for name, value, p_value in zip(fit.names, fit.coefficients, fit.p_values):
            samples.setdefault(name, []).append(float(value))
            p_values.setdefault(name, []).append(float(p_value))

    coefficients: dict[str, dict[str, Any]] = {}
    for name, values in samples.items():
        array = np.asarray(values, dtype=float)
        if len(array) < 2:
            continue
        lo, hi = np.percentile(array, [2.5, 97.5])
        positive = float((array > 0).mean())
        p_array = np.asarray(p_values.get(name, []), dtype=float)
        significance_share = (
            float((p_array < alpha).mean()) if len(p_array) else float("nan")
        )
        hist, edges = np.histogram(array, bins=20)
        coefficients[name] = {
            "mean": _round(float(np.mean(array))),
            "sd": _round(float(np.std(array, ddof=1))),
            "ci_low": _round(float(lo)),
            "ci_high": _round(float(hi)),
            "sign_share": _round(max(positive, 1.0 - positive)),
            "significance_share": _round(significance_share),
            "histogram": {
                "counts": [int(value) for value in hist],
                "edges": [_round(float(value)) for value in edges],
            },
            "n": int(len(array)),
        }

    notes: list[str] = []
    if valid < count:
        notes.append(
            f"Часть повторных выборок не оценилась: {valid} из {count}. "
            "Обычно это коллинеарность в конкретной выборке."
        )
    return BootstrapReport(
        b=count,
        valid=valid,
        seed=seed,
        coefficients=coefficients,
        notes=notes,
    )


def _resolve_checks(
    dataset: Dataset,
    target: str,
    predictors: list[str],
    requested: tuple[str, ...],
    auto: bool,
) -> list[str]:
    if auto:
        return suggest_checks(dataset, target, predictors)
    checks = [name for name in requested if name in CHECKS]
    return checks or ["diagnostics"]


# ------------------------------------------------------------------ сравнение


def _changes(scenario: ModelScenario, baseline: ModelScenario) -> dict[str, list[str]]:
    if scenario.id == baseline.id:
        return {"sign": [], "significance": [], "missing": []}
    baseline_map = {item["name"]: item for item in baseline.coefficients}
    current_map = {item["name"]: item for item in scenario.coefficients}
    sign: list[str] = []
    significance: list[str] = []
    missing: list[str] = []
    for name, base in baseline_map.items():
        if name not in current_map:
            missing.append(name)
            continue
        current = current_map[name]
        if name == "(Константа)":
            continue
        if base["direction"] != current["direction"] and "zero" not in {
            base["direction"],
            current["direction"],
        }:
            sign.append(name)
        if base["significant"] != current["significant"]:
            significance.append(name)
    return {"sign": sign, "significance": significance, "missing": missing}


def _with_changes(payload: dict[str, Any], baseline: ModelScenario) -> dict[str, Any]:
    # Собираем временный объект без изменения исходного отчёта.
    scenario = ModelScenario(
        id=payload["id"],
        title=payload["title"],
        description=payload["description"],
        kind=payload["kind"],
        n=payload["n"],
        coefficients=payload["coefficients"],
        r_squared=payload["r_squared"],
        adj_r_squared=payload["adj_r_squared"],
        f_p_value=payload["f_p_value"],
        notes=payload["notes"],
    )
    payload = dict(payload)
    payload["changes"] = _changes(scenario, baseline)
    return payload


def _overview(
    baseline: ModelScenario,
    scenarios: list[ModelScenario],
    robust: dict[str, list[dict[str, Any]]],
    bootstrap: BootstrapReport | None,
) -> dict[str, Any]:
    base = {item["name"]: item for item in baseline.coefficients}
    sign_checked = 0
    same_sign = 0
    significance_checked = 0
    same_significance = 0
    for scenario in scenarios:
        if scenario.id == baseline.id:
            continue
        for item in scenario.coefficients:
            if item["name"] == "(Константа)" or item["name"] not in base:
                continue
            origin = base[item["name"]]
            if origin["direction"] != "zero" and item["direction"] != "zero":
                sign_checked += 1
                same_sign += int(origin["direction"] == item["direction"])
            significance_checked += 1
            same_significance += int(origin["significant"] == item["significant"])

    robust_changes = 0
    robust_checked = 0
    hc3 = robust.get("HC3", [])
    base_map = {item["name"]: item for item in baseline.coefficients}
    for item in hc3:
        origin = base_map.get(item["name"])
        if origin is None or item["name"] == "(Константа)":
            continue
        robust_checked += 1
        robust_changes += int(origin["significant"] != item["significant"])

    bootstrap_unstable = []
    if bootstrap:
        for name, values in bootstrap.coefficients.items():
            if name == "(Константа)":
                continue
            if values.get("sign_share", 1.0) < 0.95:
                bootstrap_unstable.append(name)

    return {
        "n": baseline.n,
        "r_squared": baseline.r_squared,
        "scenarios": len(scenarios),
        "sign_checked": sign_checked,
        "same_sign": same_sign,
        "significance_checked": significance_checked,
        "same_significance": same_significance,
        "robust_checked": robust_checked,
        "robust_changes": robust_changes,
        "bootstrap_unstable": bootstrap_unstable,
    }


# ------------------------------------------------------------------ выводы


def _findings(
    baseline: ModelScenario,
    scenarios: list[ModelScenario],
    diagnostics: dict[str, Any],
    influence: dict[str, Any] | None,
    robust: dict[str, list[dict[str, Any]]],
    bootstrap: BootstrapReport | None,
    overview: dict[str, Any],
    alpha: float,
) -> list[Finding]:
    findings: list[Finding] = []

    if overview["sign_checked"]:
        changed = overview["sign_checked"] - overview["same_sign"]
        if changed:
            findings.append(
                Finding(
                    kind="caution",
                    text=(
                        f"Знак коэффициента изменился в {changed} "
                        f"{_plural(changed, 'случае', 'случаях', 'случаях')} из "
                        f"{overview['sign_checked']}. Вывод о направлении связи "
                        "неустойчив."
                    ),
                    source="STRESS",
                )
            )
    if overview["significance_checked"]:
        changed = overview["significance_checked"] - overview["same_significance"]
        if changed:
            findings.append(
                Finding(
                    kind="caution",
                    text=(
                        f"Статистическая значимость изменилась в {changed} "
                        f"{_plural(changed, 'случае', 'случаях', 'случаях')} из "
                        f"{overview['significance_checked']}. Не считайте исходный "
                        "p-value окончательным."
                    ),
                    source="STRESS",
                )
            )

    if overview["robust_checked"] and overview["robust_changes"]:
        findings.append(
            Finding(
                kind="caution",
                text=(
                    f"С робастными ошибками HC3 значимость изменилась у "
                    f"{overview['robust_changes']} "
                    f"{_plural(overview['robust_changes'], 'коэффициента', 'коэффициентов', 'коэффициентов')} из "
                    f"{overview['robust_checked']}. Проверьте гетероскедастичность."
                ),
                source="STRESS",
            )
        )

    if diagnostics.get("max_vif", 0) >= 10:
        findings.append(
            Finding(
                kind="caution",
                text=f"Мультиколлинеарность: максимальный VIF = {diagnostics['max_vif']:.2f}.",
                source="STRESS",
            )
        )
    bp_p = diagnostics.get("breusch_pagan_p")
    if bp_p is not None and bp_p < alpha:
        findings.append(
            Finding(
                kind="caution",
                text=(
                    "Бреуш-Пеган указывает на гетероскедастичность "
                    f"(p = {bp_p:.3f}); обычные SE могут быть неверны."
                ),
                source="STRESS",
            )
        )
    white_p = diagnostics.get("white_p")
    if white_p is not None and white_p < alpha:
        findings.append(
            Finding(
                kind="note",
                text=(
                    "Уайт также обнаружил связь дисперсии остатков с предикторами "
                    f"(p = {white_p:.3f})."
                ),
                source="STRESS",
            )
        )

    if influence and influence.get("influential_count"):
        findings.append(
            Finding(
                kind="caution",
                text=(
                    f"Влиятельных наблюдений: {influence['influential_count']}. "
                    "Сценарий без них показывает, насколько модель зависит от отдельных строк."
                ),
                source="STRESS",
            )
        )

    if bootstrap:
        unstable = overview.get("bootstrap_unstable", [])
        if unstable:
            findings.append(
                Finding(
                    kind="caution",
                    text=(
                        "Bootstrap: знак нестабилен у коэффициентов "
                        + ", ".join(unstable[:5])
                        + ". Доверительные интервалы шире, чем кажется по одной модели."
                    ),
                    source="STRESS",
                )
            )
        if bootstrap.valid < bootstrap.b:
            findings.append(
                Finding(
                    kind="note",
                    text=bootstrap.notes[0] if bootstrap.notes else "Часть bootstrap-выборок не оценилась.",
                    source="STRESS",
                )
            )

    drop_influential = next(
        (item for item in scenarios if item.id == "drop_influential"), None
    )
    if drop_influential:
        changes = _changes(drop_influential, baseline)
        if changes["sign"] or changes["significance"]:
            findings.append(
                Finding(
                    kind="caution",
                    text=(
                        "После исключения влиятельных наблюдений изменились: "
                        + ", ".join(sorted(set(changes["sign"] + changes["significance"])))
                        + "."
                    ),
                    source="STRESS",
                )
            )

    if not findings:
        findings.append(
            Finding(
                kind="conclusion",
                text=(
                    "Проверка не нашла резких изменений: знаки и значимость "
                    "основных коэффициентов устойчивы в рассмотренных сценариях."
                ),
                source="STRESS",
            )
        )
    return findings


# ------------------------------------------------------------------ утилиты


def _unique_predictors(target: str, names: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for name in names:
        name = str(name)
        if name and name != target and name not in unique:
            unique.append(name)
    return unique


def _direction(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def _plural(number: int, one: str, few: str, many: str) -> str:
    """Русское согласование числительного с существительным."""
    count = abs(int(number))
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 4) if math.isfinite(number) else None


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _fmt(value: Any, digits: int) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.{digits}f}".replace(".", ",") if math.isfinite(number) else "—"


def _fmt_p(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    if number < 0.001:
        return "< 0,001"
    return f"{number:.3f}".replace(".", ",")


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return _finite(float(value))
    if isinstance(value, np.ndarray):
        return [_safe(item) for item in value.tolist()]
    return value


__all__ = [
    "CHECKS",
    "DEFAULT_BOOTSTRAP",
    "DEFAULT_SEED",
    "MAX_BOOTSTRAP",
    "BootstrapReport",
    "ModelScenario",
    "StressConfig",
    "StressReport",
    "run_stress_test",
    "suggest_checks",
]
