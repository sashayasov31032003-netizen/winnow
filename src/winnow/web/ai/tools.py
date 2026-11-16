"""Инструменты, которые агент может вызывать.

Каждый инструмент — тонкая обёртка над уже существующим кодом приложения:
схема и профиль берутся из `stats`, расчёт идёт через `DIALOG_SPECS` →
`execute`, сценарии — из советчика. Новых формул здесь нет и быть не должно:
иначе числа в чате разойдутся с числами в отчёте.

Правила, общие для всех инструментов:

* работа только с текущим набором диалога и только с данными его владельца;
* никаких изменений данных — только чтение и расчёт;
* результат — JSON, пригодный и модели, и интерфейсу;
* ошибка — понятный текст, который модель может объяснить человеку.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable

from winnow.analysis.quality import quality_report
from winnow.stats.engine import REGISTRY_BY_KEY, execute
from winnow.stats.profile import profile_dataset
from winnow.shared.procedure_specs import DIALOG_SPECS
from winnow.web import storage
from winnow.web.ai import store
from winnow.web.ai.config import AISettings, raw_text_allowed
from winnow.web.ai.provider import ToolSpec
from winnow.web.ai.serialization import compact_payload, result_payload
from winnow.web.policy import ALLOWED_PROCEDURES


class ToolError(RuntimeError):
    """Ошибка инструмента: её текст показывается модели и человеку."""


@dataclass(frozen=True)
class ToolContext:
    """Что инструмент знает о запросе."""

    user_id: int
    dataset_id: int
    settings: AISettings


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


def _label_key(value: Any) -> str:
    """Ключ метки значения в JSON: 1.0 и 1 — один и тот же код."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value) if math.isfinite(float(value)) else None


def _load(context: ToolContext):
    row = store.dataset_row(context.user_id, context.dataset_id)
    try:
        dataset = storage.load_dataset(row.path)
    except FileNotFoundError as exc:
        raise ToolError(
            "Файл набора не найден на сервере. Загрузите данные заново."
        ) from exc
    except OSError as exc:
        raise ToolError(f"Не удалось прочитать набор: {exc}") from exc
    return row, dataset


def _meta(row, dataset) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "n_cases": int(len(dataset.frame)),
        "n_variables": len(dataset.names()),
        "revision": storage.dataset_revision(row.path),
        "ai_full_access": bool(row.ai_full_access),
    }


# ------------------------------------------------------------------ чтение


def _list_datasets(context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    return {
        "datasets": store.list_datasets(context.user_id),
        "current_dataset_id": context.dataset_id,
    }


def _schema(context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    row, dataset = _load(context)
    variables = storage.variables_payload(dataset)
    for item in variables:
        variable = dataset.var(item["name"])
        labels = {
            _label_key(value): str(label)
            for value, label in list(variable.value_labels.items())[:30]
        }
        if labels:
            item["value_labels"] = labels
        if variable.missing.discrete:
            item["missing_codes"] = sorted(
                _label_key(code) for code in variable.missing.discrete
            )
    return {
        "dataset": _meta(row, dataset),
        "variables": variables,
        "note": (
            "Это паспорт данных: имена, метки, типы и уровни измерения. "
            "Значения строк здесь не передаются."
        ),
    }


def _profile(context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    row, dataset = _load(context)
    profile = profile_dataset(dataset)
    variables = [
        {
            "name": item.name,
            "label": item.label,
            "type": item.var_type.value,
            "measure": item.measure.value,
            "role": item.role,
            "n_unique": item.n_unique,
            "n_missing": item.n_missing,
            "missing_share": round(item.missing_share, 4),
            "is_identifier": item.is_identifier,
            "is_constant": item.is_constant,
            "is_binary": item.is_binary,
            "is_likert_like": item.is_likert_like,
            "looks_like_checkbox": item.looks_like_checkbox,
            "can_compare_groups": item.can_compare_groups,
            "is_normal": item.is_normal,
            "skewness": _finite(item.skewness),
            "n_outliers": item.n_outliers,
            "min_value": _finite(item.min_value),
            "max_value": _finite(item.max_value),
        }
        for item in profile.variables
    ]
    return {
        "dataset": _meta(row, dataset),
        "n_cases": profile.n_cases,
        "n_variables": profile.n_variables,
        "notes": list(profile.notes),
        "identifiers": list(profile.identifiers),
        "constants": list(profile.constants),
        "checkboxes": list(profile.checkboxes),
        "variables": variables,
    }


def _preview(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Фрагмент строк. Только при явном разрешении на сырые данные."""
    row, dataset = _load(context)
    if not row.ai_full_access:
        return {
            "allowed": False,
            "reason": (
                "Просмотр строк выключен для этого набора. Схема, профиль и "
                "агрегаты доступны, а строки — только после явного разрешения "
                "в настройках доступа к данным."
            ),
        }
    if not raw_text_allowed():
        return {
            "allowed": False,
            "reason": "Сервер запрещает передачу сырых строк модели (WINNOW_AI_ALLOW_TEXT=0).",
        }
    limit = int(args.get("limit") or 10)
    limit = max(1, min(20, limit))
    preview = storage.preview_payload(dataset, limit=limit)
    columns = args.get("columns")
    if columns:
        names = [str(name) for name in columns if str(name) in dataset.names()]
        if names:
            preview["columns"] = names
            preview["rows"] = [
                {name: row_data.get(name) for name in names}
                for row_data in preview["rows"]
            ]
    return {
        "allowed": True,
        "preview": preview,
        "note": "Это фрагмент, а не все данные. Выводы по нему делать нельзя.",
    }


def _procedures(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Список процедур или поля формы конкретной процедуры."""
    procedure = str(args.get("procedure") or "")
    if not procedure:
        return {
            "procedures": [
                {
                    "key": info.key,
                    "title": info.title,
                    "description": info.description,
                    "group": info.group,
                }
                for info in REGISTRY_BY_KEY.values()
                if info.key in ALLOWED_PROCEDURES
            ]
        }
    if procedure not in ALLOWED_PROCEDURES:
        raise ToolError(f"Процедура «{procedure}» недоступна для запуска")
    spec = DIALOG_SPECS.get(procedure)
    info = REGISTRY_BY_KEY.get(procedure)
    if spec is None or info is None:
        raise ToolError(f"Нет описания процедуры «{procedure}»")
    return {
        "procedure": procedure,
        "title": info.title,
        "description": info.description,
        "fields": [
            {
                "name": field.name,
                "label": field.label,
                "kind": field.kind.value,
                "filter": field.var_filter.value,
                "default": field.default,
                "choices": [
                    {"label": label, "value": value}
                    for label, value in field.choices
                ],
                "min": field.minimum,
                "max": field.maximum,
                "tooltip": field.tooltip,
            }
            for field in spec.fields
        ],
        "note": (
            "Передай значения этих полей в run_procedure как объект values. "
            "Для списков переменных — массив имён."
        ),
    }


# ------------------------------------------------------------------ расчёт


def _check_quality(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Проверка качества данных и линейной модели, без изменения данных."""
    row, dataset = _load(context)
    target = str(args.get("target") or "") or None
    predictors = [str(name) for name in (args.get("predictors") or [])]
    started = time.perf_counter()
    try:
        report = quality_report(dataset, target=target, predictors=predictors)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)

    result = report.as_result()
    payload = result_payload(
        result,
        procedure="quality",
        params={"target": target, "predictors": predictors},
        dataset_name=row.name,
        dataset_revision=storage.dataset_revision(row.path),
        n_cases=int(len(dataset.frame)),
        duration_ms=duration_ms,
    )
    payload["quality"] = report.as_payload()
    run_id = store.save_run(
        user_id=context.user_id,
        dataset_id=context.dataset_id,
        dataset_path=row.path,
        procedure="quality",
        title=result.title or "Проверка качества данных",
        params=payload["params"],
        payload=payload,
        duration_ms=duration_ms,
    )
    payload["run_id"] = run_id
    compact = compact_payload(payload)
    quality = report.as_payload()
    compact["ok"] = True
    # Модели не нужны все переменные: ей нужны сводка, проблемы и модель.
    compact["quality"] = {
        "counts": quality["counts"],
        "issues": quality["issues"][:12],
        "regression": quality["regression"],
        "target": quality["target"],
        "predictors": quality["predictors"],
    }
    return compact


def _run_procedure(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    procedure = str(args.get("procedure") or "")
    if procedure not in ALLOWED_PROCEDURES:
        raise ToolError(
            f"Процедура «{procedure}» недоступна. Доступны: "
            + ", ".join(sorted(ALLOWED_PROCEDURES))
        )
    info = REGISTRY_BY_KEY.get(procedure)
    if info is None:
        raise ToolError(f"Процедура «{procedure}» не найдена")

    row, dataset = _load(context)
    values = args.get("values")
    params = args.get("params")

    if isinstance(values, dict) and isinstance(values.get("variables"), str):
        # Частая ошибка моделей: одна переменная строкой вместо списка.
        # Подсказка дешевле, чем падение разбора «s-c-o-r-e» на буквы.
        raise ToolError("Поле variables должно быть массивом имён, например [\"score\"]")
    if isinstance(params, dict) and isinstance(params.get("variables"), str):
        raise ToolError("Поле variables должно быть массивом имён, например [\"score\"]")

    if values is not None:
        spec = DIALOG_SPECS.get(procedure)
        if spec is None:
            raise ToolError(f"У процедуры «{procedure}» нет формы")
        try:
            command = spec.build(dict(values), dataset)
        except (ValueError, TypeError) as exc:
            raise ToolError(f"Неверные параметры расчёта: {exc}") from exc
    elif params:
        try:
            command = info.command_type(dataset=dataset, **dict(params))
        except TypeError as exc:
            raise ToolError(f"Неизвестный параметр расчёта: {exc}") from exc
        except ValueError as exc:
            raise ToolError(f"Неверные параметры расчёта: {exc}") from exc
    else:
        raise ToolError(
            "Нужны values (значения полей формы) или params (параметры команды)."
        )

    split_by = args.get("split_by")
    if split_by:
        try:
            dataset.set_split(str(split_by))
        except (KeyError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
    weight = args.get("weight")
    if weight:
        if str(weight) not in dataset.names():
            raise ToolError(f"Переменной весов «{weight}» нет в наборе")
        dataset.weight_var = str(weight)

    started = time.perf_counter()
    try:
        result = execute(command)
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)

    payload = result_payload(
        result,
        procedure=procedure,
        params={
            "values": values,
            "params": params,
            "split_by": split_by,
            "weight": weight,
        },
        dataset_name=row.name,
        dataset_revision=storage.dataset_revision(row.path),
        n_cases=int(len(dataset.frame)),
        duration_ms=duration_ms,
    )
    run_id = store.save_run(
        user_id=context.user_id,
        dataset_id=context.dataset_id,
        dataset_path=row.path,
        procedure=procedure,
        title=result.title or info.title,
        params=payload["params"],
        payload=payload,
        duration_ms=duration_ms,
    )
    payload["run_id"] = run_id
    compact = compact_payload(payload)
    compact["ok"] = True
    return compact


def _suggest(context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
    row, dataset = _load(context)
    payload = storage.scenarios_payload(dataset)
    return {
        "dataset": _meta(row, dataset),
        "cases": payload["cases"],
        "variables": payload["variables"],
        "notes": payload["notes"],
        "scenarios": payload["scenarios"][:10],
        "note": (
            "Это подсказки, а не готовые выводы: у каждой есть procedure и "
            "params, которые можно передать в run_procedure."
        ),
    }


def _get_run(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        run_id = int(args["run_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("Нужен числовой run_id") from exc
    data = store.get_run(context.user_id, run_id)
    payload = data["payload"]
    stale = False
    try:
        row = store.dataset_row(context.user_id, data["dataset_id"])
        stale = bool(
            data.get("dataset_revision")
            and storage.dataset_revision(row.path) != data["dataset_revision"]
        )
    except LookupError:
        pass
    result = {
        "run": compact_payload(payload),
        "created_at": data.get("created_at", ""),
        "dataset_revision": data.get("dataset_revision", ""),
        "stale": stale,
    }
    if stale:
        result["warning"] = (
            "Данные изменились после этого расчёта: числа могут не соответствовать "
            "текущему набору. Пересчитайте процедуру."
        )
    return result


# ------------------------------------------------------------------ реестр


TOOLS: dict[str, Tool] = {
    "list_datasets": Tool(
        ToolSpec(
            name="list_datasets",
            description="Список наборов данных человека. Для текущего диалога набор уже выбран.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _list_datasets,
    ),
    "get_dataset_schema": Tool(
        ToolSpec(
            name="get_dataset_schema",
            description=(
                "Паспорт текущего набора: переменные, метки, типы, уровни измерения, "
                "коды пропусков и метки значений. Вызывай первым."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _schema,
    ),
    "get_profile": Tool(
        ToolSpec(
            name="get_profile",
            description=(
                "Профиль данных: роли переменных, пропуски, выбросы, нормальность, "
                "похожесть на анкету, пригодность групп."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _profile,
    ),
    "check_quality": Tool(
        ToolSpec(
            name="check_quality",
            description=(
                "Проверка качества данных и линейной модели: пропуски, дубликаты, "
                "выбросы, дисбаланс групп, мультиколлинеарность, "
                "гетероскедастичность и влиятельные наблюдения. Для модели укажи "
                "target и предикторы; без target проверяются только данные."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Зависимая переменная для диагностики модели",
                    },
                    "predictors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "description": "Предикторы модели",
                    },
                },
                "additionalProperties": False,
            },
        ),
        _check_quality,
    ),
    "get_preview": Tool(
        ToolSpec(
            name="get_preview",
            description=(
                "Фрагмент строк таблицы (до 20). Работает только если для набора "
                "явно разрешён доступ к сырым данным."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 12,
                    },
                },
                "additionalProperties": False,
            },
        ),
        _preview,
    ),
    "list_procedures": Tool(
        ToolSpec(
            name="list_procedures",
            description=(
                "Доступные статистические процедуры. Без аргументов — список; "
                "с procedure — поля её формы для run_procedure."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "procedure": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _procedures,
    ),
    "run_procedure": Tool(
        ToolSpec(
            name="run_procedure",
            description=(
                "Выполняет статистическую процедуру и сохраняет расчёт. Вернёт run_id "
                "и таблицы с числами. Параметры бери из list_procedures; для сценария "
                "советчика можно передать params. Числа из ответа — единственный "
                "источник статистики."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "procedure": {
                        "type": "string",
                        "enum": sorted(ALLOWED_PROCEDURES),
                    },
                    "values": {
                        "type": "object",
                        "description": "Значения полей формы процедуры",
                    },
                    "params": {
                        "type": "object",
                        "description": "Параметры команды вместо values (для сценариев)",
                    },
                    "split_by": {
                        "type": "string",
                        "description": "Считать каждую группу отдельно",
                    },
                    "weight": {
                        "type": "string",
                        "description": "Переменная весов",
                    },
                },
                "required": ["procedure"],
                "additionalProperties": False,
            },
        ),
        _run_procedure,
    ),
    "suggest_research": Tool(
        ToolSpec(
            name="suggest_research",
            description=(
                "Готовые сценарии исследования по профилю данных: вопрос, метод, "
                "переменные, уверенность и оговорки."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _suggest,
    ),
    "get_run": Tool(
        ToolSpec(
            name="get_run",
            description=(
                "Открывает сохранённый расчёт по run_id (например, чтобы уточнить "
                "числа из прошлого ответа)."
            ),
            parameters={
                "type": "object",
                "properties": {"run_id": {"type": "integer", "minimum": 1}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        ),
        _get_run,
    ),
}


def tool_specs() -> list[ToolSpec]:
    return [tool.spec for tool in TOOLS.values()]


def get_tool(name: str) -> Tool | None:
    return TOOLS.get(name)


def execute_tool(
    context: ToolContext, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Находит инструмент, проверяет аргументы и выполняет его."""
    from winnow.web.ai.guardrails import ToolArgumentsError, validate_arguments

    tool = TOOLS.get(name)
    if tool is None:
        raise ToolArgumentsError(f"Инструмента «{name}» нет")
    validate_arguments(tool.spec.parameters, arguments)
    return tool.handler(context, arguments)


__all__ = [
    "TOOLS",
    "Tool",
    "ToolContext",
    "ToolError",
    "execute_tool",
    "get_tool",
    "tool_specs",
]
