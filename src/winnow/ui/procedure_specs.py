"""Декларативные описания диалогов процедур.

Смысл: чтобы добавить 20-ю процедуру, не нужно писать 20-й QDialog. Достаточно
описать поля, а окно построит winnow.ui.dialogs. Это главный приём, который
позволяет статистическому пакету расти без взрыва объёма UI-кода.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Список видов графика берётся из модуля графиков: единственный источник истины,
# иначе меню и процедура разойдутся в названиях.
from winnow.stats.charts import CHART_TYPES


class FieldKind(Enum):
    VARIABLE_LIST = "variable_list"   # перенос переменных (как в SPSS)
    SINGLE_VARIABLE = "single"        # выпадающий список переменных
    CHECKBOX = "checkbox"             # флажок
    NUMBER = "number"                 # числовое поле
    TEXT = "text"                     # свободный текст (коды групп, выражения)
    CHOICE = "choice"                 # выпадающий список вариантов
    OPTION_GROUP = "option"           # группа флажков


class VarFilter(Enum):
    """Какие переменные показывать в поле."""

    ANY = "any"
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"


@dataclass
class FieldSpec:
    name: str
    label: str
    kind: FieldKind
    var_filter: VarFilter = VarFilter.ANY
    default: Any = None
    choices: list[tuple[str, Any]] = field(default_factory=list)
    minimum: float = -1e9
    maximum: float = 1e9
    step: float = 1.0
    decimals: int = 2
    tooltip: str = ""
    row: int = 0
    column: int = 0


@dataclass
class DialogSpec:
    """Описание окна процедуры: заголовок, поля, сборщик команды."""

    key: str
    title: str
    fields: list[FieldSpec]
    command_type: type
    build: Any  # Callable[[dict[str, Any], Dataset], Command]
    description: str = ""


# --------------------------------------------------------------------------
# Сборщики команд: превращают значения виджетов в объект Command.
# --------------------------------------------------------------------------


def build_descriptives(values: dict[str, Any], dataset):
    from winnow.stats.command import DescriptivesCommand

    return DescriptivesCommand(
        dataset=dataset,
        variables=list(values.get("variables") or []),
        statistics=list(values.get("statistics") or ["n", "missing", "mean", "std"]),
        confidence=float(values.get("confidence") or 0.0),
        split_by=values.get("split_by") or None,
    )


def build_frequencies(values: dict[str, Any], dataset):
    from winnow.stats.command import FrequenciesCommand

    return FrequenciesCommand(
        dataset=dataset,
        variables=list(values.get("variables") or []),
        show_counts=bool(values.get("show_counts", True)),
        show_percent=bool(values.get("show_percent", True)),
        show_valid_percent=bool(values.get("show_valid_percent", True)),
        show_cumulative=bool(values.get("show_cumulative", False)),
        statistics=list(values.get("statistics") or []),
    )


def build_crosstabs(values: dict[str, Any], dataset):
    from winnow.stats.command import CrosstabsCommand

    return CrosstabsCommand(
        dataset=dataset,
        row_vars=list(values.get("row_vars") or []),
        col_vars=list(values.get("col_vars") or []),
        chi_square=bool(values.get("chi_square", True)),
        phi_cramers_v=bool(values.get("phi_cramers_v", True)),
        expected=bool(values.get("expected", False)),
        residuals=bool(values.get("residuals", False)),
        count=bool(values.get("count", True)),
        row_percent=bool(values.get("row_percent", False)),
        col_percent=bool(values.get("col_percent", False)),
        total_percent=bool(values.get("total_percent", False)),
    )


def _parse_group_values(raw: Any) -> list[float]:
    """Разбирает строку "1, 2" в список кодов групп.

    Ввод пользователя непредсказуем (запятая, точка с запятой, пробелы), поэтому
    разбор терпимый, а на нечисловой ввод отвечает понятной ошибкой.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(v) for v in raw]
    text = str(raw).replace(";", ",").strip()
    if not text:
        return []
    values: list[float] = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            values.append(float(chunk))
        except ValueError:
            raise ValueError(f"Код группы должен быть числом, получено: {chunk!r}") from None
    return values


def build_ttest(values: dict[str, Any], dataset):
    from winnow.stats.command import TTestCommand

    return TTestCommand(
        dataset=dataset,
        kind=values.get("kind", "independent"),
        test_vars=list(values.get("test_vars") or []),
        group_var=values.get("group_var") or None,
        group_values=_parse_group_values(values.get("group_values")),
        pair_with=list(values.get("pair_with") or []),
        test_value=float(values.get("test_value") or 0.0),
        confidence=float(values.get("confidence") or 0.95),
        effect_size=bool(values.get("effect_size", True)),
    )


def build_anova(values: dict[str, Any], dataset):
    from winnow.stats.command import AnovaCommand

    return AnovaCommand(
        dataset=dataset,
        dependent=list(values.get("dependent") or []),
        factor=values.get("factor") or None,
        post_hoc=values.get("post_hoc", "tukey"),
        confidence=float(values.get("confidence") or 0.95),
        descriptives=bool(values.get("descriptives", True)),
        homogeneity=bool(values.get("homogeneity", True)),
        welch=bool(values.get("welch", True)),
        effect_size=bool(values.get("effect_size", True)),
    )


def build_nonparametric(values: dict[str, Any], dataset):
    from winnow.stats.command import NonparametricCommand

    return NonparametricCommand(
        dataset=dataset,
        kind=values.get("kind", "independent"),
        test_vars=list(values.get("test_vars") or []),
        pair_with=list(values.get("pair_with") or []),
        group_var=values.get("group_var") or None,
        method=values.get("method", "auto"),
        descriptives=bool(values.get("descriptives", True)),
        confidence=float(values.get("confidence") or 0.95),
    )


def build_linear_regression(values: dict[str, Any], dataset):
    from winnow.stats.command import LinearRegressionCommand

    return LinearRegressionCommand(
        dataset=dataset,
        dependent=values.get("dependent") or None,
        predictors=list(values.get("predictors") or []),
        confidence=float(values.get("confidence") or 0.95),
        diagnostics=bool(values.get("diagnostics", True)),
        standardize=bool(values.get("standardize", False)),
        constant=bool(values.get("constant", True)),
    )


def _parse_reference_value(raw: Any) -> Any:
    """Приводит значение отклика из текстового поля к типу данных.

    Поле в диалоге текстовое, поэтому «1» приходит строкой, а в данных это
    число. Без приведения типов проверка «значение есть в данных» не сработает.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        number = float(text.replace(",", "."))
        return int(number) if number.is_integer() else number
    except ValueError:
        return text


def build_logistic_regression(values: dict[str, Any], dataset):
    from winnow.stats.command import LogisticRegressionCommand

    return LogisticRegressionCommand(
        dataset=dataset,
        dependent=values.get("dependent") or None,
        predictors=list(values.get("predictors") or []),
        confidence=float(values.get("confidence") or 0.95),
        reference_value=_parse_reference_value(values.get("reference_value")),
    )


def build_graph(values: dict[str, Any], dataset):
    from winnow.stats.charts import ChartCommand

    return ChartCommand(
        dataset=dataset,
        kind=values.get("kind", "histogram"),
        variables=list(values.get("variables") or []),
        category=values.get("category") or None,
        bins=int(values.get("bins") or 0),
        show_normal=bool(values.get("show_normal", False)),
        show_mean=bool(values.get("show_mean", True)),
        title=str(values.get("title") or "").strip(),
    )


def build_reliability(values: dict[str, Any], dataset):
    from winnow.stats.command import ReliabilityCommand

    return ReliabilityCommand(
        dataset=dataset,
        items=list(values.get("items") or []),
        model=values.get("model", "alpha"),
        item_statistics=bool(values.get("item_statistics", True)),
        scale_statistics=bool(values.get("scale_statistics", True)),
        inter_item=bool(values.get("inter_item", False)),
    )


def build_factor(values: dict[str, Any], dataset):
    from winnow.stats.command import FactorCommand

    return FactorCommand(
        dataset=dataset,
        variables=list(values.get("variables") or []),
        method=values.get("method", "pca"),
        rotation=values.get("rotation", "varimax"),
        n_factors=int(values.get("n_factors") or 0),
        kmo=bool(values.get("kmo", True)),
        bartlett=bool(values.get("bartlett", True)),
        scree=bool(values.get("scree", True)),
        save_scores=bool(values.get("save_scores", False)),
    )


def build_compute(values: dict[str, Any], dataset):
    from winnow.stats.command import ComputeCommand

    return ComputeCommand(
        dataset=dataset,
        target=str(values.get("target") or "").strip(),
        expression=str(values.get("expression") or "").strip(),
        label=str(values.get("label") or "").strip(),
        overwrite=bool(values.get("overwrite", False)),
        decimals=int(values.get("decimals") or 2),
    )


def build_recode(values: dict[str, Any], dataset):
    """Собирает команду перекодирования.

    В обычном режиме правила задаёт отдельный диалог с таблицей
    (ui/recode_dialog.py). Но источник и имя результата описаны декларативно,
    поэтому команда собирается и здесь - так процедура проходит общие проверки
    полноты. Правила принимаются и объектами RecodeRule, и словарями: словари
    удобнее для тестов и для будущего чтения синтаксиса.
    """
    from winnow.stats.command import RecodeCommand, RecodeRule

    rules: list[RecodeRule] = []
    for raw in values.get("rules") or []:
        if isinstance(raw, RecodeRule):
            rules.append(raw)
        elif isinstance(raw, dict):
            rules.append(RecodeRule(**raw))

    return RecodeCommand(
        dataset=dataset,
        source=values.get("source") or None,
        target=str(values.get("target") or "").strip(),
        label=str(values.get("label") or "").strip(),
        overwrite=bool(values.get("overwrite", False)),
        rules=rules,
    )


def build_correlations(values: dict[str, Any], dataset):
    from winnow.stats.command import CorrelationsCommand

    return CorrelationsCommand(
        dataset=dataset,
        variables=list(values.get("variables") or []),
        method=values.get("method", "pearson"),
        two_tailed=bool(values.get("two_tailed", True)),
        flag_significant=bool(values.get("flag_significant", True)),
    )


# --------------------------------------------------------------------------
# Спецификации окон.
# --------------------------------------------------------------------------

DESCRIPTIVE_STATISTICS = [
    ("n", "N (число наблюдений)"),
    ("missing", "Пропущенные"),
    ("mean", "Среднее"),
    ("median", "Медиана"),
    ("std", "Стд. отклонение"),
    ("variance", "Дисперсия"),
    ("sem", "Стд. ошибка среднего"),
    ("min", "Минимум"),
    ("max", "Максимум"),
    ("range", "Размах"),
    ("skewness", "Асимметрия"),
    ("kurtosis", "Эксцесс"),
    ("sum", "Сумма"),
    ("mode", "Мода"),
    ("iqr", "Межквартильный размах"),
]

DIALOG_SPECS: dict[str, DialogSpec] = {
    "descriptives": DialogSpec(
        key="descriptives",
        title="Описательные статистики",
        command_type=object,
        build=build_descriptives,
        description="Среднее, медиана, разброс и форма распределения",
        fields=[
            FieldSpec(
                "variables", "Переменные:", FieldKind.VARIABLE_LIST, VarFilter.NUMERIC,
                row=0, column=0,
            ),
            FieldSpec(
                "statistics",
                "Статистики:",
                FieldKind.OPTION_GROUP,
                default=[key for key, _ in DESCRIPTIVE_STATISTICS[:12]],
                choices=DESCRIPTIVE_STATISTICS,
                row=0,
                column=1,
            ),
            FieldSpec(
                "confidence",
                "Доверительный интервал для среднего:",
                FieldKind.CHOICE,
                default=0.0,
                row=1,
                column=0,
                choices=[("не считать", 0.0), ("90%", 0.90), ("95%", 0.95), ("99%", 0.99)],
            ),
            FieldSpec(
                "split_by", "Разбить по переменной:", FieldKind.SINGLE_VARIABLE,
                VarFilter.CATEGORICAL, row=1, column=1,
            ),
        ],
    ),
    "frequencies": DialogSpec(
        key="frequencies",
        title="Частоты",
        command_type=object,
        build=build_frequencies,
        description="Распределение значений переменной",
        fields=[
            FieldSpec("variables", "Переменные:", FieldKind.VARIABLE_LIST, VarFilter.ANY,
                      row=0, column=0),
            FieldSpec("show_counts", "Частота", FieldKind.CHECKBOX, default=True,
                      row=0, column=1),
            FieldSpec("show_percent", "Процент", FieldKind.CHECKBOX, default=True,
                      row=1, column=1),
            FieldSpec("show_valid_percent", "Валидный процент", FieldKind.CHECKBOX,
                      default=True, row=2, column=1),
            FieldSpec("show_cumulative", "Накопленный процент", FieldKind.CHECKBOX,
                      default=False, row=3, column=1),
        ],
    ),
    "crosstabs": DialogSpec(
        key="crosstabs",
        title="Таблицы сопряжённости",
        command_type=object,
        build=build_crosstabs,
        description="Связь двух категориальных переменных",
        fields=[
            FieldSpec("row_vars", "Строки:", FieldKind.VARIABLE_LIST, VarFilter.CATEGORICAL,
                      row=0, column=0),
            FieldSpec("col_vars", "Столбцы:", FieldKind.VARIABLE_LIST, VarFilter.CATEGORICAL,
                      row=1, column=0),
            FieldSpec("count", "Количество", FieldKind.CHECKBOX, default=True,
                      row=0, column=1),
            FieldSpec("row_percent", "Процент по строке", FieldKind.CHECKBOX, default=True,
                      row=1, column=1),
            FieldSpec("col_percent", "Процент по столбцу", FieldKind.CHECKBOX, default=False,
                      row=2, column=1),
            FieldSpec("total_percent", "Процент от итога", FieldKind.CHECKBOX, default=False,
                      row=3, column=1),
            FieldSpec("expected", "Ожидаемая частота", FieldKind.CHECKBOX, default=False,
                      row=4, column=1),
            FieldSpec("residuals", "Остатки", FieldKind.CHECKBOX, default=False,
                      row=5, column=1),
            FieldSpec("chi_square", "Хи-квадрат Пирсона", FieldKind.CHECKBOX, default=True,
                      row=6, column=1),
            FieldSpec("phi_cramers_v", "V Крамера и Фи", FieldKind.CHECKBOX, default=True,
                      row=7, column=1),
        ],
    ),
    "ttest": DialogSpec(
        key="ttest",
        title="t-критерий",
        command_type=object,
        build=build_ttest,
        description="Сравнение средних: одна, две независимые или связанные выборки",
        fields=[
            FieldSpec(
                "kind",
                "Вид критерия:",
                FieldKind.CHOICE,
                default="independent",
                row=0,
                column=0,
                choices=[
                    ("Независимые выборки", "independent"),
                    ("Связанные выборки", "paired"),
                    ("Одна выборка", "one_sample"),
                ],
            ),
            FieldSpec("test_vars", "Проверяемые переменные:", FieldKind.VARIABLE_LIST,
                      VarFilter.NUMERIC, row=1, column=0),
            FieldSpec("group_var", "Группировать по:", FieldKind.SINGLE_VARIABLE,
                      VarFilter.CATEGORICAL, row=2, column=0),
            FieldSpec(
                "group_values",
                "Коды групп (через запятую):",
                FieldKind.TEXT,
                default="1, 2",
                row=3,
                column=0,
                tooltip="Для независимых выборок укажите два кода, например 1, 2",
            ),
            FieldSpec("pair_with", "В парах с переменными:", FieldKind.VARIABLE_LIST,
                      VarFilter.NUMERIC, row=4, column=0),
            FieldSpec(
                "test_value",
                "Проверяемое значение:",
                FieldKind.NUMBER,
                default=0.0,
                row=5,
                column=0,
                # Диапазон намеренно широкий: проверяемое значение может быть
                # любым (например, -5), а не только "от 0 до 100".
                minimum=-1e9,
                maximum=1e9,
                decimals=4,
            ),
            FieldSpec(
                "confidence",
                "Доверительный уровень:",
                FieldKind.CHOICE,
                default=0.95,
                row=0,
                column=1,
                choices=[("90%", 0.90), ("95%", 0.95), ("99%", 0.99)],
            ),
            FieldSpec("effect_size", "Размеры эффекта (d Коэна, g Хеджеса)",
                      FieldKind.CHECKBOX, default=True, row=1, column=1),
        ],
    ),
    "correlations": DialogSpec(
        key="correlations",
        title="Корреляции",
        command_type=object,
        build=build_correlations,
        description="Пирсон, Спирмен, Кендалл",
        fields=[
            FieldSpec("variables", "Переменные:", FieldKind.VARIABLE_LIST, VarFilter.NUMERIC,
                      row=0, column=0),
            FieldSpec(
                "method",
                "Метод:",
                FieldKind.CHOICE,
                default="pearson",
                row=0,
                column=1,
                choices=[
                    ("Пирсона (r)", "pearson"),
                    ("Спирмена (rho)", "spearman"),
                    ("Кендалла (tau-b)", "kendall"),
                ],
            ),
            FieldSpec("flag_significant", "Помечать значимые звёздочками",
                      FieldKind.CHECKBOX, default=True, row=1, column=1),
        ],
    ),
    "anova": DialogSpec(
        key="anova",
        title="Однофакторный дисперсионный анализ",
        command_type=object,
        build=build_anova,
        description="Сравнение средних трёх и более групп с апостериорными сравнениями",
        fields=[
            FieldSpec("dependent", "Зависимые переменные:", FieldKind.VARIABLE_LIST,
                      VarFilter.NUMERIC, row=0, column=0),
            FieldSpec("factor", "Фактор (группировка):", FieldKind.SINGLE_VARIABLE,
                      VarFilter.CATEGORICAL, row=1, column=0),
            FieldSpec(
                "post_hoc",
                "Апостериорные сравнения:",
                FieldKind.CHOICE,
                default="tukey",
                row=2,
                column=0,
                choices=[
                    ("Тьюки (HSD) - рекомендуются", "tukey"),
                    ("Бонферрони", "bonferroni"),
                    ("Холм", "holm"),
                    ("не считать", "none"),
                ],
            ),
            FieldSpec(
                "confidence",
                "Доверительный уровень:",
                FieldKind.CHOICE,
                default=0.95,
                row=3,
                column=0,
                choices=[("90%", 0.90), ("95%", 0.95), ("99%", 0.99)],
            ),
            FieldSpec("descriptives", "Описательные статистики", FieldKind.CHECKBOX,
                      default=True, row=0, column=1),
            FieldSpec("homogeneity", "Проверка однородности дисперсий (Ливинь)",
                      FieldKind.CHECKBOX, default=True, row=1, column=1),
            FieldSpec("welch", "Робастный тест Уэлча (для неравных дисперсий)",
                      FieldKind.CHECKBOX, default=True, row=2, column=1),
            FieldSpec("effect_size", "Размеры эффекта (эта- и омега-квадрат)",
                      FieldKind.CHECKBOX, default=True, row=3, column=1),
        ],
    ),
    "nonparametric": DialogSpec(
        key="nonparametric",
        title="Непараметрические критерии",
        command_type=object,
        build=build_nonparametric,
        description=(
            "Для данных, которые не подчиняются нормальному распределению, "
            "и для порядковых шкал"
        ),
        fields=[
            FieldSpec(
                "kind",
                "Вид выборок:",
                FieldKind.CHOICE,
                default="independent",
                row=0,
                column=0,
                choices=[
                    ("Независимые (разные люди)", "independent"),
                    ("Связанные (замеры до и после)", "related"),
                ],
            ),
            FieldSpec(
                "method",
                "Критерий:",
                FieldKind.CHOICE,
                default="auto",
                row=1,
                column=0,
                choices=[
                    ("Подобрать автоматически", "auto"),
                    ("U Манна-Уитни (две группы)", "mann_whitney"),
                    ("H Краскела-Уоллиса (три и более групп)", "kruskal_wallis"),
                    ("T Уилкоксона (связанные выборки)", "wilcoxon"),
                    ("Фридман (три и более связанные)", "friedman"),
                ],
            ),
            FieldSpec("test_vars", "Проверяемые переменные:", FieldKind.VARIABLE_LIST,
                      VarFilter.NUMERIC, row=2, column=0),
            FieldSpec("group_var", "Группировать по:", FieldKind.SINGLE_VARIABLE,
                      VarFilter.CATEGORICAL, row=3, column=0),
            FieldSpec(
                "pair_with",
                "Для связанных выборок - сравнить с:",
                FieldKind.VARIABLE_LIST,
                VarFilter.NUMERIC,
                row=4,
                column=0,
                tooltip="Для Фридмана укажите все связанные переменные в первом списке",
            ),
            FieldSpec("descriptives", "Описательные статистики", FieldKind.CHECKBOX,
                      default=True, row=0, column=1),
            FieldSpec(
                "confidence",
                "Уровень значимости для поправок:",
                FieldKind.CHOICE,
                default=0.95,
                row=1,
                column=1,
                choices=[("0.10", 0.90), ("0.05", 0.95), ("0.01", 0.99)],
            ),
        ],
    ),
    "linear_regression": DialogSpec(
        key="linear_regression",
        title="Линейная регрессия",
        command_type=object,
        build=build_linear_regression,
        description="Предсказание количественной переменной по нескольким другим",
        fields=[
            FieldSpec("dependent", "Зависимая переменная:", FieldKind.SINGLE_VARIABLE,
                      VarFilter.NUMERIC, row=0, column=0),
            FieldSpec("predictors", "Предикторы (независимые переменные):",
                      FieldKind.VARIABLE_LIST, VarFilter.NUMERIC, row=1, column=0),
            FieldSpec(
                "confidence",
                "Доверительный уровень:",
                FieldKind.CHOICE,
                default=0.95,
                row=2,
                column=0,
                choices=[("90%", 0.90), ("95%", 0.95), ("99%", 0.99)],
            ),
            FieldSpec("diagnostics", "Диагностика: коллинеарность и остатки",
                      FieldKind.CHECKBOX, default=True, row=0, column=1),
            FieldSpec("standardize", "Стандартизованные коэффициенты (бета)",
                      FieldKind.CHECKBOX, default=True, row=1, column=1),
            FieldSpec("constant", "Включать свободный член", FieldKind.CHECKBOX,
                      default=True, row=2, column=1),
        ],
    ),
    "logistic_regression": DialogSpec(
        key="logistic_regression",
        title="Логистическая регрессия",
        command_type=object,
        build=build_logistic_regression,
        description=(
            "Предсказание события «да/нет»: отклик должен принимать два значения"
        ),
        fields=[
            FieldSpec("dependent", "Зависимая переменная (два значения):",
                      FieldKind.SINGLE_VARIABLE, VarFilter.CATEGORICAL, row=0, column=0),
            FieldSpec("predictors", "Предикторы:", FieldKind.VARIABLE_LIST,
                      VarFilter.NUMERIC, row=1, column=0),
            FieldSpec(
                "reference_value",
                "Считать событием значение:",
                FieldKind.TEXT,
                default="",
                row=2,
                column=0,
                tooltip="Оставьте пустым - событием будет большее из двух значений",
            ),
            FieldSpec(
                "confidence",
                "Доверительный уровень:",
                FieldKind.CHOICE,
                default=0.95,
                row=0,
                column=1,
                choices=[("90%", 0.90), ("95%", 0.95), ("99%", 0.99)],
            ),
        ],
    ),
    "compute": DialogSpec(
        key="compute",
        title="Вычислить переменную",
        command_type=object,
        build=build_compute,
        description=(
            "Новая переменная по выражению. Доступны переменные набора, "
            "арифметика, сравнения и функции: abs, min, max, round, sqrt, log, exp"
        ),
        fields=[
            FieldSpec(
                "target",
                "Имя новой переменной:",
                FieldKind.TEXT,
                default="",
                row=0,
                column=0,
                tooltip="Латиницей, например income_thousands",
            ),
            FieldSpec(
                "expression",
                "Выражение:",
                FieldKind.TEXT,
                default="",
                row=1,
                column=0,
                tooltip="Например: income / 1000 или age >= 30 and gender == 1",
            ),
            FieldSpec(
                "label",
                "Метка переменной:",
                FieldKind.TEXT,
                default="",
                row=2,
                column=0,
                tooltip="Необязательно: как переменная будет называться в отчётах",
            ),
            FieldSpec(
                "decimals",
                "Знаков после запятой:",
                FieldKind.NUMBER,
                default=2.0,
                row=3,
                column=0,
                minimum=0,
                maximum=10,
                step=1,
                decimals=0,
            ),
            FieldSpec(
                "overwrite",
                "Перезаписать переменную с таким именем",
                FieldKind.CHECKBOX,
                default=False,
                row=0,
                column=1,
            ),
        ],
    ),
    "recode": DialogSpec(
        key="recode",
        title="Перекодировать в новую переменную",
        command_type=object,
        build=build_recode,
        description="Превращение значений в новые: объединение категорий, диапазоны",
        # Поля описывают только источник и имя результата: сами правила - это
        # таблица, и её строит отдельный диалог (ui/recode_dialog.py).
        fields=[
            FieldSpec("source", "Переменная для перекодирования:",
                      FieldKind.SINGLE_VARIABLE, VarFilter.ANY, row=0, column=0),
            FieldSpec("target", "Имя новой переменной:", FieldKind.TEXT,
                      default="", row=1, column=0),
            FieldSpec("label", "Метка переменной:", FieldKind.TEXT,
                      default="", row=2, column=0),
            FieldSpec("overwrite", "Перезаписать переменную с таким именем",
                      FieldKind.CHECKBOX, default=False, row=0, column=1),
        ],
    ),
    "reliability": DialogSpec(
        key="reliability",
        title="Анализ надёжности",
        command_type=object,
        build=build_reliability,
        description=(
            "Проверка, что пункты опросника измеряют одно и то же: "
            "альфа Кронбаха и статистики пунктов"
        ),
        fields=[
            FieldSpec("items", "Пункты шкалы:", FieldKind.VARIABLE_LIST,
                      VarFilter.NUMERIC, row=0, column=0),
            FieldSpec(
                "model",
                "Модель:",
                FieldKind.CHOICE,
                default="alpha",
                row=1,
                column=0,
                choices=[
                    ("Альфа Кронбаха (рекомендуется)", "alpha"),
                    ("Надёжность половин", "split"),
                    ("Параллельная модель", "parallel"),
                ],
            ),
            FieldSpec("item_statistics", "Статистики пунктов и «альфа при удалении»",
                      FieldKind.CHECKBOX, default=True, row=0, column=1),
            FieldSpec("scale_statistics", "Статистики шкалы", FieldKind.CHECKBOX,
                      default=True, row=1, column=1),
            FieldSpec("inter_item", "Межпунктовые корреляции", FieldKind.CHECKBOX,
                      default=False, row=2, column=1),
        ],
    ),
    "factor": DialogSpec(
        key="factor",
        title="Факторный анализ",
        command_type=object,
        build=build_factor,
        description=(
            "Сколько скрытых конструктов стоит за пунктами и какие пункты "
            "к какому относятся"
        ),
        fields=[
            FieldSpec("variables", "Переменные:", FieldKind.VARIABLE_LIST,
                      VarFilter.NUMERIC, row=0, column=0),
            FieldSpec(
                "method",
                "Метод выделения:",
                FieldKind.CHOICE,
                default="pca",
                row=1,
                column=0,
                choices=[
                    ("Главные компоненты", "pca"),
                    ("Главные факторы", "ml"),
                ],
            ),
            FieldSpec(
                "rotation",
                "Вращение:",
                FieldKind.CHOICE,
                default="varimax",
                row=2,
                column=0,
                choices=[
                    ("Varimax (ортогональное)", "varimax"),
                    ("Quartimax (ортогональное)", "quartimax"),
                    ("Promax (косоугольное)", "promax"),
                    ("без вращения", "none"),
                ],
            ),
            FieldSpec(
                "n_factors",
                "Число факторов (0 - по критерию Кайзера):",
                FieldKind.NUMBER,
                default=0.0,
                row=3,
                column=0,
                minimum=0,
                maximum=50,
                step=1,
                decimals=0,
            ),
            FieldSpec("kmo", "Мера адекватности KMO", FieldKind.CHECKBOX,
                      default=True, row=0, column=1),
            FieldSpec("bartlett", "Критерий сферичности Бартлетта", FieldKind.CHECKBOX,
                      default=True, row=1, column=1),
            FieldSpec("scree", "Собственные значения и объяснённая дисперсия",
                      FieldKind.CHECKBOX, default=True, row=2, column=1),
            FieldSpec("save_scores", "Показать факторные значения", FieldKind.CHECKBOX,
                      default=False, row=3, column=1),
        ],
    ),
    "graph": DialogSpec(
        key="graph",
        title="Графики",
        command_type=object,
        build=build_graph,
        description=(
            "Гистограмма, ящик с усами, диаграмма рассеяния, столбчатая и "
            "круговая диаграммы, линия средних"
        ),
        fields=[
            FieldSpec(
                "kind",
                "Вид графика:",
                FieldKind.CHOICE,
                default="histogram",
                row=0,
                column=0,
                choices=CHART_TYPES,
            ),
            FieldSpec("variables", "Переменные:", FieldKind.VARIABLE_LIST,
                      VarFilter.ANY, row=1, column=0),
            FieldSpec("category", "Категории (для ящика, столбцов, круга, линии):",
                      FieldKind.SINGLE_VARIABLE, VarFilter.CATEGORICAL, row=2, column=0),
            FieldSpec("bins", "Интервалов (0 - автоматически):", FieldKind.NUMBER,
                      default=0.0, row=3, column=0, minimum=0, maximum=100, step=1,
                      decimals=0),
            FieldSpec("show_normal", "Наложить кривую нормального распределения",
                      FieldKind.CHECKBOX, default=False, row=0, column=1),
            FieldSpec("show_mean", "Показать среднее и медиану", FieldKind.CHECKBOX,
                      default=True, row=1, column=1),
            FieldSpec("title", "Заголовок графика:", FieldKind.TEXT, default="",
                      row=2, column=1),
        ],
    ),
}


__all__ = [
    "DESCRIPTIVE_STATISTICS",
    "DIALOG_SPECS",
    "DialogSpec",
    "FieldKind",
    "FieldSpec",
    "VarFilter",
    "build_anova",
    "build_compute",
    "build_correlations",
    "build_crosstabs",
    "build_descriptives",
    "build_factor",
    "build_frequencies",
    "build_graph",
    "build_linear_regression",
    "build_logistic_regression",
    "build_nonparametric",
    "build_recode",
    "build_reliability",
    "build_ttest",
]
