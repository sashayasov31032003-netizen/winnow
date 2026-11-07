"""Профиль данных: что представляет собой загруженный набор.

Зачем это нужно. Опытный исследователь, открыв базу, сразу видит, что с ней
делать. Начинающий видит сто три переменные с именами вида «воп17» и не знает,
с чего начать. Профиль - это машинное «понимание» набора: какие переменные
годатся в группы, какие являются показателями, где номер респондента, а где
пункт анкеты, сколько пропусков и где выбросы.

Работает БЕЗ интерфейса: на входе набор данных, на выходе структура. Поэтому
профиль проверяется тестами обычным образом, а интерфейс лишь показывает то,
что здесь посчитано.

Важное правило: профиль ничего не решает за пользователя. Он помечает признаки
(«похоже на идентификатор»), а не меняет метаданные набора.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, VarType

# Сколько уникальных значений считается «категориями», а не измерением.
MAX_CATEGORIES = 12
# Минимальный размер группы, чтобы сравнение групп имело смысл.
MIN_GROUP_SIZE = 2
# Ниже этого числа случаев статистические выводы шаткие, о чём предупреждаем.
SMALL_SAMPLE = 30
# Много пропусков - повод проверить, не систематический ли это пропуск.
HIGH_MISSING_SHARE = 0.3
# Для проверки нормальности нужно хотя бы столько наблюдений.
MIN_FOR_NORMALITY = 8
# Столько переменных с одинаковым набором ответов уже похоже на анкету.
QUESTIONNAIRE_MIN_ITEMS = 3


@dataclass
class VariableProfile:
    """Что известно об одной переменной."""

    name: str
    label: str
    var_type: VarType
    measure: Measure
    n_cases: int
    n_missing: int
    n_unique: int
    # Признаки ролей.
    is_identifier: bool = False
    is_constant: bool = False
    is_binary: bool = False
    is_likert_like: bool = False
    can_compare_groups: bool = False
    # Похоже на вопрос «выберите подходящее»: у ответивших стоит единица, а
    # пропуск означает «не выбрано».
    looks_like_checkbox: bool = False
    # Единственное непустое значение (для констант).
    constant_value: float | None = None
    # Числовые свойства (только для количественных).
    is_normal: bool | None = None
    skewness: float | None = None
    n_outliers: int = 0
    min_value: float | None = None
    max_value: float | None = None

    @property
    def missing_share(self) -> float:
        return self.n_missing / self.n_cases if self.n_cases else 0.0

    @property
    def is_usable(self) -> bool:
        """Годится ли переменная для анализа вообще."""
        return not self.is_constant and not self.is_identifier

    @property
    def is_scale(self) -> bool:
        """Количественный показатель: объявлен количественным И есть что измерять.

        Одного объявленного уровня измерения мало. В файлах SPSS (и в чужих
        выгрузках) количественной часто помечена переменная с двумя значениями -
        например, возраст, перекодированный в «младшее/среднее поколение». Такая
        переменная не показатель, а группа: средние по двум значениям считать
        можно, но это уже сравнение групп, а не измерение.
        """
        return (
            self.measure is Measure.SCALE
            and self.var_type is VarType.NUMERIC
            and self.n_unique > MAX_CATEGORIES
        )

    @property
    def role(self) -> str:
        """Роль переменной человеческим языком - для интерфейса."""
        if self.looks_like_checkbox:
            return "отметка «выбрано»"
        if self.is_constant:
            return "константа"
        if self.is_identifier:
            return "идентификатор"
        if self.is_binary or self.measure is Measure.NOMINAL:
            return "категория"
        if self.measure is Measure.ORDINAL:
            return "порядковая"
        return "показатель"

    def summary(self) -> str:
        """Одна строка для списка переменных."""
        parts = [self.role, f"уникальных: {self.n_unique}"]
        if self.n_missing:
            parts.append(f"пропусков: {self.n_missing} ({self.missing_share:.0%})")
        if self.is_normal is not None:
            parts.append("распределение близко к нормальному" if self.is_normal else "распределение не нормальное")
        if self.n_outliers:
            parts.append(f"выбросов: {self.n_outliers}")
        return ", ".join(parts)


@dataclass
class DatasetProfile:
    """Профиль всего набора."""

    n_cases: int
    n_variables: int
    variables: list[VariableProfile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Переменные-идентификаторы: нужны, чтобы исключать их из подсказок.
    identifiers: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)
    # Вопросы «выберите подходящее»: единица у ответивших, пропуск у остальных.
    checkboxes: list[str] = field(default_factory=list)

    def by_name(self, name: str) -> VariableProfile | None:
        for variable in self.variables:
            if variable.name == name:
                return variable
        return None

    @property
    def usable(self) -> list[VariableProfile]:
        """Переменные, пригодные для анализа."""
        return [variable for variable in self.variables if variable.is_usable]

    @property
    def scales(self) -> list[VariableProfile]:
        """Количественные показатели."""
        return [variable for variable in self.usable if variable.is_scale]

    @property
    def categories(self) -> list[VariableProfile]:
        """Категориальные и порядковые переменные, а также объявленные
        количественными, но имеющие мало градаций."""
        return [variable for variable in self.usable if not variable.is_scale]

    @property
    def groupers(self) -> list[VariableProfile]:
        """Переменные, по которым можно сравнивать группы."""
        return [variable for variable in self.usable if variable.can_compare_groups]

    @property
    def likert_items(self) -> list[VariableProfile]:
        """Пункты анкет: целые числа в узком диапазоне."""
        return [variable for variable in self.usable if variable.is_likert_like]

    def with_missing(self, share: float = HIGH_MISSING_SHARE) -> list[VariableProfile]:
        return [variable for variable in self.variables if variable.missing_share >= share]


def _is_identifier(series: pd.Series, values: pd.Series) -> bool:
    """Похожа ли переменная на номер случая, а не на показатель.

    Признак: целые значения, каждое встречается ровно один раз. Такая переменная
    не измеряет ничего - это сквозная нумерация строк.
    """
    if len(values) < 10 or values.nunique() != len(values):
        return False
    try:
        numbers = values.astype(float)
    except (TypeError, ValueError):
        return False
    if not np.all(np.isfinite(numbers)):
        return False
    if not np.allclose(numbers, np.round(numbers)):
        return False
    return True


def _outlier_count(values: pd.Series) -> int:
    """Число выбросов по правилу межквартильного размаха."""
    if len(values) < MIN_FOR_NORMALITY:
        return 0
    q1, q3 = values.quantile(0.25), values.quantile(0.75)
    spread = q3 - q1
    if spread <= 0:
        return 0
    lower, upper = q1 - 1.5 * spread, q3 + 1.5 * spread
    return int(((values < lower) | (values > upper)).sum())


def _normality(values: pd.Series) -> bool | None:
    """Проверка нормальности критерием Шапиро-Уилка.

    Возвращает None, когда проверить нельзя: мало наблюдений или все значения
    одинаковые (критерий на таких данных не определён).
    """
    if len(values) < MIN_FOR_NORMALITY or values.nunique() < 4:
        return None
    try:
        _statistic, p_value = scipy_stats.shapiro(values.astype(float))
    except (ValueError, TypeError):
        return None
    if not np.isfinite(p_value):
        return None
    return bool(p_value > 0.05)


def profile_variable(dataset: Dataset, name: str) -> VariableProfile:
    """Считает профиль одной переменной."""
    variable = dataset.var(name)
    series = dataset.analysis_frame([name])[name]
    total = len(series)
    values = series.dropna()
    n_missing = total - len(values)
    n_unique = int(values.nunique())

    profile = VariableProfile(
        name=name,
        label=variable.label,
        var_type=variable.var_type,
        measure=variable.measure,
        n_cases=total,
        n_missing=n_missing,
        n_unique=n_unique,
    )
    profile.is_constant = n_unique <= 1
    profile.is_identifier = _is_identifier(series, values)
    profile.is_binary = n_unique == 2
    if profile.is_constant and len(values) > 0:
        # Одно РАЗЛИЧНОЕ значение, а не один заполненный случай: у вопросов
        # «выберите подходящее» заполнены десятки случаев, но все одним и тем же
        # числом.
        try:
            profile.constant_value = float(values.iloc[0])
        except (TypeError, ValueError):
            profile.constant_value = None
    # Вопрос «выберите подходящее»: у ответивших единица, остальные пропущены.
    # Такая переменная сейчас бесполезна - она константа, - но стоит заменить
    # пропуски нулями, и она станет обычной отметкой 0/1.
    profile.looks_like_checkbox = bool(
        profile.is_constant
        and not profile.is_identifier
        and len(values) >= 3
        and profile.missing_share >= 0.2
        and profile.constant_value is not None
        and profile.constant_value in (0.0, 1.0)
    )

    numeric = variable.var_type is VarType.NUMERIC and len(values) > 0
    if numeric:
        numbers = values.astype(float)
        finite = numbers[np.isfinite(numbers)]
        if len(finite):
            profile.min_value = float(finite.min())
            profile.max_value = float(finite.max())
        whole = bool(len(finite)) and bool(np.allclose(finite, np.round(finite)))
        # Пункт шкалы - это порядковая переменная: целые числа в узком диапазоне.
        # Номинальные коды (пол, город) в узкий диапазон тоже попадают, но
        # ступеней в них нет, поэтому они сюда не относятся.
        profile.is_likert_like = (
            whole
            and variable.measure is Measure.ORDINAL
            and 3 <= n_unique <= 10
            and profile.min_value is not None
            and profile.min_value >= 0
            and profile.max_value is not None
            and profile.max_value <= 10
        )
        if profile.is_scale and n_unique > 2:
            try:
                profile.skewness = float(values.skew())
            except (ValueError, TypeError):
                profile.skewness = None
            profile.is_normal = _normality(values)
            profile.n_outliers = _outlier_count(values)

    # По переменной можно делить на группы, если категорий немного и в каждой
    # есть хотя бы пара случаев: иначе сравнивать нечего.
    if not profile.is_identifier and not profile.is_constant:
        if 2 <= n_unique <= MAX_CATEGORIES:
            sizes = values.value_counts()
            profile.can_compare_groups = bool(
                len(sizes) and int(sizes.min()) >= MIN_GROUP_SIZE
            )
    return profile


def _short_list(names: list[str], limit: int = 3) -> str:
    """Перечисление с многоточием: длинные списки в тексте нечитаемы."""
    shown = ", ".join(names[:limit])
    if len(names) > limit:
        shown += f" и ещё {len(names) - limit}"
    return shown


def _questionnaire_notes(profiles: list[VariableProfile]) -> list[str]:
    """Замечания про анкету: группы пунктов с одинаковым набором ответов."""
    notes: list[str] = []
    groups: dict[tuple[float, float], list[str]] = {}
    for profile in profiles:
        if not profile.is_likert_like:
            continue
        key = (profile.min_value or 0.0, profile.max_value or 0.0)
        groups.setdefault(key, []).append(profile.name)

    for (low, high), names in groups.items():
        if len(names) < QUESTIONNAIRE_MIN_ITEMS:
            continue
        notes.append(
            f"Похоже на анкету: {len(names)} переменных с ответами от {low:g} "
            f"до {high:g} ({_short_list(names)}). Их можно объединить в шкалу — "
            "меню «Масштабирование», надёжность или факторный анализ."
        )
    return notes


def profile_dataset(dataset: Dataset) -> DatasetProfile:
    """Строит профиль набора: роли переменных и замечания о качестве данных."""
    profiles = [profile_variable(dataset, name) for name in dataset.names()]
    profile = DatasetProfile(
        n_cases=len(dataset.frame),
        n_variables=len(profiles),
        variables=profiles,
    )
    profile.identifiers = [p.name for p in profiles if p.is_identifier]
    profile.constants = [p.name for p in profiles if p.is_constant]
    profile.checkboxes = [p.name for p in profiles if p.looks_like_checkbox]

    notes: list[str] = []
    if profile.n_cases < SMALL_SAMPLE:
        notes.append(
            f"Случаев мало: {profile.n_cases}. Для сравнения групп и факторного "
            f"анализа обычно нужно не меньше {SMALL_SAMPLE} — выводы будут "
            "предварительными."
        )
    if profile.identifiers:
        notes.append(
            f"Найдены переменные-идентификаторы ({_short_list(profile.identifiers)})"
            " — это номера случаев, а не показатели; в анализ их лучше не брать."
        )

    # Про вопросы «выберите подходящее» говорим раньше прочих замечаний о
    # пропусках: это не «много пропусков», а понятная и исправимая причина.
    if profile.checkboxes:
        notes.append(
            f"Похоже на вопросы «выберите подходящее»: {len(profile.checkboxes)} "
            f"переменных ({_short_list(profile.checkboxes)}) заполнены только "
            "единицами, а пропуск означает «не выбрано». Сейчас такие переменные "
            "ничего не измеряют — они константы. Чтобы их можно было "
            "анализировать, пропуски нужно заменить нулями: меню «Данные → "
            "Перекодировать» или «Вычислить переменную»."
        )

    # Одинаковые замечания про пропуски сводятся в одно: список из девяноста
    # строк подряд прочитать невозможно, а смысл в нём один.
    heavy = [
        p
        for p in profile.with_missing()
        if not p.looks_like_checkbox and not p.is_identifier
    ]
    if heavy:
        names = [p.label or p.name for p in heavy]
        notes.append(
            f"У {len(heavy)} переменных пропущено больше "
            f"{HIGH_MISSING_SHARE:.0%} значений ({_short_list(names)}). "
            "Проверьте, не связан ли пропуск с изучаемым явлением: если пропуск "
            "означает «нет» или «не ответил», это разные вещи."
        )

    other_constants = [name for name in profile.constants if name not in profile.checkboxes]
    if other_constants:
        notes.append(
            f"Переменные-константы ({_short_list(other_constants)}) одинаковы во "
            "всех случаях и в анализе не участвуют."
        )

    notes.extend(_questionnaire_notes(profiles))

    profile.notes = notes
    return profile


def format_profile(profile: DatasetProfile, limit: int | None = None) -> str:
    """Текстовое представление профиля - для консоли и проверки без интерфейса."""
    lines = [
        f"Случаев: {profile.n_cases}",
        f"Переменных: {profile.n_variables}",
        "",
    ]
    if profile.notes:
        lines.append("Замечания о данных:")
        lines.extend(f"  • {note}" for note in profile.notes)
        lines.append("")

    lines.append("Переменные:")
    shown: Any = profile.variables if limit is None else profile.variables[:limit]
    for variable in shown:
        title = f"{variable.label} [{variable.name}]" if variable.label else variable.name
        lines.append(f"  {title} — {variable.summary()}")
    if limit is not None and len(profile.variables) > limit:
        lines.append(f"  ... и ещё {len(profile.variables) - limit}")
    return "\n".join(lines)


__all__ = [
    "DatasetProfile",
    "VariableProfile",
    "format_profile",
    "profile_dataset",
    "profile_variable",
]
