"""Движок: единственное место, где команда превращается в результат.

Реестр процедур даёт GUI список доступных действий, а скриптовому режиму -
точку входа. Добавление процедуры = один модуль со своей функцией run() плюс
одна строка в REGISTRY.
"""

from __future__ import annotations

import dataclasses

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from winnow.stats.command import (
    AnovaCommand,
    Command,
    CommandError,
    ComputeCommand,
    CorrelationsCommand,
    CrosstabsCommand,
    DescriptivesCommand,
    FactorCommand,
    FrequenciesCommand,
    LinearRegressionCommand,
    LogisticRegressionCommand,
    NonparametricCommand,
    RecodeCommand,
    ReliabilityCommand,
    TTestCommand,
)
from winnow.stats.charts import ChartCommand
from winnow.stats.result import Result, Table

ProcedureRunner = Callable[[Command], Result]


@dataclass(frozen=True)
class ProcedureInfo:
    """Описание процедуры для меню и диалогов."""

    key: str
    title: str
    command_type: type[Command]
    runner: ProcedureRunner
    group: str = "Анализ"
    description: str = ""


def _runner(module_name: str) -> ProcedureRunner:
    """Ленивая загрузка: модули статистики подключаются по требованию."""

    def run(command: Command) -> Result:
        module = __import__(f"winnow.stats.{module_name}", fromlist=["run"])
        return module.run(command)

    return run


def _runner_regression(kind: str) -> ProcedureRunner:
    """Регрессия живёт в одном модуле с двумя точками входа."""

    def run(command: Command) -> Result:
        from winnow.stats import regression

        return regression.run_linear(command) if kind == "linear" else regression.run_logistic(command)

    return run


def _runner_transform(kind: str) -> ProcedureRunner:
    """Вычисление и перекодирование живут в одном модуле."""

    def run(command: Command) -> Result:
        from winnow.stats import transform

        return transform.run_compute(command) if kind == "compute" else transform.run_recode(command)

    return run


REGISTRY: tuple[ProcedureInfo, ...] = (
    ProcedureInfo(
        key="frequencies",
        title="Частоты",
        command_type=FrequenciesCommand,
        runner=_runner("frequencies"),
        group="Описательные статистики",
        description="Распределение значений категориальной или числовой переменной",
    ),
    ProcedureInfo(
        key="descriptives",
        title="Описательные статистики",
        command_type=DescriptivesCommand,
        runner=_runner("descriptives"),
        group="Описательные статистики",
        description="Среднее, медиана, разброс, форма распределения",
    ),
    ProcedureInfo(
        key="crosstabs",
        title="Таблицы сопряжённости",
        command_type=CrosstabsCommand,
        runner=_runner("crosstabs"),
        group="Таблицы",
        description="Связь двух категориальных переменных, хи-квадрат, V Крамера",
    ),
    ProcedureInfo(
        key="ttest",
        title="t-критерий",
        command_type=TTestCommand,
        runner=_runner("ttest"),
        group="Сравнение средних",
        description="Одна выборка, независимые и связанные выборки, размеры эффекта",
    ),
    ProcedureInfo(
        key="anova",
        title="Однофакторный дисперсионный анализ",
        command_type=AnovaCommand,
        runner=_runner("anova"),
        group="Сравнение средних",
        description=(
            "Сравнение трёх и более групп, робастный тест Уэлча, "
            "апостериорные сравнения Тьюки, Бонферрони и Холма"
        ),
    ),
    ProcedureInfo(
        key="nonparametric",
        title="Непараметрические критерии",
        command_type=NonparametricCommand,
        runner=_runner("nonparametric"),
        group="Сравнение средних",
        description=(
            "Манна-Уитни, Краскела-Уоллиса, Уилкоксона и Фридмана - для данных, "
            "которые не подчиняются нормальному распределению"
        ),
    ),
    ProcedureInfo(
        key="correlations",
        title="Корреляции",
        command_type=CorrelationsCommand,
        runner=_runner("correlations"),
        group="Связи",
        description="Пирсон, Спирмен, Кендалл с попарным исключением пропусков",
    ),
    ProcedureInfo(
        key="linear_regression",
        title="Линейная регрессия",
        command_type=LinearRegressionCommand,
        runner=_runner_regression("linear"),
        group="Связи",
        description=(
            "Предсказание количественной переменной: коэффициенты, R-квадрат, "
            "мультиколлинеарность, диагностика остатков"
        ),
    ),
    ProcedureInfo(
        key="logistic_regression",
        title="Логистическая регрессия",
        command_type=LogisticRegressionCommand,
        runner=_runner_regression("logistic"),
        group="Связи",
        description=(
            "Предсказание события «да/нет»: отношения шансов, качество "
            "предсказания, псевдо-R-квадрат"
        ),
    ),
    ProcedureInfo(
        key="compute",
        title="Вычислить переменную",
        command_type=ComputeCommand,
        runner=_runner_transform("compute"),
        group="Преобразование данных",
        description=(
            "Новая переменная по выражению: пересчёт шкалы, индекс из нескольких "
            "пунктов, возрастные группы"
        ),
    ),
    ProcedureInfo(
        key="recode",
        title="Перекодировать в новую переменную",
        command_type=RecodeCommand,
        runner=_runner_transform("recode"),
        group="Преобразование данных",
        description=(
            "Превращение значений в новые: объединение категорий, группировка "
            "диапазонов, замена кодов"
        ),
    ),
    ProcedureInfo(
        key="reliability",
        title="Анализ надёжности",
        command_type=ReliabilityCommand,
        runner=_runner("reliability"),
        group="Масштабирование",
        description=(
            "Альфа Кронбаха и омега Макдональда для шкалы опросника, "
            "статистики пунктов и «альфа при удалении пункта»"
        ),
    ),
    ProcedureInfo(
        key="factor",
        title="Факторный анализ",
        command_type=FactorCommand,
        runner=_runner("factor"),
        group="Масштабирование",
        description=(
            "Структура опросника: KMO и критерий Бартлетта, выделение факторов, "
            "вращение Varimax и Promax, общности и факторные нагрузки"
        ),
    ),
    ProcedureInfo(
        key="graph",
        title="Графики",
        command_type=ChartCommand,
        runner=_runner("charts"),
        group="Графики",
        description=(
            "Гистограмма, ящик с усами, диаграмма рассеяния, столбчатая и "
            "круговая диаграммы, линия средних"
        ),
    ),
)

REGISTRY_BY_KEY: dict[str, ProcedureInfo] = {info.key: info for info in REGISTRY}


def _split_subsets(dataset) -> list[tuple[str, pd.Series | None]]:
    """Готовит поднаборы для разбиения файла.

    Возвращает список (подпись группы, маска). Если разбиение не задано, список
    состоит из одного элемента с пустой подписью - тогда процедура выполняется
    как обычно и никаких лишних заголовков в отчёте не появляется.
    """
    if not getattr(dataset, "has_split", False) or not dataset.split_var:
        return [("", None)]

    subsets: list[tuple[str, pd.Series | None]] = []
    for value in dataset.split_values:
        try:
            mask = dataset.split_mask(value)
        except ValueError:
            # Пустая группа молча пропускается: падать из-за этого нельзя.
            continue
        subsets.append((dataset.split_label(value), mask))
    return subsets or [("", None)]


#: Процедуры, которые действительно учитывают веса кейсов.
#:
#: Список закрытый и намеренно короткий: обещать взвешивание там, где формулы
#: не взвешенные, значит давать неверные числа. У остальных процедур в отчёт
#: добавляется предупреждение, что веса не учтены.
WEIGHTED_PROCEDURES = frozenset(
    {"frequencies", "descriptives", "crosstabs", "ttest", "anova", "linear_regression"}
)

#: Процедуры, где веса применяются развёртыванием набора по весам.
#:
#: При целых весах это в точности поведение SPSS (частотные веса): суммы
#: квадратов, средние и степени свободы совпадают, проверено на эталоне
#: (F = 392,824 при N = 22). Переписывать математику процедуры не нужно.
WEIGHT_EXPANDED_PROCEDURES = frozenset({"anova", "linear_regression"})


def _weights_note(result: Result, command: Command) -> None:
    """Предупреждает, если веса заданы, но процедура их не учитывает."""
    dataset = command.dataset
    if dataset is None:
        return
    try:
        has_weights = dataset.weight_values() is not None
    except (ValueError, TypeError):
        has_weights = False
    if has_weights and command.KEY not in WEIGHTED_PROCEDURES:
        result.warn(
            f"Веса кейсов (переменная «{dataset.weight_var}») в этой процедуре не "
            "учитываются: числа невзвешенные"
        )


def execute(command: Command) -> Result:
    """Проверяет постановку и исполняет команду.

    Если включено разбиение файла, процедура выполняется отдельно по каждой
    группе, а результаты собираются в один отчёт с заголовками групп. Это
    поведение движка, а не отдельных процедур: иначе каждую пришлось бы учить
    работать с разбиением, и они неизбежно разошлись бы в трактовке.
    """
    command.validate()
    info = REGISTRY_BY_KEY.get(command.KEY)
    if info is None:
        raise CommandError(f"Процедура не зарегистрирована: {command.PROCEDURE}")

    dataset = command.dataset

    # Веса: набор разворачивается по весам, дальше считается как обычно. Так
    # результат совпадает с SPSS без правки формул внутри процедуры.
    if dataset is not None and command.KEY in WEIGHT_EXPANDED_PROCEDURES:
        from winnow.stats.weights import expand_by_weights, expansion_counts

        counts = expansion_counts(dataset)
        if counts is not None and counts.sum() > 0:
            original = dataset
            command.dataset = expand_by_weights(dataset)
            try:
                result = execute(command)
            finally:
                command.dataset = original
            result.note(
                f"Учтены веса кейсов: переменная «{original.weight_var}» "
                f"(строк {len(original.frame)} → {int(counts.sum())})"
            )
            result.syntax = command.syntax()
            return result

    subsets = _split_subsets(dataset) if dataset is not None else [("", None)]

    if len(subsets) == 1 and not subsets[0][0]:
        result = info.runner(command)
        if not result.syntax:
            result.syntax = command.syntax()
        _weights_note(result, command)
        return result

    combined = Result(
        procedure=command.PROCEDURE,
        title=command.TITLE,
        syntax=command.syntax(),
    )
    combined.note(
        f"Разбиение файла: результаты по каждой категории переменной "
        f"«{dataset.var(dataset.split_var).display_name}» отдельно"
    )

    for label, mask in subsets:
        previous = dataset._filter_mask
        dataset.set_filter(mask)
        try:
            partial = info.runner(command)
        except Exception as exc:  # noqa: BLE001 - одна группа не должна ломать весь отчёт
            combined.warn(f"{label}: расчёт не выполнен ({exc})")
            continue
        finally:
            dataset._filter_mask = previous

        # Пустая таблица работает как заголовок группы: в HTML она рисуется
        # заметным подзаголовком, а в дереве вывода становится отдельным узлом.
        combined.tables.append(Table(title=label))
        combined.tables.extend(partial.tables)
        for warning in partial.warnings:
            combined.warn(f"{label}: {warning}")
        for note in partial.notes:
            combined.note(f"{label}: {note}")
        # Выводы простыми словами тоже переносятся, с подписью группы: без них
        # при разбиении отчёт состоял из таблиц без объяснений.
        for finding in getattr(partial, "findings", []):
            combined.findings.append(
                dataclasses.replace(finding, text=f"{label}: {finding.text}")
            )

    if not combined.tables:
        combined.warn("Ни одной таблицы не построено")
    _weights_note(combined, command)
    return combined


__all__ = ["REGISTRY", "REGISTRY_BY_KEY", "ProcedureInfo", "execute"]
