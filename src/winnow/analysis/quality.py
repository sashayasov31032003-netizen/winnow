"""Проверка качества данных и моделей.

Зачем это отдельным модулем. Статистическая процедура честно считает то, что
её попросили, но не отвечает на вопрос «а можно ли этим числам верить». Пропуски,
дубликаты, выбросы, мультиколлинеарность и гетероскедастичность ломают выводы
раньше, чем человек успевает их прочитать. Инспектор проходит по данным и
модели и говорит, где именно проблема.

Три правила:

* **всё считается, а не угадывается.** Каждое предупреждение содержит число,
  по которому его можно проверить;
* **нет автоматических исправлений.** Инспектор ничего не удаляет и не меняет:
  решение остаётся за человеком;
* **уровни важности.** `critical` — анализ даст неверный вывод; `warning` —
  вывод возможен, но с оговоркой; `note` — стоит посмотреть.

Модуль не знает про HTTP и ИИ: на входе набор, на выходе структура. Поэтому его
можно проверить тестами как обычный расчёт.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from winnow.analysis.diagnostics import breusch_pagan
from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, VarType
from winnow.stats.profile import DatasetProfile, profile_dataset
from winnow.stats.regression import fit_linear
from winnow.stats.result import Column, Finding, Result, Table

#: Порог, после которого пропуски считаются серьёзными.
HIGH_MISSING = 0.30
MODERATE_MISSING = 0.10
#: Доля выбросов, после которой переменная требует решения.
HIGH_OUTLIERS = 0.05
#: Порог «почти дублирующие» переменные.
STRONG_CORRELATION = 0.98
NOTABLE_CORRELATION = 0.90
#: Минимальная доля самой маленькой группы.
MIN_GROUP_SHARE = 0.05
#: Сколько переменных максимум брать в многомерную проверку.
MAX_MULTIVARIATE = 10


@dataclass(frozen=True)
class QualityIssue:
    """Одна найденная проблема."""

    code: str
    severity: str  # critical | warning | note
    title: str
    details: str
    variables: tuple[str, ...] = ()
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def is_serious(self) -> bool:
        return self.severity in {"critical", "warning"}

    def as_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "details": self.details,
            "variables": list(self.variables),
            "values": _json_safe(self.values),
        }


@dataclass(frozen=True)
class VariableQuality:
    """Что видно про одну переменную."""

    name: str
    label: str
    role: str
    type: str
    measure: str
    n: int
    n_missing: int
    missing_share: float
    n_unique: int
    n_outliers: int
    outlier_share: float
    skewness: float | None
    is_normal: bool | None
    is_identifier: bool
    is_constant: bool
    is_binary: bool

    def as_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "role": self.role,
            "type": self.type,
            "measure": self.measure,
            "n": self.n,
            "n_missing": self.n_missing,
            "missing_share": _round(self.missing_share),
            "n_unique": self.n_unique,
            "n_outliers": self.n_outliers,
            "outlier_share": _round(self.outlier_share),
            "skewness": _finite(self.skewness),
            "is_normal": self.is_normal,
            "is_identifier": self.is_identifier,
            "is_constant": self.is_constant,
            "is_binary": self.is_binary,
        }


@dataclass(frozen=True)
class RegressionQuality:
    """Диагностика линейной модели: то, что нельзя увидеть в таблице коэффициентов."""

    target: str
    predictors: tuple[str, ...]
    n: int
    n_predictors: int
    r_squared: float
    adj_r_squared: float
    max_vif: float
    vif: dict[str, float]
    breusch_pagan_p: float | None
    breusch_pagan_lm: float | None
    durbin_watson: float
    cooks_max: float
    influential_count: int
    leverage_count: int
    residual_normality_p: float | None
    condition_index: float
    n_per_predictor: float

    def as_payload(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "predictors": list(self.predictors),
            "n": self.n,
            "n_predictors": self.n_predictors,
            "r_squared": _round(self.r_squared),
            "adj_r_squared": _round(self.adj_r_squared),
            "max_vif": _round(self.max_vif),
            "vif": {name: _round(value) for name, value in self.vif.items()},
            "breusch_pagan_p": _finite(self.breusch_pagan_p),
            "breusch_pagan_lm": _finite(self.breusch_pagan_lm),
            "durbin_watson": _round(self.durbin_watson),
            "cooks_max": _round(self.cooks_max),
            "influential_count": self.influential_count,
            "leverage_count": self.leverage_count,
            "residual_normality_p": _finite(self.residual_normality_p),
            "condition_index": _round(self.condition_index),
            "n_per_predictor": _round(self.n_per_predictor),
        }


@dataclass
class QualityReport:
    """Полный отчёт инспектора."""

    n_cases: int
    n_variables: int
    complete_rows: int
    missing_cells: int
    missing_share: float
    duplicate_rows: int
    duplicate_share: float
    variables: list[VariableQuality] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    correlated: list[dict[str, Any]] = field(default_factory=list)
    regression: RegressionQuality | None = None
    target: str | None = None
    predictors: list[str] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(issue.severity == "critical" for issue in self.issues)

    @property
    def counts(self) -> dict[str, int]:
        result = {"critical": 0, "warning": 0, "note": 0}
        for issue in self.issues:
            result[issue.severity] = result.get(issue.severity, 0) + 1
        return result

    def as_payload(self) -> dict[str, Any]:
        return {
            "n_cases": self.n_cases,
            "n_variables": self.n_variables,
            "complete_rows": self.complete_rows,
            "missing_cells": self.missing_cells,
            "missing_share": _round(self.missing_share),
            "duplicate_rows": self.duplicate_rows,
            "duplicate_share": _round(self.duplicate_share),
            "counts": self.counts,
            "variables": [variable.as_payload() for variable in self.variables],
            "issues": [issue.as_payload() for issue in self.issues],
            "correlated": [
                {
                    "a": pair["a"],
                    "b": pair["b"],
                    "r": _round(float(pair["r"])),
                }
                for pair in self.correlated
            ],
            "regression": self.regression.as_payload() if self.regression else None,
            "target": self.target,
            "predictors": list(self.predictors),
        }

    def as_result(self) -> Result:
        """Тот же отчёт в виде таблиц — для интерфейса и выгрузки."""
        result = Result(
            procedure="quality",
            title="Проверка качества данных",
        )

        summary = Table(
            title="Сводка",
            columns=[
                Column("Показатель", align="left", is_metric=False),
                Column("Значение", align="right"),
            ],
        )
        summary.add_row(["Случаев", self.n_cases])
        summary.add_row(["Переменных", self.n_variables])
        summary.add_row(["Полных строк", self.complete_rows])
        summary.add_row(["Пропущенных ячеек", self.missing_cells])
        summary.add_row(["Доля пропусков, %", round(self.missing_share * 100, 1)])
        summary.add_row(["Дублей строк", self.duplicate_rows])
        summary.add_row(["Доля дублей, %", round(self.duplicate_share * 100, 1)])
        result.tables.append(summary)

        if self.issues:
            issues = Table(
                title="Найденные проблемы",
                columns=[
                    Column("Уровень", align="left", is_metric=False),
                    Column("Что", align="left", is_metric=False),
                    Column("Переменные", align="left", is_metric=False),
                    Column("Подробности", align="left", is_metric=False),
                ],
            )
            for issue in self.issues:
                issues.add_row(
                    [
                        _severity_ru(issue.severity),
                        issue.title,
                        ", ".join(issue.variables) if issue.variables else "—",
                        issue.details,
                    ]
                )
            result.tables.append(issues)

        if self.variables:
            variables = Table(
                title="Переменные",
                columns=[
                    Column("Переменная", align="left", is_metric=False),
                    Column("Роль", align="left", is_metric=False),
                    Column("N", decimals=0),
                    Column("Пропуски, %", decimals=1),
                    Column("Выбросы", decimals=0),
                    Column("Асимметрия", decimals=2),
                ],
            )
            for variable in self.variables:
                variables.add_row(
                    [
                        variable.label or variable.name,
                        variable.role,
                        variable.n,
                        round(variable.missing_share * 100, 1),
                        variable.n_outliers,
                        _finite(variable.skewness),
                    ]
                )
            result.tables.append(variables)

        if self.regression:
            model = Table(
                title="Диагностика модели",
                columns=[
                    Column("Показатель", align="left", is_metric=False),
                    Column("Значение", align="right"),
                ],
            )
            regression = self.regression
            model.add_row(["Зависимая переменная", regression.target])
            model.add_row(["Предикторов", regression.n_predictors])
            model.add_row(["Случаев в модели", regression.n])
            model.add_row(["R²", round(regression.r_squared, 3)])
            model.add_row(["Скорректированный R²", round(regression.adj_r_squared, 3)])
            model.add_row(["Максимальный VIF", round(regression.max_vif, 2)])
            model.add_row(["Дарбин-Уотсон", round(regression.durbin_watson, 2)])
            if regression.breusch_pagan_p is not None:
                model.add_row(
                    ["Бреуш-Пеган, p", round(regression.breusch_pagan_p, 3)]
                )
            if regression.residual_normality_p is not None:
                model.add_row(
                    ["Нормальность остатков, p", round(regression.residual_normality_p, 3)]
                )
            model.add_row(["Максимум Кука", round(regression.cooks_max, 3)])
            model.add_row(["Влиятельных наблюдений", regression.influential_count])
            model.add_row(["Наблюдений с рычагом", regression.leverage_count])
            result.tables.append(model)

        if not self.issues:
            result.findings.append(
                Finding(
                    kind="conclusion",
                    text=(
                        "Проверка не нашла критических проблем: пропуски и дубли "
                        "в допустимых пределах, явных выбросов и дисбаланса нет."
                    ),
                    source="QUALITY",
                )
            )
        else:
            for issue in self.issues:
                result.findings.append(
                    Finding(
                        kind="caution" if issue.is_serious else "note",
                        text=f"{issue.title}: {issue.details}",
                        source="QUALITY",
                    )
                )

        serious = [issue.details for issue in self.issues if issue.is_serious]
        result.warnings.extend(serious)
        result.notes.append(
            "Инспектор ничего не исправляет: решения об удалении строк, "
            "перекодировании и выборе модели принимает человек."
        )
        return result


# ------------------------------------------------------------------ расчёт


def quality_report(
    dataset: Dataset,
    *,
    target: str | None = None,
    predictors: list[str] | None = None,
) -> QualityReport:
    """Строит отчёт по данным и, если задана цель, по линейной модели."""
    profile = profile_dataset(dataset)
    # Аналитический срез, а не сырой frame: коды пропусков уже превращены в NaN,
    # иначе инспектор считал бы «-1» обычным значением.
    frame = dataset.analysis_frame()
    n_cases = int(len(frame))
    n_variables = int(len(frame.columns))
    missing_cells = int(frame.isna().sum().sum())
    complete_rows = int(frame.notna().all(axis=1).sum())
    duplicate_rows = int(frame.duplicated().sum())

    report = QualityReport(
        n_cases=n_cases,
        n_variables=n_variables,
        complete_rows=complete_rows,
        missing_cells=missing_cells,
        missing_share=missing_cells / (n_cases * n_variables) if n_cases and n_variables else 0.0,
        duplicate_rows=duplicate_rows,
        duplicate_share=duplicate_rows / n_cases if n_cases else 0.0,
        variables=[
            VariableQuality(
                name=item.name,
                label=item.label,
                role=item.role,
                type=item.var_type.value,
                measure=item.measure.value,
                n=item.n_cases,
                n_missing=item.n_missing,
                missing_share=item.missing_share,
                n_unique=item.n_unique,
                n_outliers=item.n_outliers,
                outlier_share=item.n_outliers / item.n_cases if item.n_cases else 0.0,
                skewness=item.skewness,
                is_normal=item.is_normal,
                is_identifier=item.is_identifier,
                is_constant=item.is_constant,
                is_binary=item.is_binary,
            )
            for item in profile.variables
        ],
    )

    report.issues.extend(_dataset_issues(profile, frame, report))
    report.correlated = _correlated_pairs(dataset, profile)
    if report.correlated:
        strongest = max(abs(pair["r"]) for pair in report.correlated)
        report.issues.append(
            QualityIssue(
                code="correlated_predictors",
                severity="warning" if strongest >= STRONG_CORRELATION else "note",
                title="Переменные почти дублируют друг друга",
                details=(
                    f"Найдено пар с |r| ≥ {NOTABLE_CORRELATION:.2f}: "
                    f"{len(report.correlated)}. Сильнейшая связь r = {strongest:.2f}; "
                    "в регрессии такие переменные дадут мультиколлинеарность."
                ),
                variables=tuple(
                    sorted(
                        {pair["a"] for pair in report.correlated}
                        | {pair["b"] for pair in report.correlated}
                    )
                ),
                values={"pairs": len(report.correlated), "max_r": strongest},
            )
        )

    multivariate = _multivariate_outliers(dataset, profile)
    if multivariate is not None:
        count, share, names, rows = multivariate
        report.issues.append(
            QualityIssue(
                code="multivariate_outliers",
                severity="warning" if share >= 0.02 else "note",
                title="Необычные сочетания значений",
                details=(
                    f"Многомерных выбросов (расстояние Махаланобиса): {count} "
                    f"({share * 100:.1f} % случаев). Проверьте строки: "
                    + ", ".join(str(row) for row in rows[:5])
                ),
                variables=tuple(names),
                values={"count": count, "share": share, "rows": rows[:5]},
            )
        )

    if target:
        if target not in dataset.names():
            raise ValueError(f"Переменной «{target}» нет в наборе")
        if not dataset.var(target).is_numeric:
            raise ValueError(f"Зависимая переменная «{target}» должна быть числовой")
        chosen = list(predictors or [])
        if not chosen:
            chosen = [
                item.name
                for item in profile.variables
                if item.is_numeric and not item.is_identifier and item.name != target
            ][:12]
        if not chosen:
            raise ValueError("Не удалось подобрать предикторы: выберите их вручную")
        report.regression = _regression_quality(dataset, target, chosen)
        report.target = target
        report.predictors = list(report.regression.predictors)
        report.issues.extend(_regression_issues(report.regression))

    return report


def _dataset_issues(
    profile: DatasetProfile, frame: pd.DataFrame, report: QualityReport
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    if report.n_cases == 0:
        return [
            QualityIssue(
                code="no_cases",
                severity="critical",
                title="В наборе нет строк",
                details="Анализ невозможен: нет ни одного наблюдения.",
            )
        ]

    empty = [item.name for item in profile.variables if item.n_missing == item.n_cases]
    if empty:
        issues.append(
            QualityIssue(
                code="empty_variable",
                severity="critical",
                title="Переменная целиком пустая",
                details=(
                    "Все значения пропущены: " + ", ".join(empty)
                    + ". Для анализа переменную нужно убрать или заполнить."
                ),
                variables=tuple(empty),
            )
        )

    constants = list(profile.constants)
    if constants:
        issues.append(
            QualityIssue(
                code="constant_variable",
                severity="warning",
                title="Переменная не меняется",
                details=(
                    "Одно и то же значение у всех случаев: " + ", ".join(constants)
                    + ". Такая переменная не различает группы и только занимает место."
                ),
                variables=tuple(constants),
            )
        )

    high_missing = [
        item.name for item in profile.variables if item.missing_share >= HIGH_MISSING
    ]
    if high_missing:
        issues.append(
            QualityIssue(
                code="high_missing",
                severity="warning",
                title="Много пропусков",
                details=(
                    f"Пропущено больше {HIGH_MISSING * 100:.0f} % значений: "
                    + ", ".join(high_missing)
                    + ". Выводы по этим переменным опираются на меньшую выборку."
                ),
                variables=tuple(high_missing),
            )
        )

    moderate = [
        item.name
        for item in profile.variables
        if MODERATE_MISSING <= item.missing_share < HIGH_MISSING
    ]
    if moderate:
        issues.append(
            QualityIssue(
                code="moderate_missing",
                severity="note",
                title="Заметные пропуски",
                details=(
                    f"От {MODERATE_MISSING * 100:.0f} до {HIGH_MISSING * 100:.0f} % "
                    "пропусков: " + ", ".join(moderate)
                    + ". Проверьте, не связан ли пропуск с группой."
                ),
                variables=tuple(moderate),
            )
        )

    if report.duplicate_rows:
        issues.append(
            QualityIssue(
                code="duplicate_rows",
                severity="warning" if report.duplicate_share >= 0.01 else "note",
                title="Повторяющиеся строки",
                details=(
                    f"Полных дублей: {report.duplicate_rows} "
                    f"({report.duplicate_share * 100:.1f} %). "
                    "Если это не разные люди с одинаковыми ответами, дубли искажают N."
                ),
                values={
                    "rows": report.duplicate_rows,
                    "share": report.duplicate_share,
                },
            )
        )

    duplicate_ids: list[str] = []
    for name in profile.identifiers:
        if name not in frame:
            continue
        codes = frame[name].dropna()
        if codes.duplicated().any():
            duplicate_ids.append(name)
    if duplicate_ids:
        issues.append(
            QualityIssue(
                code="duplicate_ids",
                severity="critical",
                title="Идентификатор повторяется",
                details=(
                    "Повторяются значения идентификатора: " + ", ".join(duplicate_ids)
                    + ". Один и тот же случай входит в данные несколько раз."
                ),
                variables=tuple(duplicate_ids),
            )
        )

    outliers = [
        item.name
        for item in profile.variables
        if item.n_cases and item.n_outliers / item.n_cases >= HIGH_OUTLIERS
    ]
    if outliers:
        issues.append(
            QualityIssue(
                code="outliers",
                severity="warning",
                title="Много выбросов",
                details=(
                    f"Больше {HIGH_OUTLIERS * 100:.0f} % значений вне межквартильного "
                    "размаха: " + ", ".join(outliers)
                    + ". Решите, это ошибки ввода или реальный разброс."
                ),
                variables=tuple(outliers),
            )
        )

    imbalance: list[str] = []
    for item in profile.variables:
        if item.n_unique < 2 or item.n_unique > 10:
            continue
        counts = frame[item.name].dropna().value_counts()
        if counts.empty:
            continue
        smallest = int(counts.min())
        if smallest / max(1, int(counts.sum())) < MIN_GROUP_SHARE:
            imbalance.append(item.name)
    if imbalance:
        issues.append(
            QualityIssue(
                code="group_imbalance",
                severity="warning",
                title="Сильный дисбаланс групп",
                details=(
                    "В одной из групп меньше "
                    f"{MIN_GROUP_SHARE * 100:.0f} % случаев: " + ", ".join(imbalance)
                    + ". Сравнение групп будет неустойчивым."
                ),
                variables=tuple(imbalance),
            )
        )

    scale_coded = [
        item.name
        for item in profile.variables
        if item.measure is Measure.SCALE
        and item.var_type is VarType.NUMERIC
        and 2 < item.n_unique <= 12
    ]
    if scale_coded:
        issues.append(
            QualityIssue(
                code="scale_coded",
                severity="note",
                title="Показатель похож на категорию",
                details=(
                    "Объявлены количественными, но имеют мало значений: "
                    + ", ".join(scale_coded)
                    + ". Проверьте уровень измерения: возможно, это порядковая шкала."
                ),
                variables=tuple(scale_coded),
            )
        )

    return issues


def _correlated_pairs(
    dataset: Dataset, profile: DatasetProfile
) -> list[dict[str, Any]]:
    numeric = [
        item.name
        for item in profile.variables
        if item.var_type is VarType.NUMERIC and item.n_unique > 2
    ][:MAX_MULTIVARIATE]
    pairs: list[dict[str, Any]] = []
    for index, first in enumerate(numeric):
        for second in numeric[index + 1 :]:
            frame = dataset.analysis_frame([first, second]).dropna()
            if len(frame) < 10:
                continue
            r = float(frame[first].corr(frame[second]))
            if math.isfinite(r) and abs(r) >= NOTABLE_CORRELATION:
                pairs.append({"a": first, "b": second, "r": r})
    pairs.sort(key=lambda pair: abs(pair["r"]), reverse=True)
    return pairs


def _multivariate_outliers(
    dataset: Dataset, profile: DatasetProfile
) -> tuple[int, float, list[str], list[int]] | None:
    names = [
        item.name
        for item in profile.variables
        if item.measure is Measure.SCALE
        and item.var_type is VarType.NUMERIC
        and item.n_unique > 12
    ][:MAX_MULTIVARIATE]
    if len(names) < 2:
        return None
    frame = dataset.analysis_frame(names).dropna()
    n, k = len(frame), len(names)
    if n < k + 5:
        return None
    values = frame.to_numpy(dtype=float)
    covariance = np.cov(values, rowvar=False)
    try:
        inverse = np.linalg.pinv(covariance)
    except np.linalg.LinAlgError:
        return None
    centered = values - values.mean(axis=0)
    distances = np.einsum("ij,jk,ik->i", centered, inverse, centered)
    threshold = scipy_stats.chi2.ppf(0.999, k)
    mask = distances > threshold
    count = int(mask.sum())
    if not count:
        return None
    rows = [int(index) + 1 for index in np.where(mask)[0][:5]]
    return count, count / n, names, rows


def _regression_quality(
    dataset: Dataset, target: str, predictors: list[str]
) -> RegressionQuality:
    unique: list[str] = []
    for name in predictors:
        if name != target and name not in unique:
            unique.append(name)
    if not unique:
        raise ValueError("Нужен хотя бы один предиктор")
    for name in unique:
        if name not in dataset.names():
            raise ValueError(f"Переменной «{name}» нет в наборе")
        if not dataset.var(name).is_numeric:
            raise ValueError(f"Предиктор «{name}» должен быть числовым")

    frame = dataset.analysis_frame([target, *unique]).dropna()
    n = len(frame)
    if n <= len(unique) + 2:
        raise ValueError(
            f"Для модели слишком мало полных наблюдений: {n}. "
            "Уберите пропуски или сократите число предикторов."
        )

    try:
        fit = fit_linear(frame, target, unique, confidence=0.95)
    except (np.linalg.LinAlgError, ValueError) as exc:
        raise ValueError(f"Модель не оценивается: {exc}") from exc

    x = np.column_stack(
        [np.ones(n), *(frame[name].to_numpy(dtype=float) for name in unique)]
    )
    parameters = x.shape[1]
    try:
        inverse = np.linalg.pinv(x.T @ x)
        leverage = np.einsum("ij,jk,ik->i", x, inverse, x)
    except np.linalg.LinAlgError:
        leverage = np.zeros(n)

    mse = float(fit.ms_residual)
    cooks = np.zeros(n)
    if mse > 0:
        safe = np.clip(leverage, 0.0, 1.0 - 1e-12)
        cooks = (fit.residuals**2 / (parameters * mse)) * (safe / (1.0 - safe) ** 2)
    cooks_max = float(np.nanmax(cooks)) if n else 0.0
    influential = int((cooks > 4.0 / n).sum()) if n else 0
    leverage_count = int((leverage > 2.0 * parameters / n).sum()) if n else 0

    standardized = np.zeros(n)
    if mse > 0:
        safe = np.clip(leverage, 0.0, 1.0 - 1e-12)
        standardized = fit.residuals / math.sqrt(mse) / np.sqrt(1.0 - safe)

    bp_lm, bp_p = _breusch_pagan(fit.residuals, x)
    normality_p = None
    if 8 <= n <= 5000:
        try:
            normality_p = float(scipy_stats.shapiro(fit.residuals).pvalue)
        except (ValueError, TypeError):
            normality_p = None

    vif = {name: float(value) for name, value in fit.vif.items()}
    return RegressionQuality(
        target=target,
        predictors=tuple(unique),
        n=n,
        n_predictors=len(unique),
        r_squared=float(fit.r_squared),
        adj_r_squared=float(fit.adj_r_squared),
        max_vif=max(vif.values(), default=0.0),
        vif=vif,
        breusch_pagan_p=bp_p,
        breusch_pagan_lm=bp_lm,
        durbin_watson=float(fit.durbin_watson),
        cooks_max=cooks_max,
        influential_count=influential,
        leverage_count=leverage_count,
        residual_normality_p=normality_p,
        condition_index=float(fit.condition_index),
        n_per_predictor=n / len(unique),
    )


def _breusch_pagan(
    residuals: np.ndarray, design: np.ndarray
) -> tuple[float | None, float | None]:
    """Тест Бреуша-Пегана; общая реализация — в diagnostics.py."""
    result = breusch_pagan(residuals, design)
    return result.statistic, result.p_value


def _regression_issues(regression: RegressionQuality) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    if regression.max_vif >= 10:
        issues.append(
            QualityIssue(
                code="multicollinearity",
                severity="warning",
                title="Мультиколлинеарность",
                details=(
                    f"Максимальный VIF = {regression.max_vif:.1f} (порог 10). "
                    "Коэффициенты модели неустойчивы: предикторы дублируют друг друга."
                ),
                variables=tuple(
                    name
                    for name, value in regression.vif.items()
                    if value >= 10
                ),
                values={"max_vif": regression.max_vif},
            )
        )
    elif regression.max_vif >= 5:
        issues.append(
            QualityIssue(
                code="multicollinearity_note",
                severity="note",
                title="Заметная связь предикторов",
                details=(
                    f"Максимальный VIF = {regression.max_vif:.1f} (5–10). "
                    "Стоит проверить, не измеряют ли предикторы одно и то же."
                ),
                variables=tuple(
                    name
                    for name, value in regression.vif.items()
                    if value >= 5
                ),
                values={"max_vif": regression.max_vif},
            )
        )

    if regression.breusch_pagan_p is not None and regression.breusch_pagan_p < 0.05:
        issues.append(
            QualityIssue(
                code="heteroscedasticity",
                severity="warning",
                title="Гетероскедастичность",
                details=(
                    f"Тест Бреуша-Пегана: p = {regression.breusch_pagan_p:.3f}. "
                    "Разброс остатков зависит от предикторов — обычные стандартные "
                    "ошибки и доверительные интервалы могут быть неверными."
                ),
                values={"p": regression.breusch_pagan_p},
            )
        )

    if not 1.5 <= regression.durbin_watson <= 2.5:
        issues.append(
            QualityIssue(
                code="autocorrelation",
                severity="warning",
                title="Автокорреляция остатков",
                details=(
                    f"Дарбин-Уотсон = {regression.durbin_watson:.2f} (норма около 2). "
                    "Соседние наблюдения связаны; проверьте порядок строк и время."
                ),
                values={"durbin_watson": regression.durbin_watson},
            )
        )

    if regression.influential_count and (
        regression.cooks_max > 1.0 or regression.influential_count / regression.n > 0.05
    ):
        issues.append(
            QualityIssue(
                code="influential_cases",
                severity="warning",
                title="Влиятельные наблюдения",
                details=(
                    f"Влиятельных точек: {regression.influential_count} "
                    f"из {regression.n}; максимум Кука = {regression.cooks_max:.2f}. "
                    "Одна-две строки могут определять коэффициенты."
                ),
                values={
                    "count": regression.influential_count,
                    "cooks_max": regression.cooks_max,
                },
            )
        )

    if regression.residual_normality_p is not None and regression.residual_normality_p < 0.05:
        issues.append(
            QualityIssue(
                code="residual_normality",
                severity="note",
                title="Остатки не нормальны",
                details=(
                    f"Шапиро-Уилк: p = {regression.residual_normality_p:.3f}. "
                    "На больших выборках это влияет мало, на малых — на p-значения."
                ),
                values={"p": regression.residual_normality_p},
            )
        )

    if regression.n_per_predictor < 10:
        issues.append(
            QualityIssue(
                code="small_sample",
                severity="warning",
                title="Мало наблюдений на предиктор",
                details=(
                    f"{regression.n} наблюдений на {regression.n_predictors} "
                    "предикторов. Для устойчивой модели нужно хотя бы 10 на предиктор."
                ),
                values={"n": regression.n, "predictors": regression.n_predictors},
            )
        )

    return issues


def _severity_ru(severity: str) -> str:
    return {"critical": "критично", "warning": "предупреждение", "note": "заметка"}.get(
        severity, severity
    )


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (ValueError, AttributeError):
            return str(value)
    return value


__all__ = [
    "QualityIssue",
    "QualityReport",
    "RegressionQuality",
    "VariableQuality",
    "quality_report",
]
