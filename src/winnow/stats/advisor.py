"""Советчик: что можно сделать с загруженными данными.

Зачем это нужно. Опытный исследователь, открыв базу, сам знает, с чего начать.
Начинающий видит сто три переменные и не понимает, что с ними делать: в программе
есть четырнадцать процедур, но выбор процедуры - это уже статистическая
квалификация, которой у него нет.

Советчик закрывает именно этот разрыв. Он смотрит на профиль данных и предлагает
готовые сценарии исследования: «сравнить две группы», «проверить связь двух
показателей», «проверить согласованность анкеты». У каждого сценария сразу
подставлены конкретные переменные, и рядом сказано, ПОЧЕМУ он предложен.

Три правила, без которых такая подсказка вредна:

* **подсказка, а не приговор.** Сценарий можно выполнить, но решение остаётся за
  пользователем: программа объясняет, почему предлагает, и что при этом
  проверяется;
* **конкретность.** Не «есть количественные переменные», а «мужчины и женщины
  различаются по тревожности (p = 0,008)» — с числами, по которым предложение
  можно принять или отклонить;
* **никаких догадок о смысле по имени переменной.** Роли определяются только по
  измеримым свойствам: шкала, число градаций, пропуски.

Модуль работает без интерфейса: на входе набор данных, на выходе список
сценариев. Поэтому его поведение проверяется тестами как обычные расчёты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from winnow.core.dataset import Dataset
from winnow.core.variable import VarType
from winnow.stats.profile import (
    DatasetProfile,
    VariableProfile,
    profile_dataset,
)
from winnow.stats.reliability import cronbach_alpha

# Сколько переменных каждого вида рассматривать. Больше не нужно: подсказка всё
# равно показывает один лучший вариант, а перебор всех пар на сотне переменных
# занимал бы заметное время.
MAX_CANDIDATES = 12
# Ниже этого числа полных наблюдений пары расчёт не имеет смысла.
MIN_PAIR_CASES = 8
# Порог значимости, по которому сценарий считается «подходящим».
ALPHA = 0.05


@dataclass
class Scenario:
    """Готовый сценарий исследования с подставленными переменными."""

    key: str
    title: str
    question: str
    why: str
    procedure: str
    params: dict[str, Any] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    confidence: str = "возможно"
    caveats: list[str] = field(default_factory=list)
    order: int = 100

    @property
    def is_confident(self) -> bool:
        return self.confidence == "подходит"

    def variables(self) -> list[str]:
        """Все переменные, которые сценарий использует."""
        return list(self.roles.values())

    def summary(self) -> str:
        """Одна строка для списка сценариев."""
        variables = ", ".join(self.roles.values())
        return f"{self.title} ({variables})"


def _candidates(
    profile: DatasetProfile, variables: list[VariableProfile], limit: int = MAX_CANDIDATES
) -> list[VariableProfile]:
    """Отбирает переменные для перебора: сначала самые полные.

    Переменная с половиной пропусков даст расчёт на половине случаев, поэтому
    при выборе «лучшей пары» предпочтение отдаётся заполненным переменным.
    """
    ordered = sorted(variables, key=lambda variable: (variable.missing_share, variable.name))
    return ordered[:limit]


def _frames(dataset: Dataset, names: list[str]) -> pd.DataFrame:
    """Срез данных без кодов пропусков - в том же виде, в каком считают процедуры.

    Имена повторяться не должны: срез с двумя одинаковыми столбцами превращает
    обычное обращение `frame[имя]` в таблицу, и расчёт падает на ровном месте.
    """
    unique: list[str] = []
    for name in names:
        if name not in unique:
            unique.append(name)
    return dataset.analysis_frame(unique)


def _cohens_d(first: np.ndarray, second: np.ndarray) -> float:
    """Размер эффекта для двух групп (объединённое стандартное отклонение)."""
    n1, n2 = len(first), len(second)
    if n1 < 2 or n2 < 2:
        return float("nan")
    var1, var2 = first.var(ddof=1), second.var(ddof=1)
    pooled = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
    if pooled <= 0:
        return float("nan")
    return float((first.mean() - second.mean()) / np.sqrt(pooled))


def _cramers_v(table: np.ndarray) -> float:
    """Сила связи двух категориальных переменных (V Крамера)."""
    total = table.sum()
    if total <= 0:
        return float("nan")
    chi2 = float(scipy_stats.chi2_contingency(table, correction=False)[0])
    smallest = min(table.shape) - 1
    if smallest <= 0:
        return float("nan")
    return float(np.sqrt(chi2 / (total * smallest)))


# Разница больше этого числа стандартных отклонений в анкетных данных
# неправдоподобна. Обычно это значит, что группа выведена из самого показателя:
# например, возраст разбили на «поколения» и предлагают сравнить их по возрасту.
IMPLAUSIBLE_EFFECT = 3.0
# Разница больше этого значения возможна, но требует объяснения.
SUSPICIOUS_EFFECT = 1.5


def _tautology_caveat(
    first: np.ndarray, second: np.ndarray, group: str, outcome: str
) -> str:
    """Предупреждение о сравнении, которое не может не дать разницы."""
    return (
        f"Разница очень велика. Проверьте, не выведена ли переменная-группа "
        f"«{group}» из самого показателя «{outcome}»: например, возраст, "
        "разбитый на возрастные группы, всегда будет от них отличаться. "
        "Такой результат ничего не доказывает, его нельзя приводить как вывод."
    )


def _two_group_scenario(
    frame: pd.DataFrame, groupers: list[VariableProfile], scales: list[VariableProfile]
) -> Scenario | None:
    """Ищет самую заметную разницу между двумя группами."""
    best: tuple[float, Scenario] | None = None
    for grouper in groupers:
        if grouper.n_unique != 2:
            continue
        for scale in scales:
            if grouper.name == scale.name:
                continue
            pair = frame[[grouper.name, scale.name]].dropna()
            if len(pair) < MIN_PAIR_CASES:
                continue
            levels = sorted(pair[grouper.name].unique())
            if len(levels) != 2:
                continue
            first = pair.loc[pair[grouper.name] == levels[0], scale.name].to_numpy(dtype=float)
            second = pair.loc[pair[grouper.name] == levels[1], scale.name].to_numpy(dtype=float)
            if len(first) < 3 or len(second) < 3:
                continue
            # Критерий Уэлча: не требует равенства дисперсий, поэтому подходит
            # как предложение по умолчанию. Обычный Стьюдент остаётся доступен.
            _statistic, p_value = scipy_stats.ttest_ind(first, second, equal_var=False)
            if not np.isfinite(p_value):
                continue
            effect = _cohens_d(first, second)
            if not np.isfinite(effect):
                continue
            # Неправдоподобно большая разница означает, что сравнение
            # бессодержательно: предлагать его как исследование нельзя.
            if abs(effect) >= IMPLAUSIBLE_EFFECT:
                continue
            label_first = _level_label(frame, grouper.name, levels[0])
            label_second = _level_label(frame, grouper.name, levels[1])
            why = (
                f"{label_first} и {label_second}: {_format_p(p_value)}, средние "
                f"{first.mean():.3g} и {second.mean():.3g}, размер эффекта "
                f"d = {effect:.2f} (n = {len(first)} и {len(second)})"
            )
            caveats = _normality_caveats(first, second, scale.name)
            confidence = "подходит" if p_value < ALPHA else "возможно"
            if abs(effect) >= SUSPICIOUS_EFFECT:
                confidence = "возможно"
                caveats.insert(
                    0,
                    _tautology_caveat(
                        first, second, grouper.label or grouper.name, scale.label or scale.name
                    ),
                )
            scenario = Scenario(
                key="compare_two_groups",
                title="Сравнить две группы",
                question=(
                    f"Различаются ли «{label_first}» и «{label_second}» по "
                    f"показателю «{scale.label or scale.name}»?"
                ),
                why=why,
                procedure="ttest",
                params={
                    "kind": "independent",
                    "test_vars": [scale.name],
                    "group_var": grouper.name,
                    # Какие именно значения образуют группы, нужно указать явно:
                    # без этого команда не знает, что с чем сравнивать.
                    "group_values": [levels[0], levels[1]],
                },
                roles={"группа": grouper.name, "показатель": scale.name},
                confidence=confidence,
                caveats=caveats,
                order=20,
            )
            score = float(p_value)
            if best is None or score < best[0]:
                best = (score, scenario)
    return best[1] if best else None


def _many_groups_scenario(
    frame: pd.DataFrame, groupers: list[VariableProfile], scales: list[VariableProfile]
) -> Scenario | None:
    """Ищет самую заметную разницу между тремя и более группами."""
    best: tuple[float, Scenario] | None = None
    for grouper in groupers:
        if not 3 <= grouper.n_unique <= 10:
            continue
        for scale in scales:
            if grouper.name == scale.name:
                continue
            pair = frame[[grouper.name, scale.name]].dropna()
            if len(pair) < MIN_PAIR_CASES:
                continue
            samples = [
                group[scale.name].to_numpy(dtype=float)
                for _level, group in pair.groupby(grouper.name)
                if len(group) >= 2
            ]
            if len(samples) < 3:
                continue
            _statistic, p_value = scipy_stats.f_oneway(*samples)
            if not np.isfinite(p_value):
                continue
            # Доля объяснённой дисперсии. Если группы объясняют почти всё
            # различие, переменная-группа, скорее всего, выведена из показателя,
            # и такое сравнение бессодержательно.
            combined = np.concatenate(samples)
            total_variance = float(combined.var(ddof=1)) * (len(combined) - 1)
            if total_variance <= 0:
                continue
            between = sum(
                len(sample) * (sample.mean() - combined.mean()) ** 2 for sample in samples
            )
            eta_squared = between / total_variance
            if eta_squared >= 0.8:
                continue
            why = (
                f"{_plural(grouper.n_unique, 'группа', 'группы', 'групп')} по "
                f"«{grouper.label or grouper.name}»: {_format_p(p_value)}, "
                f"всего случаев {len(pair)}"
            )
            scenario = Scenario(
                key="compare_groups",
                title="Сравнить несколько групп",
                question=(
                    f"Отличаются ли группы по «{grouper.label or grouper.name}» "
                    f"по показателю «{scale.label or scale.name}»?"
                ),
                why=why,
                procedure="anova",
                params={"dependent": [scale.name], "factor": grouper.name},
                roles={"группа": grouper.name, "показатель": scale.name},
                confidence="подходит" if p_value < ALPHA else "возможно",
                caveats=[
                    "Дисперсионный анализ сравнивает средние; для попарных "
                    "сравнений нужны апостериорные тесты — они есть в выводе."
                ],
                order=40,
            )
            score = float(p_value)
            if best is None or score < best[0]:
                best = (score, scenario)
    return best[1] if best else None


def _correlation_scenario(
    frame: pd.DataFrame, scales: list[VariableProfile]
) -> Scenario | None:
    """Ищет самую заметную связь двух количественных показателей."""
    best: tuple[float, Scenario] | None = None
    for index, first in enumerate(scales):
        for second in scales[index + 1 :]:
            pair = frame[[first.name, second.name]].dropna()
            if len(pair) < MIN_PAIR_CASES:
                continue
            left = pair[first.name].to_numpy(dtype=float)
            right = pair[second.name].to_numpy(dtype=float)
            if np.std(left) == 0 or np.std(right) == 0:
                continue
            coefficient, p_value = scipy_stats.pearsonr(left, right)
            if not np.isfinite(coefficient):
                continue
            direction = "прямая" if coefficient > 0 else "обратная"
            why = (
                f"связь {direction}: r = {coefficient:.3f}, {_format_p(p_value)}, "
                f"случаев {len(pair)}"
            )
            scenario = Scenario(
                key="correlation",
                title="Проверить связь двух показателей",
                question=(
                    f"Связаны ли «{first.label or first.name}» и "
                    f"«{second.label or second.name}»?"
                ),
                why=why,
                procedure="correlations",
                params={"variables": [first.name, second.name], "method": "pearson"},
                roles={"показатель 1": first.name, "показатель 2": second.name},
                confidence="подходит" if p_value < ALPHA else "возможно",
                caveats=_correlation_caveats(first, second),
                order=30,
            )
            # Сортируем по силе связи, а не по значимости: на большой выборке
            # значимым становится и слабая связь.
            score = -abs(float(coefficient))
            if best is None or score < best[0]:
                best = (score, scenario)
    return best[1] if best else None


def _crosstabs_scenario(
    frame: pd.DataFrame, categories: list[VariableProfile]
) -> Scenario | None:
    """Ищет самую сильную связь двух категориальных переменных."""
    best: tuple[float, Scenario] | None = None
    for index, first in enumerate(categories):
        for second in categories[index + 1 :]:
            pair = frame[[first.name, second.name]].dropna()
            if len(pair) < MIN_PAIR_CASES:
                continue
            table = pd.crosstab(pair[first.name], pair[second.name]).to_numpy()
            if table.shape[0] < 2 or table.shape[1] < 2:
                continue
            strength = _cramers_v(table)
            if not np.isfinite(strength):
                continue
            try:
                _chi2, p_value, _dof, _expected = scipy_stats.chi2_contingency(table)
            except ValueError:
                continue
            if not np.isfinite(p_value):
                continue
            why = (
                f"V Крамера = {strength:.3f}, {_format_p(p_value)}, "
                f"таблица {table.shape[0]}×{table.shape[1]}, случаев {len(pair)}"
            )
            scenario = Scenario(
                key="crosstabs",
                title="Сопоставить две категории",
                question=(
                    f"Связаны ли «{first.label or first.name}» и "
                    f"«{second.label or second.name}»?"
                ),
                why=why,
                procedure="crosstabs",
                params={"row_vars": [first.name], "col_vars": [second.name]},
                roles={"строка": first.name, "столбец": second.name},
                confidence="подходит" if p_value < ALPHA else "возможно",
                caveats=[
                    "Хи-квадрат надёжен, когда ожидаемые частоты не меньше 5; "
                    "в выводе есть строка с их числом."
                ],
                order=50,
            )
            score = -strength
            if best is None or score < best[0]:
                best = (score, scenario)
    return best[1] if best else None


def _reliability_scenario(
    frame: pd.DataFrame, profile: DatasetProfile
) -> Scenario | None:
    """Предлагает проверить согласованность пунктов анкеты."""
    items = _questionnaire_group(profile)
    if items is None:
        return None
    names, low, high = items
    data = frame[names].dropna()
    if len(data) < MIN_PAIR_CASES:
        return None
    alpha = cronbach_alpha(data.to_numpy(dtype=float))
    if not np.isfinite(alpha):
        return None
    quality = (
        "высокая"
        if alpha >= 0.8
        else "приемлемая"
        if alpha >= 0.7
        else "низкая"
    )
    return Scenario(
        key="reliability",
        title="Проверить согласованность анкеты",
        question=(
            f"Измеряют ли "
            f"{_plural(len(names), 'пункт', 'пункта', 'пунктов')} с ответами от "
            f"{low:g} до {high:g} одно и то же?"
        ),
        why=(
            f"найдена группа из {len(names)} однотипных пунктов; "
            f"альфа Кронбаха = {alpha:.3f} — согласованность {quality}, "
            f"полных ответов {len(data)}"
        ),
        procedure="reliability",
        params={"items": names, "model": "alpha"},
        roles={f"пункт {number}": name for number, name in enumerate(names[:4], start=1)},
        confidence="подходит",
        caveats=[
            "Альфа растёт с числом пунктов, поэтому высокое значение само по себе "
            "не доказывает одномерность: посмотрите, не поднимает ли альфу "
            "удаление отдельного пункта."
        ],
        order=10,
    )


def _questionnaire_group(
    profile: DatasetProfile,
) -> tuple[list[str], float, float] | None:
    """Самая крупная группа однотипных пунктов анкеты."""
    groups: dict[tuple[float, float], list[str]] = {}
    for variable in profile.likert_items:
        key = (variable.min_value or 0.0, variable.max_value or 0.0)
        groups.setdefault(key, []).append(variable.name)
    candidates = [
        (names, low, high)
        for (low, high), names in groups.items()
        if len(names) >= 3
    ]
    if not candidates:
        return None
    names, low, high = max(candidates, key=lambda item: len(item[0]))
    return names, low, high


def _describe_scenario(profile: DatasetProfile) -> Scenario:
    """Описать выборку - подходит всегда и всегда стоит первым."""
    # Только числовые переменные: описательные статистики считают средние, и
    # текстовая переменная («Мужской»/«Женский» словами, как их выгружает Google
    # Forms) валит проверку параметров. Человек вместо расчёта видел «Проверьте
    # параметры... - string» и не понимал, что делать. Для текстовых категорий
    # есть «Частоты».
    numeric_groups = [
        variable for variable in profile.groupers if variable.var_type is VarType.NUMERIC
    ]
    groups = [variable.name for variable in numeric_groups[:4]]
    scales = [variable.name for variable in profile.scales[:4]]
    return Scenario(
        key="describe",
        title="Описать выборку",
        question="Кто и что попал в данные?",
        why=(
            f"{profile.n_cases} случаев, {profile.n_variables} переменных; "
            f"можно описать {_plural(len(groups), 'категорию', 'категории', 'категорий')} "
            f"и {_plural(len(scales), 'показатель', 'показателя', 'показателей')}"
        ),
        procedure="descriptives",
        params={"variables": groups + scales},
        roles={"описать": ", ".join(groups + scales)},
        confidence="подходит",
        caveats=[],
        order=0,
    )


def _plural(number: int, one: str, few: str, many: str) -> str:
    """Согласует существительное с числом: 1 пункт, 2 пункта, 5 пунктов.

    Без этого подсказки читаются как машинный перевод («измеряют ли 4 пунктов»),
    а программа адресована в том числе людям, которые не занимаются статистикой
    и судят о качестве по языку.
    """
    remainder = abs(number) % 100
    if 11 <= remainder <= 14:
        return f"{number} {many}"
    last = remainder % 10
    if last == 1:
        return f"{number} {one}"
    if 2 <= last <= 4:
        return f"{number} {few}"
    return f"{number} {many}"


def _level_label(frame: pd.DataFrame, name: str, level: Any) -> str:
    """Название категории из меток значений, если они заданы."""
    labels = getattr(frame, "attrs", {}).get("value_labels", {})
    label = labels.get(name, {}).get(level)
    return str(label) if label else f"{level:g}" if isinstance(level, float) else str(level)


def _format_p(p_value: float) -> str:
    """Значимость в привычном виде."""
    if p_value < 0.001:
        return "p < 0,001"
    return f"p = {p_value:.3f}".replace(".", ",")


def _normality_caveats(
    first: np.ndarray, second: np.ndarray, variable: str
) -> list[str]:
    """Предупреждения о применимости критерия Стьюдента."""
    caveats = [
        "Указан вариант с поправкой Уэлча: он не требует равенства дисперсий."
    ]
    for name, sample in (("первой", first), ("второй", second)):
        if len(sample) >= 8 and len(np.unique(sample)) >= 4:
            try:
                _statistic, p_value = scipy_stats.shapiro(sample)
            except (ValueError, TypeError):
                continue
            if np.isfinite(p_value) and p_value <= ALPHA:
                caveats.append(
                    f"В {name} группе распределение «{variable}» отличается от "
                    "нормального — стоит посмотреть и на критерий Манна-Уитни, "
                    "он есть среди непараметрических."
                )
                break
    return caveats


def _correlation_caveats(
    first: VariableProfile, second: VariableProfile
) -> list[str]:
    """Предупреждения о применимости корреляции Пирсона."""
    caveats = [
        "Корреляция показывает связь, но не доказывает причину: возможна третья "
        "переменная, влияющая на обе."
    ]
    not_normal = [
        variable.name
        for variable in (first, second)
        if variable.is_normal is False
    ]
    if not_normal:
        caveats.append(
            "Распределение «" + "», «".join(not_normal) + "» отличается от "
            "нормального — сравните с ранговой корреляцией (Спирмен)."
        )
    return caveats


def suggest_scenarios(
    dataset: Dataset,
    profile: DatasetProfile | None = None,
    limit: int | None = None,
) -> list[Scenario]:
    """Предлагает сценарии исследования для загруженных данных.

    Сценарии упорядочены по полезности: сначала описание выборки, затем проверка
    анкеты, затем сравнения и связи. У каждого подставлены конкретные переменные
    и объяснено, почему он предложен.
    """
    if dataset is None or not dataset.names():
        return []
    profile = profile or profile_dataset(dataset)

    usable = profile.usable
    if not usable:
        return []

    names = [variable.name for variable in usable]
    frame = _frames(dataset, names)
    # Метки значений нужны для человеческих подписей групп в объяснениях.
    frame.attrs["value_labels"] = {
        variable.name: dict(dataset.var(variable.name).value_labels) for variable in usable
    }

    scales = _candidates(profile, profile.scales)
    groupers = _candidates(profile, profile.groupers)
    categories = _candidates(profile, profile.categories)

    scenarios: list[Scenario] = [_describe_scenario(profile)]
    for builder in (
        lambda: _reliability_scenario(frame, profile),
        lambda: _two_group_scenario(frame, groupers, scales),
        lambda: _correlation_scenario(frame, scales),
        lambda: _many_groups_scenario(frame, groupers, scales),
        lambda: _crosstabs_scenario(frame, categories),
    ):
        scenario = builder()
        if scenario is not None:
            scenarios.append(scenario)

    scenarios.sort(key=lambda scenario: scenario.order)
    # Последняя проверка: сценарий, который на этих данных не выполнится, в
    # подсказках не показывается. Человек нажимает «Выполнить» и ждёт расчёт, а
    # не сообщение о неверных параметрах; подсказка, которая не работает, хуже
    # отсутствующей подсказки.
    runnable = [
        scenario
        for scenario in scenarios
        if _runnable(dataset, scenario.procedure, scenario.params)
    ]
    if limit is not None:
        runnable = runnable[:limit]
    return runnable


def _runnable(dataset: Dataset, procedure: str, params: dict[str, Any]) -> bool:
    """Выполним ли сценарий на этих данных (без самого расчёта)."""
    from winnow.stats.engine import REGISTRY_BY_KEY

    info = REGISTRY_BY_KEY.get(procedure)
    if info is None:
        return False
    try:
        info.command_type(dataset=dataset, **params).validate()
    except Exception:
        return False
    return True


def format_scenarios(scenarios: list[Scenario]) -> str:
    """Текстовое представление подсказок - для консоли и проверки без интерфейса."""
    if not scenarios:
        return "Подсказать нечего: в наборе нет переменных, пригодных для анализа."
    lines: list[str] = []
    for number, scenario in enumerate(scenarios, start=1):
        mark = "подходит" if scenario.is_confident else "возможно"
        lines.append(f"{number}. {scenario.title} — {mark}")
        lines.append(f"   Вопрос: {scenario.question}")
        lines.append(f"   Почему: {scenario.why}")
        if scenario.roles:
            roles = "; ".join(f"{role}: {name}" for role, name in scenario.roles.items())
            lines.append(f"   Переменные: {roles}")
        for caveat in scenario.caveats:
            lines.append(f"   Учтите: {caveat}")
        lines.append("")
    return "\n".join(lines).rstrip()


__all__ = ["Scenario", "format_scenarios", "suggest_scenarios"]
