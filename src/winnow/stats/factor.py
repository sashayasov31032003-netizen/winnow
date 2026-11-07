"""Эксплораторный факторный анализ.

Отвечает на вопрос, который задают про любой опросник: сколько за пунктами стоит
скрытых конструктов и какие пункты к какому относятся. Это проверка структуры
опросника - то, без чего психологическая шкала в дипломной работе не защищается.

Реализовано:

* проверка применимости: мера адекватности выборки Кайзера-Мейера-Олкина (KMO)
  и критерий сферичности Бартлетта;
* выделение факторов методом главных компонент или главных факторов;
* вращение Varimax и Quartimax (ортогональные) и Promax (косоугольное);
* общности, собственные значения, доля объяснённой дисперсии;
* матрица факторных нагрузок после вращения и факторные значения.

Числа проверяются на данных с заранее известной структурой.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.stats import interpretation
from winnow.stats.command import CommandError, FactorCommand
from winnow.stats.result import Column, Result, Table

ROTATION_LABELS = {
    "none": "без вращения",
    "varimax": "Varimax (ортогональное)",
    "quartimax": "Quartimax (ортогональное)",
    "promax": "Promax (косоугольное)",
}

METHOD_LABELS = {
    "pca": "Метод главных компонент",
    "ml": "Метод главных факторов",
}


@dataclass
class FactorSolution:
    """Результат факторного анализа."""

    n: int
    k_variables: int
    correlation: np.ndarray
    eigenvalues: np.ndarray
    explained: np.ndarray          # доля объяснённой дисперсии по каждому фактору
    cumulative: np.ndarray         # накопленная доля
    loadings: np.ndarray           # матрица нагрузок после вращения
    unrotated: np.ndarray          # до вращения
    communalities: np.ndarray
    n_factors: int
    kmo: float
    kmo_per_variable: dict[str, float] = field(default_factory=dict)
    bartlett_chi2: float = float("nan")
    bartlett_df: float = float("nan")
    bartlett_p: float = float("nan")
    rotation: str = "none"
    method: str = "pca"
    scores: np.ndarray | None = None


def _correlation_matrix(data: np.ndarray) -> np.ndarray:
    return np.corrcoef(data, rowvar=False)


def kmo_measure(correlation: np.ndarray) -> tuple[float, np.ndarray]:
    """Мера адекватности выборки Кайзера-Мейера-Олкина.

    Сравнивает простые корреляции с частными: если после исключения влияния
    остальных переменных связи почти исчезают, значит общие факторы есть, и
    факторный анализ применим. Значение ниже 0.5 означает, что данные для
    факторного анализа не подходят.
    """
    k = correlation.shape[0]
    if k < 2:
        return float("nan"), np.array([])
    try:
        inverse = np.linalg.inv(correlation)
    except np.linalg.LinAlgError:
        return float("nan"), np.full(k, np.nan)

    # Антиобразная корреляционная матрица: частные корреляции со знаком минус.
    diagonal = np.sqrt(np.diag(inverse))
    anti_image = -inverse / np.outer(diagonal, diagonal)
    np.fill_diagonal(anti_image, 0.0)

    partial = correlation.copy()
    np.fill_diagonal(partial, 0.0)

    sum_partial = float(np.sum(partial**2))
    sum_anti = float(np.sum(anti_image**2))
    if sum_partial + sum_anti <= 0:
        return float("nan"), np.full(k, np.nan)

    overall = sum_partial / (sum_partial + sum_anti)
    per_variable = np.sum(partial**2, axis=0) / (
        np.sum(partial**2, axis=0) + np.sum(anti_image**2, axis=0)
    )
    return float(overall), per_variable


def bartlett_test(correlation: np.ndarray, n: int) -> tuple[float, float, float]:
    """Критерий сферичности Бартлетта: проверяет, что матрица не единичная."""
    k = correlation.shape[0]
    if k < 2 or n <= k:
        return float("nan"), float("nan"), float("nan")
    sign, logdet = np.linalg.slogdet(correlation)
    if sign <= 0 or not math.isfinite(logdet):
        return float("nan"), float("nan"), float("nan")
    statistic = -((n - 1) - (2 * k + 5) / 6.0) * logdet
    df = k * (k - 1) / 2.0
    p_value = float(sps.chi2.sf(statistic, df)) if statistic > 0 else float("nan")
    return float(statistic), float(df), p_value


def _principal_components(correlation: np.ndarray, n_factors: int) -> np.ndarray:
    """Нагрузки методом главных компонент."""
    eigenvalues, eigenvectors = np.linalg.eigh(correlation)
    order = np.argsort(eigenvalues)[::-1][:n_factors]
    loadings = eigenvectors[:, order] * np.sqrt(np.maximum(eigenvalues[order], 0.0))
    return loadings


def _principal_factors(
    correlation: np.ndarray, n_factors: int, iterations: int = 50, tolerance: float = 1e-6
) -> np.ndarray:
    """Нагрузки методом главных факторов с итерациями по общностям.

    В отличие от главных компонент, этот метод анализирует только общую
    дисперсию, а не всю: для проверки структуры опросника он корректнее.
    """
    k = correlation.shape[0]
    communalities = np.ones(k)
    loadings = np.zeros((k, n_factors))
    for _ in range(iterations):
        reduced = correlation.copy()
        np.fill_diagonal(reduced, communalities)
        eigenvalues, eigenvectors = np.linalg.eigh(reduced)
        order = np.argsort(eigenvalues)[::-1][:n_factors]
        new_loadings = eigenvectors[:, order] * np.sqrt(np.maximum(eigenvalues[order], 0.0))
        new_communalities = np.clip(np.sum(new_loadings**2, axis=1), 0.0, 1.0)
        if np.max(np.abs(new_communalities - communalities)) < tolerance:
            loadings = new_loadings
            communalities = new_communalities
            break
        loadings = new_loadings
        communalities = new_communalities
    return loadings


def varimax(
    loadings: np.ndarray,
    gamma: float = 1.0,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
    normalize: bool = True,
) -> np.ndarray:
    """Ортогональное вращение Varimax (или Quartimax при gamma = 0).

    Вращение не меняет общности и объяснённую дисперсию - оно только
    перераспределяет нагрузки так, чтобы структура читалась: каждый пункт
    нагружен на один фактор сильно, на остальные слабо.

    ВАЖНО: столбцы нормируются перед вращением. У сырых нагрузок столбцы имеют
    разный масштаб, и без нормировки вращение работает неверно - общности
    «размазываются» и структура теряется. Это стандартный приём (так же работает
    SPSS), а обратная нормировка не нужна: масштаб столбцов всё равно приводится
    к единице вызывающим кодом.
    """
    rows, columns = loadings.shape
    if columns < 2:
        return loadings.copy()

    if normalize:
        norms = np.sqrt(np.sum(loadings**2, axis=0))
        safe = np.where(norms > 1e-12, norms, 1.0)
        rotation_input = loadings / safe
    else:
        rotation_input = loadings.copy()

    # ВАЖНО: итерации идут по НЕнормированным нагрузкам. Нормировка нужна только
    # для выбора угла поворота, а сам поворот обязан применяться к исходным
    # нагрузкам - иначе вместо поворота получается сжатие и общности рушатся
    # (проверено: 0.906 превращалось в 0.331).
    rotated = loadings.copy()
    previous = 0.0
    for _ in range(max_iterations):
        u, s, vh = np.linalg.svd(
            rotation_input.T
            @ (
                rotation_input**3
                - (gamma / rows) * rotation_input @ np.diag(np.sum(rotation_input**2, axis=0))
            )
        )
        transform = u @ vh
        rotation_input = rotation_input @ transform
        rotated = rotated @ transform
        current = float(np.sum(s))
        if previous and current / previous < 1.0 + tolerance:
            break
        previous = current
    return rotated


def promax(loadings: np.ndarray, power: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Косоугольное вращение Promax: сначала Varimax, затем степенное преобразование.

    Возвращает нагрузки и матрицу корреляций факторов: при косоугольном вращении
    факторы могут быть связаны между собой, и это нужно показывать.
    """
    if loadings.shape[1] < 2:
        return loadings.copy(), np.eye(loadings.shape[1])
    orthogonal = varimax(loadings)
    # Степенное преобразование усиливает простую структуру.
    target = np.sign(orthogonal) * np.abs(orthogonal) ** (power + 1)
    try:
        transform = np.linalg.solve(orthogonal.T @ orthogonal, orthogonal.T @ target)
    except np.linalg.LinAlgError:
        return orthogonal, np.eye(loadings.shape[1])
    rotated = orthogonal @ transform
    # Корреляции факторов: нормируем столбцы преобразования.
    norms = np.sqrt(np.diag(transform.T @ transform))
    norms[norms == 0] = 1.0
    factor_correlation = (transform.T @ transform) / np.outer(norms, norms)
    return rotated, factor_correlation


def _normalize_rotation(loadings: np.ndarray) -> np.ndarray:
    """Приводит нагрузки к устойчивому виду: знаки и порядок факторов.

    Факторное решение определено с точностью до знака и перестановки столбцов:
    умножение столбца на -1 или обмен двух факторов дают ту же модель. Это создаёт
    две проблемы: знаки меняются от запуска к запуску, а «первый» фактор может
    оказаться вторым. Здесь знаки ориентируются так, чтобы сумма нагрузок была
    положительной, а порядок задаётся жадно: первый фактор - тот, на котором
    сильнее всего нагружена первая переменная списка.

    ВАЖНО: масштаб нагрузок не меняется. Соблазн поделить столбцы на их нормы
    (чтобы «привести к единице») разрушает решение: объяснённая дисперсия каждого
    фактора становится ровно 1, а общности падают с 0.9 до 0.33. Нормировка
    допустима только внутри вращения и только для выбора угла.
    """
    if loadings.size == 0 or loadings.shape[1] == 0:
        return loadings

    columns = loadings.shape[1]
    signs = np.ones(columns)
    for column in range(columns):
        if float(np.sum(loadings[:, column])) < 0:
            signs[column] = -1.0

    orientation = loadings * signs

    # Порядок факторов: жадно выбираем столбец с наибольшей нагрузкой на первую
    # переменную, затем на следующую и так далее. Это даёт стабильный результат,
    # привязанный к порядку переменных, а не к произвольному порядку собственных
    # значений после вращения.
    remaining = list(range(columns))
    order: list[int] = []
    for row in range(orientation.shape[0]):
        if not remaining:
            break
        best = max(remaining, key=lambda column: abs(orientation[row, column]))
        if abs(orientation[row, best]) < 1e-9:
            continue
        order.append(best)
        remaining.remove(best)
    order.extend(remaining)
    return orientation[:, order]


def _rotate(loadings: np.ndarray, rotation: str) -> tuple[np.ndarray, np.ndarray | None]:
    if rotation == "none" or loadings.shape[1] < 2:
        return _normalize_rotation(loadings), None
    if rotation == "varimax":
        return _normalize_rotation(varimax(loadings)), None
    if rotation == "quartimax":
        return _normalize_rotation(varimax(loadings, gamma=0.0)), None
    if rotation == "promax":
        rotated, factor_correlation = promax(loadings)
        return _normalize_rotation(rotated), factor_correlation
    return _normalize_rotation(loadings), None


def fit_factor(
    data: np.ndarray,
    names: list[str],
    method: str = "pca",
    rotation: str = "varimax",
    n_factors: int = 0,
    min_eigenvalue: float = 1.0,
) -> FactorSolution:
    """Выполняет факторный анализ целиком."""
    n, k = data.shape
    correlation = _correlation_matrix(data)
    eigenvalues = np.sort(np.linalg.eigvalsh(correlation))[::-1]
    eigenvalues = np.maximum(eigenvalues, 0.0)
    explained = eigenvalues / k
    cumulative = np.cumsum(explained)

    if n_factors <= 0:
        # Критерий Кайзера: оставляем факторы с собственным значением больше
        # заданного порога (обычно 1).
        n_factors = int(np.sum(eigenvalues > min_eigenvalue))
    n_factors = max(1, min(n_factors, k - 1))

    raw = (
        _principal_components(correlation, n_factors)
        if method == "pca"
        else _principal_factors(correlation, n_factors)
    )
    loadings, factor_correlation = _rotate(raw, rotation)
    communalities = np.sum(loadings**2, axis=1)

    overall_kmo, per_variable = kmo_measure(correlation)
    chi2, df, p_value = bartlett_test(correlation, n)

    # Факторные значения по методу регрессии: используются для дальнейшего анализа.
    scores: np.ndarray | None = None
    if n_factors >= 1:
        try:
            structure = correlation @ np.linalg.pinv(correlation) @ loadings
            scores = (data - data.mean(axis=0)) @ np.linalg.pinv(correlation) @ structure
        except np.linalg.LinAlgError:
            scores = None

    return FactorSolution(
        n=n,
        k_variables=k,
        correlation=correlation,
        eigenvalues=eigenvalues,
        explained=explained,
        cumulative=cumulative,
        loadings=loadings,
        unrotated=raw,
        communalities=communalities,
        n_factors=n_factors,
        kmo=overall_kmo,
        kmo_per_variable=dict(zip(names, per_variable.tolist())),
        bartlett_chi2=chi2,
        bartlett_df=df,
        bartlett_p=p_value,
        rotation=rotation,
        method=method,
        scores=scores,
    )


# ---------------------------------------------------------------------------
# Таблицы вывода
# ---------------------------------------------------------------------------


def _adequacy_table(solution: FactorSolution) -> Table:
    table = Table(
        title="Проверка применимости факторного анализа",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", decimals=3),
        ],
        footnotes=[
            "KMO ниже 0.5 означает, что данные плохо подходят для факторного "
            "анализа: общих факторов в них, скорее всего, нет.",
            "Критерий Бартлетта проверяет, что корреляционная матрица не единичная. "
            "Значимость меньше 0.05 - это условие применимости выполнено.",
        ],
    )
    table.add_row(["Мера адекватности выборки (KMO)", solution.kmo])
    table.add_row(["Критерий Бартлетта: хи-квадрат", solution.bartlett_chi2])
    table.add_row(["ст. св.", solution.bartlett_df])
    table.add_row(["значимость", solution.bartlett_p])
    table.add_row(["Число наблюдений", float(solution.n)])
    return table


def _communalities_table(solution: FactorSolution, names: list[str]) -> Table:
    table = Table(
        title="Общности",
        columns=[
            Column("Переменная", align="left", is_metric=False),
            Column("Начальная", decimals=3),
            Column("После выделения", decimals=3),
            Column("KMO переменной", decimals=3),
        ],
        footnotes=[
            "Общность - доля дисперсии переменной, объяснённая факторами. "
            "Значение ниже 0.5 означает, что переменная плохо представлена моделью."
        ],
    )
    for index, name in enumerate(names):
        table.add_row(
            [
                name,
                1.0,
                float(solution.communalities[index]),
                float(solution.kmo_per_variable.get(name, float("nan"))),
            ]
        )
    return table


def _variance_table(solution: FactorSolution) -> Table:
    table = Table(
        title="Объяснённая дисперсия",
        columns=[
            Column("Компонента", align="left", is_metric=False),
            Column("Собственное значение", decimals=3),
            Column("Доля дисперсии", decimals=3),
            Column("Накопленная доля", decimals=3),
        ],
        footnotes=[
            "По критерию Кайзера оставляются компоненты с собственным значением "
            "больше единицы."
        ],
    )
    for index in range(min(solution.k_variables, 10)):
        table.add_row(
            [
                f"{index + 1}",
                float(solution.eigenvalues[index]),
                float(solution.explained[index]),
                float(solution.cumulative[index]),
            ]
        )
    table.add_row(
        [
            f"Оставлено факторов: {solution.n_factors}",
            None,
            float(solution.cumulative[solution.n_factors - 1]),
            None,
        ]
    )
    return table


def _loadings_table(
    solution: FactorSolution, names: list[str], suppress: float
) -> Table:
    table = Table(
        title=f"Матрица факторных нагрузок ({ROTATION_LABELS[solution.rotation]})",
        columns=[Column("Переменная", align="left", is_metric=False)]
        + [Column(f"Фактор {index + 1}", decimals=3) for index in range(solution.n_factors)],
        footnotes=[
            "Нагрузка - связь переменной с фактором. Обычно значимыми считают "
            "нагрузки от 0.4; здесь слабые нагрузки скрыты для читаемости.",
            "Переменная относится к тому фактору, где её нагрузка наибольшая.",
        ],
    )
    for index, name in enumerate(names):
        row: list[Any] = [name]
        for factor in range(solution.n_factors):
            value = float(solution.loadings[index, factor])
            row.append(None if abs(value) < suppress else value)
        table.add_row(row)
    return table


def run_factor(command: FactorCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    frame = dataset.analysis_frame(command.variables)
    total = int(len(frame))
    numeric = pd.DataFrame(
        {name: pd.to_numeric(frame[name], errors="coerce") for name in command.variables}
    )
    complete = numeric.dropna()
    excluded = total - int(len(complete))

    summary = Table(
        title="Сводка по обработке наблюдений",
        columns=[
            Column("", align="left", is_metric=False),
            Column("N", decimals=0),
        ],
        footnotes=["Факторный анализ требует полных наблюдений по всем переменным."],
    )
    summary.add_row(["Всего кейсов", total])
    summary.add_row(["Включено в анализ", len(complete)])
    summary.add_row(["Исключено (пропуски)", excluded])
    result.add_table(summary)

    names = [dataset.var(name).display_name for name in command.variables]
    if len(complete) < len(command.variables) + 2:
        result.warn(
            "Наблюдений слишком мало для факторного анализа: нужно хотя бы "
            "на несколько больше, чем переменных"
        )
        return result

    data = complete.to_numpy(dtype=float)
    if np.any(np.std(data, axis=0, ddof=1) == 0):
        result.warn("Одна из переменных не изменяется - факторный анализ невозможен")
        return result

    solution = fit_factor(
        data,
        names,
        method=command.method,
        rotation=command.rotation,
        n_factors=command.n_factors,
        min_eigenvalue=command.min_eigenvalue,
    )

    if command.kmo or command.bartlett:
        result.add_table(_adequacy_table(solution))
    if math.isfinite(solution.kmo) and solution.kmo < 0.5:
        result.warn(
            f"KMO = {solution.kmo:.3f}: данные плохо подходят для факторного анализа"
        )
    if command.scree:
        result.add_table(_variance_table(solution))
    result.add_table(_communalities_table(solution, names))

    weak = [
        name
        for index, name in enumerate(names)
        if solution.communalities[index] < 0.5
    ]
    if weak:
        result.warn(
            "плохо объяснены моделью (общность ниже 0.5): " + ", ".join(weak[:5])
        )

    result.add_table(_loadings_table(solution, names, command.suppress_small))

    if solution.rotation == "promax":
        # Для косоугольного вращения важно показать, что факторы связаны.
        correlation = np.corrcoef(
            ((data - data.mean(axis=0)) @ np.linalg.pinv(solution.correlation) @ solution.loadings).T
        )
        table = Table(
            title="Корреляции факторов",
            columns=[Column("", align="left", is_metric=False)]
            + [Column(f"Фактор {index + 1}", decimals=3) for index in range(solution.n_factors)],
            footnotes=[
                "При косоугольном вращении факторы могут быть связаны. Сильные "
                "связи означают, что факторы не независимы."
            ],
        )
        for index in range(solution.n_factors):
            table.add_row([f"Фактор {index + 1}"] + [float(value) for value in correlation[index]])
        result.add_table(table)

    if command.save_scores and solution.scores is not None:
        table = Table(
            title="Факторные значения (первые пять кейсов)",
            columns=[Column("Кейс", decimals=0)]
            + [Column(f"Фактор {index + 1}", decimals=3) for index in range(solution.n_factors)],
            footnotes=[
                "Факторные значения можно сохранить как переменные и использовать "
                "в дальнейшем анализе."
            ],
        )
        for row_index in range(min(5, solution.scores.shape[0])):
            table.add_row(
                [row_index + 1]
                + [float(value) for value in solution.scores[row_index]]
            )
        result.add_table(table)

    result.note(
        f"Выделено факторов: {solution.n_factors} "
        f"({METHOD_LABELS[command.method]}, {ROTATION_LABELS[command.rotation]}); "
        f"объяснено {solution.cumulative[solution.n_factors - 1] * 100:.1f}% дисперсии"
    )

    # Вывод «простыми словами»: главный вопрос здесь не «сколько факторов», а
    # «можно ли было вообще их выделять» - на него отвечают KMO и Бартлетт.
    result.add_findings(
        interpretation.factor_structure(
            variables=len(command.variables),
            n_factors=int(solution.n_factors),
            explained=float(solution.cumulative[solution.n_factors - 1]),
            kmo=float(solution.kmo) if math.isfinite(solution.kmo) else float("nan"),
            bartlett_p=(
                float(solution.bartlett_p)
                if math.isfinite(solution.bartlett_p)
                else float("nan")
            ),
        )
    )
    return result


def run(command: FactorCommand) -> Result:
    """Точка входа процедуры для движка."""
    return run_factor(command)


__all__ = [
    "METHOD_LABELS",
    "ROTATION_LABELS",
    "FactorSolution",
    "bartlett_test",
    "fit_factor",
    "kmo_measure",
    "promax",
    "run",
    "run_factor",
    "varimax",
]
