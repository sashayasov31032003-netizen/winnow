"""Команды - единая точка входа в движок для GUI и для скриптов.

Почему это важно: если кнопка в диалоге вызывает расчёт напрямую, а скриптовый
режим - своим путём, то очень скоро эти два пути начнут считать по-разному.
Поэтому любой запуск процедуры - это объект Command, который умеет:
  1) отдать человекочитаемый синтаксис (лог воспроизводимости),
  2) быть исполненным движком.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from winnow.core.dataset import Dataset
from winnow.stats.result import Result


class CommandError(ValueError):
    """Ошибка постановки задачи: её текст показывается пользователю как есть."""


@dataclass
class Command:
    """Базовый класс команды. Наследники заполняют PROCEDURE/TITLE/KEY и syntax().

    KEY - ключ в реестре процедур. Он задан явно, а не выводится из PROCEDURE,
    потому что "T-TEST" и "ttest" - разные строки, и такая мелочь ломает запуск.

    ВАЖНО: PROCEDURE/TITLE/KEY объявлены как ClassVar. Если объявить их просто
    с значением по умолчанию, dataclass превратит их в ПОЛЯ экземпляра, и
    значения подклассов ("DESCRIPTIVES") будут затираться базовыми ("COMMAND") -
    процедура перестанет находиться в реестре.
    """

    PROCEDURE: ClassVar[str] = "COMMAND"
    TITLE: ClassVar[str] = "Процедура"
    KEY: ClassVar[str] = "command"
    dataset: Dataset | None = field(default=None, repr=False, compare=False)

    def syntax(self) -> str:
        return f"{self.PROCEDURE}."

    def execute(self) -> Result:
        """Исполняет команду. Импорт внутри метода - чтобы не плодить циклы."""
        from winnow.stats.engine import execute

        return execute(self)

    def validate(self) -> None:
        """Проверка постановки до расчёта. Наследники переопределяют."""


def _var_list(names: list[str]) -> str:
    return " ".join(names)


@dataclass
class DescriptivesCommand(Command):
    """Описательные статистики: среднее, медиана, разброс, асимметрия, эксцесс."""

    PROCEDURE: ClassVar[str] = "DESCRIPTIVES"
    TITLE: ClassVar[str] = "Описательные статистики"
    KEY: ClassVar[str] = "descriptives"

    variables: list[str] = field(default_factory=list)
    statistics: list[str] = field(
        default_factory=lambda: [
            "n", "missing", "mean", "median", "std", "variance", "min", "max",
            "range", "skewness", "kurtosis", "sem", "sum",
        ]
    )
    percentiles: list[float] = field(default_factory=list)
    confidence: float = 0.0  # 0 - не показывать доверительные интервалы
    split_by: str | None = None
    z_scores: bool = False

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.variables:
            raise CommandError("Выберите хотя бы одну переменную")
        for name in self.variables:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(
                    f"Описательные статистики требуют числовую переменную, а {name!r} - "
                    f"{self.dataset.var(name).var_type.value}"
                )

    def syntax(self) -> str:
        lines = [
            "DESCRIPTIVES",
            f"  VARIABLES={_var_list(self.variables)}",
            f"  /STATISTICS={_var_list(self.statistics)}",
        ]
        if self.percentiles:
            lines.append("  /PERCENTILES=" + _var_list([f"{p:g}" for p in self.percentiles]))
        if self.confidence:
            lines.append(f"  /CRITERIA=CI({self.confidence * 100:g})")
        if self.split_by:
            lines.append(f"  /SPLIT={self.split_by}")
        return "\n".join(lines) + "."


@dataclass
class CrosstabsCommand(Command):
    """Таблицы сопряжённости с хи-квадратом, метками значений и мерами связи."""

    PROCEDURE: ClassVar[str] = "CROSSTABS"
    TITLE: ClassVar[str] = "Таблицы сопряжённости"
    KEY: ClassVar[str] = "crosstabs"

    row_vars: list[str] = field(default_factory=list)
    col_vars: list[str] = field(default_factory=list)
    layer_vars: list[str] = field(default_factory=list)
    chi_square: bool = True
    exact: bool = False
    expected: bool = False
    residuals: bool = False
    row_percent: bool = True
    col_percent: bool = False
    total_percent: bool = False
    count: bool = True
    phi_cramers_v: bool = True
    lambda_: bool = False
    gamma: bool = False
    kendall_tau: bool = False

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.row_vars:
            raise CommandError("Выберите хотя бы одну переменную строк")
        if not self.col_vars:
            raise CommandError("Выберите хотя бы одну переменную столбцов")
        for name in self.row_vars + self.col_vars + self.layer_vars:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
        if not (self.count or self.row_percent or self.col_percent or self.total_percent):
            raise CommandError("Выберите хотя бы одну ячейку для отображения")

    def syntax(self) -> str:
        lines = [
            "CROSSTABS",
            f"  /TABLES={_var_list(self.row_vars)} BY {_var_list(self.col_vars)}",
        ]
        if self.layer_vars:
            lines.append("  /LAYERS=" + _var_list(self.layer_vars))
        cells = []
        if self.count:
            cells.append("COUNT")
        if self.row_percent:
            cells.append("ROW")
        if self.col_percent:
            cells.append("COLUMN")
        if self.total_percent:
            cells.append("TOTAL")
        if cells:
            lines.append("  /CELLS=" + _var_list(cells))
        if self.chi_square:
            lines.append("  /STATISTICS=CHISQ")
        if self.phi_cramers_v:
            lines.append("  /STATISTICS=PHI CRAMERS_V")
        if self.expected:
            lines.append("  /CELLS=EXPECTED")
        if self.residuals:
            lines.append("  /CELLS=RESID")
        return "\n".join(lines) + "."


@dataclass
class TTestCommand(Command):
    """t-критерий: одна выборка, независимые и связанные выборки."""

    PROCEDURE: ClassVar[str] = "T-TEST"
    TITLE: ClassVar[str] = "t-критерий"
    KEY: ClassVar[str] = "ttest"

    kind: str = "independent"  # "one_sample" | "independent" | "paired"
    test_vars: list[str] = field(default_factory=list)
    group_var: str | None = None
    group_values: list[Any] = field(default_factory=list)
    pair_with: list[str] = field(default_factory=list)
    test_value: float = 0.0
    confidence: float = 0.95
    effect_size: bool = True

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if self.kind == "one_sample":
            if not self.test_vars:
                raise CommandError("Выберите переменную для проверки")
        elif self.kind == "independent":
            if not self.test_vars:
                raise CommandError("Выберите хотя бы одну проверяемую переменную")
            if not self.group_var:
                raise CommandError("Выберите переменную группировки")
            if len(self.group_values) != 2:
                raise CommandError(
            "Для независимых выборок нужно ровно две группы. "
            "Укажите два кода в поле «Коды групп», например 1, 2, "
            "или выберите вид критерия «Одна выборка»"
        )
        elif self.kind == "paired":
            if not self.test_vars or not self.pair_with:
                raise CommandError(
            "Для связанных выборок нужны две переменные: первая — в списке "
            "«Проверяемые переменные», парная к ней — в списке «В парах с "
            "переменными»"
        )
            if len(self.test_vars) != len(self.pair_with):
                raise CommandError(
            "Число переменных в парах должно совпадать: сколько переменных "
            "выбрано для проверки, столько же должно быть парных к ним"
        )
        else:
            raise CommandError(f"Неизвестный вид t-критерия: {self.kind!r}")

        named = list(self.test_vars) + list(self.pair_with)
        if self.group_var:
            named.append(self.group_var)
        for name in named:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(
            f"Переменная {name!r} должна быть числовой: описательные "
            "статистики считают средние, а у категорий их не бывает. "
            "Для категорий используйте «Частоты»"
        )
        if not 0.0 < self.confidence < 1.0:
            raise CommandError(
            "Доверительный уровень задаётся долей между 0 и 1, "
            "обычно это 0,95"
        )

    def syntax(self) -> str:
        conf = f"{self.confidence * 100:g}"
        if self.kind == "independent":
            groups = " ".join(str(v) for v in self.group_values)
            return (
                "T-TEST\n"
                f"  /GROUPS={self.group_var}({groups})\n"
                f"  /VARIABLES={_var_list(self.test_vars)}\n"
                f"  /CRITERIA=CI({conf})"
            )
        if self.kind == "paired":
            pairs = " ".join(f"{a} WITH {b}" for a, b in zip(self.test_vars, self.pair_with))
            return f"T-TEST\n  /PAIRS={pairs}\n  /CRITERIA=CI({conf})"
        return (
            "T-TEST\n"
            f"  /TESTVAL={self.test_value:g}\n"
            f"  /VARIABLES={_var_list(self.test_vars)}\n"
            f"  /CRITERIA=CI({conf})"
        )


@dataclass
class FrequenciesCommand(Command):
    """Частоты: самая первая процедура, которой пользуется любой новичок."""

    PROCEDURE: ClassVar[str] = "FREQUENCIES"
    TITLE: ClassVar[str] = "Частоты"
    KEY: ClassVar[str] = "frequencies"

    variables: list[str] = field(default_factory=list)
    show_counts: bool = True
    show_percent: bool = True
    show_valid_percent: bool = True
    show_cumulative: bool = False
    statistics: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.variables:
            raise CommandError("Выберите хотя бы одну переменную")
        for name in self.variables:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")

    def syntax(self) -> str:
        lines = [
            "FREQUENCIES",
            f"  /VARIABLES={_var_list(self.variables)}",
            "  /ORDER=ANALYSIS",
        ]
        if self.statistics:
            lines.append("  /STATISTICS=" + _var_list(self.statistics))
        return "\n".join(lines) + "."


@dataclass
class CorrelationsCommand(Command):
    """Корреляции Пирсона, Спирмена и Кендалла с проверкой значимости."""

    PROCEDURE: ClassVar[str] = "CORRELATIONS"
    TITLE: ClassVar[str] = "Корреляции"
    KEY: ClassVar[str] = "correlations"

    variables: list[str] = field(default_factory=list)
    method: str = "pearson"  # "pearson" | "spearman" | "kendall"
    two_tailed: bool = True
    flag_significant: bool = True

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if len(self.variables) < 2:
            raise CommandError(
            "Для корреляционного анализа нужны минимум две переменные. "
            "Перенесите в правый список ещё одну переменную"
        )
        if self.method not in ("pearson", "spearman", "kendall"):
            raise CommandError(f"Неизвестный метод корреляции: {self.method!r}")
        for name in self.variables:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(f"Переменная {name!r} должна быть числовой")

    def syntax(self) -> str:
        method = {"pearson": "PEARSON", "spearman": "SPEARMAN", "kendall": "KENDALL"}[self.method]
        tail = "TWO-TAILED" if self.two_tailed else "ONE-TAILED"
        return (
            "CORRELATIONS\n"
            f"  /VARIABLES={_var_list(self.variables)}\n"
            f"  /PRINT={tail} NOSIG\n"
            f"  /METHOD={method}"
        )


@dataclass
class AnovaCommand(Command):
    """Однофакторный дисперсионный анализ с апостериорными сравнениями.

    Нужен для сравнения более чем двух групп: если групп три и больше, t-критерий
    применять нельзя - из-за множественных сравнений он даёт ложные срабатывания.
    """

    PROCEDURE: ClassVar[str] = "ONEWAY"
    TITLE: ClassVar[str] = "Однофакторный дисперсионный анализ"
    KEY: ClassVar[str] = "anova"

    dependent: list[str] = field(default_factory=list)   # зависимые переменные
    factor: str | None = None                            # группирующая переменная
    post_hoc: str = "tukey"  # "tukey" | "bonferroni" | "holm" | "none"
    confidence: float = 0.95
    descriptives: bool = True
    homogeneity: bool = True
    welch: bool = True
    effect_size: bool = True

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.dependent:
            raise CommandError("Выберите хотя бы одну зависимую переменную")
        if not self.factor:
            raise CommandError("Выберите переменную группировки")
        if self.factor in self.dependent:
            raise CommandError("Переменная группировки не может быть зависимой переменной")
        for name in list(self.dependent) + [self.factor]:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
        for name in self.dependent:
            if not self.dataset.var(name).is_numeric:
                raise CommandError(f"Зависимая переменная {name!r} должна быть числовой")
        if self.post_hoc not in ("tukey", "bonferroni", "holm", "none"):
            raise CommandError(f"Неизвестный метод апостериорных сравнений: {self.post_hoc!r}")
        if not 0.0 < self.confidence < 1.0:
            raise CommandError("Доверительный уровень должен быть между 0 и 1")

    def syntax(self) -> str:
        lines = [
            "ONEWAY",
            f"  VARIABLES={_var_list(self.dependent)} BY {self.factor}",
        ]
        if self.descriptives:
            lines.append("  /STATISTICS=DESCRIPTIVES")
        if self.homogeneity:
            lines.append("  /STATISTICS=HOMOGENEITY")
        if self.welch:
            lines.append("  /STATISTICS=WELCH")
        if self.effect_size:
            lines.append("  /STATISTICS=EFFECTSIZE")
        if self.post_hoc != "none":
            method = {"tukey": "TUKEY", "bonferroni": "BONFERRONI", "holm": "HOLM"}[self.post_hoc]
            lines.append(f"  /POSTHOC={method}")
            lines.append(f"  /CRITERIA=CI({self.confidence * 100:g})")
        return "\n".join(lines) + "."


@dataclass
class NonparametricCommand(Command):
    """Непараметрические критерии для независимых и связанных выборок.

    Нужны, когда данные не подчиняются нормальному распределению или измерены в
    порядковой шкале: t-критерий и ANOVA в этих случаях неприменимы.
    """

    PROCEDURE: ClassVar[str] = "NPAR TESTS"
    TITLE: ClassVar[str] = "Непараметрические критерии"
    KEY: ClassVar[str] = "nonparametric"

    kind: str = "independent"  # "independent" | "related"
    test_vars: list[str] = field(default_factory=list)
    pair_with: list[str] = field(default_factory=list)
    group_var: str | None = None
    group_values: list[Any] = field(default_factory=list)
    # "auto" | "mann_whitney" | "kruskal_wallis" | "wilcoxon" | "friedman"
    method: str = "auto"
    descriptives: bool = True
    confidence: float = 0.95

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.test_vars:
            raise CommandError("Выберите хотя бы одну переменную")
        if self.method not in ("auto", "mann_whitney", "kruskal_wallis", "wilcoxon", "friedman"):
            raise CommandError(f"Неизвестный метод: {self.method!r}")

        if self.kind == "independent":
            if not self.group_var:
                raise CommandError("Выберите переменную группировки")
            if self.method in ("wilcoxon", "friedman"):
                raise CommandError("Этот критерий применяется только к связанным выборкам")
        elif self.kind == "related":
            if not self.pair_with:
                raise CommandError("Для связанных выборок укажите, с чем сравнивать")
            if len(self.test_vars) != len(self.pair_with):
                raise CommandError("Число переменных в парах должно совпадать")
            if self.method in ("mann_whitney", "kruskal_wallis"):
                raise CommandError("Этот критерий применяется только к независимым выборкам")
        else:
            raise CommandError(f"Неизвестный вид выборок: {self.kind!r}")

        names = list(self.test_vars) + list(self.pair_with)
        if self.group_var:
            names.append(self.group_var)
        for name in names:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(f"Переменная {name!r} должна быть числовой")

    def syntax(self) -> str:
        if self.kind == "independent":
            method = {
                "auto": "M-W K-W",
                "mann_whitney": "M-W",
                "kruskal_wallis": "K-W",
            }.get(self.method, "M-W K-W")
            return (
                "NPAR TESTS\n"
                f"  /{method}={_var_list(self.test_vars)} BY {self.group_var}"
            )
        method = {"auto": "WILCOXON", "wilcoxon": "WILCOXON", "friedman": "FRIEDMAN"}.get(
            self.method, "WILCOXON"
        )
        pairs = " ".join(f"{a} WITH {b}" for a, b in zip(self.test_vars, self.pair_with))
        return f"NPAR TESTS\n  /{method}={pairs}"


@dataclass
class LinearRegressionCommand(Command):
    """Линейная регрессия методом наименьших квадратов с диагностикой.

    Помимо коэффициентов считаются: качество модели (R-квадрат), вклад каждого
    предиктора, мультиколлинеарность (VIF), автокорреляция остатков (Дарбин-Уотсон)
    и нормальность остатков. Без диагностики регрессию защищать бессмысленно:
    первое, что спросят, - «а условия применимости выполнены?».
    """

    PROCEDURE: ClassVar[str] = "REGRESSION"
    TITLE: ClassVar[str] = "Линейная регрессия"
    KEY: ClassVar[str] = "linear_regression"

    dependent: str | None = None
    predictors: list[str] = field(default_factory=list)
    confidence: float = 0.95
    method: str = "enter"  # пока поддерживается только "enter"
    diagnostics: bool = True
    standardize: bool = False
    constant: bool = True

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.dependent:
            raise CommandError("Выберите зависимую переменную")
        if not self.predictors:
            raise CommandError("Выберите хотя бы один предиктор")
        if self.dependent in self.predictors:
            raise CommandError("Зависимая переменная не может быть предиктором")
        for name in [self.dependent, *self.predictors]:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(f"Переменная {name!r} должна быть числовой")
        if not 0.0 < self.confidence < 1.0:
            raise CommandError("Доверительный уровень должен быть между 0 и 1")

    def syntax(self) -> str:
        lines = [
            "REGRESSION",
            f"  /DESCRIPTIVES MEAN STDDEV CORR SIG N",
            f"  /MISSING LISTWISE",
            f"  /STATISTICS COEFF OUTS CI({self.confidence * 100:g}) R ANOVA",
        ]
        if self.diagnostics:
            lines.append("  /STATISTICS COLLIN TOL")
        if self.standardize:
            lines.append("  /STATISTICS ZPP")
        if not self.constant:
            lines.append("  /ORIGIN")
        lines.append(f"  /DEPENDENT {self.dependent}")
        lines.append(f"  /METHOD=ENTER {_var_list(self.predictors)}")
        return "\n".join(lines) + "."


@dataclass
class LogisticRegressionCommand(Command):
    """Логистическая регрессия для бинарного отклика.

    Нужна, когда зависимая переменная - событие «да/нет» (поступил или нет,
    болен или здоров): линейная регрессия для такого отклика неприменима.
    """

    PROCEDURE: ClassVar[str] = "LOGISTIC REGRESSION"
    TITLE: ClassVar[str] = "Логистическая регрессия"
    KEY: ClassVar[str] = "logistic_regression"

    dependent: str | None = None
    predictors: list[str] = field(default_factory=list)
    confidence: float = 0.95
    reference_value: Any = None  # какое значение отклика считать «событием»
    max_iterations: int = 50
    tolerance: float = 1e-8

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.dependent:
            raise CommandError("Выберите зависимую переменную")
        if not self.predictors:
            raise CommandError("Выберите хотя бы один предиктор")
        if self.dependent in self.predictors:
            raise CommandError("Зависимая переменная не может быть предиктором")
        for name in [self.dependent, *self.predictors]:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(f"Переменная {name!r} должна быть числовой")
        if not 0.0 < self.confidence < 1.0:
            raise CommandError("Доверительный уровень должен быть между 0 и 1")

        # Отклик обязан быть бинарным - иначе это не логистическая регрессия.
        series = self.dataset.categorical_series(self.dependent).dropna()
        unique = sorted(set(series.tolist()), key=lambda value: str(value))
        if len(unique) != 2:
            raise CommandError(
                f"Зависимая переменная должна принимать ровно два значения, "
                f"а найдено {len(unique)}: {unique[:5]}"
            )
        if self.reference_value is not None and self.reference_value not in unique:
            raise CommandError(
                f"Указанное значение отклика {self.reference_value!r} отсутствует в данных"
            )

    def syntax(self) -> str:
        # Зависимая переменная указывается сразу после имени процедуры: без неё
        # записанный синтаксис нельзя выполнить повторно - команда не знает, что
        # предсказывать. Раньше она терялась при сохранении.
        return (
            f"LOGISTIC REGRESSION VARIABLES {self.dependent or ''}".rstrip() + "\n"
            f"  /METHOD=ENTER {_var_list(self.predictors)}\n"
            f"  /CRITERIA=PIN({self.tolerance:g}) ITERATE({self.max_iterations})\n"
            f"  /PRINT=CI({self.confidence * 100:g})"
        )


@dataclass
class ComputeCommand(Command):
    """Вычисление новой переменной по выражению.

    Закрывает самый частый этап подготовки данных: пересчитать шкалу, построить
    индекс из нескольких пунктов, получить возрастные группы.
    """

    PROCEDURE: ClassVar[str] = "COMPUTE"
    TITLE: ClassVar[str] = "Вычисление переменной"
    KEY: ClassVar[str] = "compute"

    target: str = ""
    expression: str = ""
    label: str = ""
    overwrite: bool = False
    decimals: int = 2

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.target.strip():
            raise CommandError("Укажите имя новой переменной")
        if not _is_valid_name(self.target):
            raise CommandError(
                f"Недопустимое имя переменной: {self.target!r}. "
                "Используйте латинские буквы, цифры и подчёркивание, начиная с буквы"
            )
        if self.target in self.dataset.variables and not self.overwrite:
            raise CommandError(
                f"Переменная {self.target!r} уже существует. "
                "Отметьте «перезаписать», если её нужно заменить"
            )
        if not self.expression.strip():
            raise CommandError("Введите выражение для вычисления")
        # Проверяем выражение до расчёта, чтобы ошибка была понятной и сразу.
        from winnow.stats.expressions import check_expression

        check_expression(self.expression, self.dataset.names())

    def syntax(self) -> str:
        suffix = " (перезапись)" if self.overwrite else ""
        return (
            "COMPUTE\n"
            f"  {self.target} = {self.expression}{suffix}\n"
            f"  /LABEL={self.label or self.target}"
        )


@dataclass
class RecodeRule:
    """Одно правило перекодирования: значение или диапазон превращается в новое."""

    kind: str = "value"          # "value" | "range" | "system_missing" | "else"
    value: Any = None            # для kind="value"
    low: float | None = None     # для kind="range" (включая нижнюю границу)
    high: float | None = None    # для kind="range" (не включая верхнюю)
    new_value: Any = None
    new_label: str = ""


@dataclass
class RecodeCommand(Command):
    """Перекодирование значений в новую переменную."""

    PROCEDURE: ClassVar[str] = "RECODE"
    TITLE: ClassVar[str] = "Перекодирование переменной"
    KEY: ClassVar[str] = "recode"

    source: str | None = None
    target: str = ""
    rules: list[RecodeRule] = field(default_factory=list)
    overwrite: bool = False
    label: str = ""

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if not self.source:
            raise CommandError("Выберите переменную для перекодирования")
        if self.source not in self.dataset.variables:
            raise CommandError(f"Переменная не найдена: {self.source}")
        if not self.target.strip():
            raise CommandError("Укажите имя новой переменной")
        if not _is_valid_name(self.target):
            raise CommandError(f"Недопустимое имя переменной: {self.target!r}")
        if self.target in self.dataset.variables and not self.overwrite:
            raise CommandError(
                f"Переменная {self.target!r} уже существует. "
                "Отметьте «перезаписать», если её нужно заменить"
            )
        if not self.rules:
            raise CommandError("Добавьте хотя бы одно правило перекодирования")
        for rule in self.rules:
            if rule.kind == "range" and (rule.low is None or rule.high is None):
                raise CommandError("В диапазоне нужно указать обе границы")
            if rule.kind == "range" and rule.low is not None and rule.high is not None:
                if rule.low >= rule.high:
                    raise CommandError(
                        f"Нижняя граница диапазона ({rule.low:g}) должна быть "
                        f"меньше верхней ({rule.high:g})"
                    )
            if rule.kind in ("value", "range") and rule.new_value is None:
                raise CommandError("У каждого правила должно быть новое значение")

    def syntax(self) -> str:
        lines = ["RECODE", f"  {self.source}"]
        for rule in self.rules:
            if rule.kind == "value":
                lines.append(f"    ({rule.value} = {rule.new_value})")
            elif rule.kind == "range":
                lines.append(f"    ({rule.low:g} THRU {rule.high:g} = {rule.new_value})")
            elif rule.kind == "system_missing":
                lines.append(f"    (SYSMIS = {rule.new_value})")
            else:
                lines.append(f"    (ELSE = {rule.new_value})")
        lines.append(f"  INTO {self.target}.")
        return "\n".join(lines)


def _is_valid_name(name: str) -> bool:
    """Проверяет имя переменной: латиница, цифры, подчёркивание."""
    import re

    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name or ""))


@dataclass
class ReliabilityCommand(Command):
    """Надёжность шкалы: альфа Кронбаха и сопутствующие показатели.

    Нужна, когда в работе есть опросник: прежде чем складывать пункты в шкалу,
    нужно показать, что они действительно измеряют одно и то же.
    """

    PROCEDURE: ClassVar[str] = "RELIABILITY"
    TITLE: ClassVar[str] = "Анализ надёжности"
    KEY: ClassVar[str] = "reliability"

    items: list[str] = field(default_factory=list)
    model: str = "alpha"  # "alpha" | "split" | "parallel"
    split_half: bool = False
    item_statistics: bool = True
    scale_statistics: bool = True
    inter_item: bool = False

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if len(self.items) < 2:
            raise CommandError("Для анализа надёжности нужно минимум два пункта")
        for name in self.items:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(f"Пункт {name!r} должен быть числовым")
        if self.model not in ("alpha", "split", "parallel"):
            raise CommandError(f"Неизвестная модель надёжности: {self.model!r}")

    def syntax(self) -> str:
        lines = [
            "RELIABILITY",
            f"  /VARIABLES={_var_list(self.items)}",
            f"  /SCALE('Шкала') ALL",
            f"  /MODEL={self.model.upper()}",
        ]
        if self.item_statistics:
            lines.append("  /SUMMARY=TOTAL")
        if self.inter_item:
            lines.append("  /SUMMARY=CORR")
        return "\n".join(lines) + "."


@dataclass
class FactorCommand(Command):
    """Эксплораторный факторный анализ.

    Отвечает на вопрос «сколько за шкалами стоит скрытых конструктов и какие
    пункты к какому относятся» - то есть проверяет структуру опросника.
    """

    PROCEDURE: ClassVar[str] = "FACTOR"
    TITLE: ClassVar[str] = "Факторный анализ"
    KEY: ClassVar[str] = "factor"

    variables: list[str] = field(default_factory=list)
    method: str = "pca"        # "pca" (главные компоненты) | "ml" (максимальное правдоподобие)
    rotation: str = "varimax"  # "none" | "varimax" | "quartimax" | "promax"
    n_factors: int = 0         # 0 - определить по критерию Кайзера
    min_eigenvalue: float = 1.0
    suppress_small: float = 0.30
    kmo: bool = True
    bartlett: bool = True
    scree: bool = True
    save_scores: bool = False

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError(
            "Сначала откройте данные: «Файл → Открыть данные»"
        )
        if len(self.variables) < 3:
            raise CommandError("Для факторного анализа нужно минимум три переменные")
        for name in self.variables:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")
            if not self.dataset.var(name).is_numeric:
                raise CommandError(f"Переменная {name!r} должна быть числовой")
        if self.method not in ("pca", "ml"):
            raise CommandError(f"Неизвестный метод выделения: {self.method!r}")
        if self.rotation not in ("none", "varimax", "quartimax", "promax"):
            raise CommandError(f"Неизвестный метод вращения: {self.rotation!r}")
        if self.n_factors < 0:
            raise CommandError("Число факторов не может быть отрицательным")
        if self.n_factors and self.n_factors >= len(self.variables):
            raise CommandError(
                "Число факторов должно быть меньше числа переменных"
            )

    def syntax(self) -> str:
        method = {"pca": "PC", "ml": "ML"}[self.method]
        lines = [
            "FACTOR",
            f"  /VARIABLES={_var_list(self.variables)}",
            f"  /MISSING=LISTWISE",
            f"  /ANALYSIS={_var_list(self.variables)}",
            f"  /PRINT=INITIAL CORRELATION KMO BARTLETT",
            f"  /CRITERIA=MINEIGEN({self.min_eigenvalue:g}) ITERATE(25)"
            if not self.n_factors
            else f"  /CRITERIA=FACTORS({self.n_factors}) ITERATE(25)",
            f"  /EXTRACTION={method}",
        ]
        if self.rotation != "none":
            lines.append(f"  /ROTATION={self.rotation.upper()}")
        else:
            lines.append("  /ROTATION=NOROTATE")
        if self.save_scores:
            lines.append("  /SAVE=REG(ALL)")
        return "\n".join(lines) + "."


__all__ = [
    "AnovaCommand",
    "Command",
    "CommandError",
    "ComputeCommand",
    "CorrelationsCommand",
    "CrosstabsCommand",
    "DescriptivesCommand",
    "FactorCommand",
    "FrequenciesCommand",
    "LinearRegressionCommand",
    "LogisticRegressionCommand",
    "NonparametricCommand",
    "RecodeCommand",
    "RecodeRule",
    "ReliabilityCommand",
    "TTestCommand",
]
