"""Собственный формат Winnow (.wndata) - JSON с полным сохранением паспортов.

Это "эталонный" формат: что положили, то и достали. Пока совместимость с .sav
не идеальна, он гарантирует, что работа пользователя не потеряется.

Расширение .wndata появилось при переименовании проекта (раньше он назывался
StatLab): файлы с прежним расширением .stldata и прежним маркером формата
читаются по-прежнему, иначе старые наборы перестали бы открываться.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pandas as pd

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec, Variable, VarType

FORMAT_VERSION = 1

#: Маркер формата в JSON. Прежний маркер оставлен только для чтения.
FORMAT_MARKER = "winnow-dataset"
LEGACY_MARKERS = ("statlab-dataset",)


def _json_safe(value: Any) -> Any:
    """Приводит значение ячейки к тому, что переживёт JSON."""
    if isinstance(value, (bool, str, int, float)) or value is None:
        return value
    return str(value)


def _encode_value_labels(labels: dict[Any, str]) -> list[dict[str, Any]]:
    """Ключи JSON обязаны быть строками, поэтому код метки хранит свой тип."""
    items = []
    for key, label in labels.items():
        if isinstance(key, bool):
            encoded: Any = bool(key)
        elif isinstance(key, (int, float)):
            encoded = float(key)
        else:
            encoded = str(key)
        items.append({"value": encoded, "label": label})
    return items


def _decode_value_labels(items: list[dict[str, Any]]) -> dict[Any, str]:
    labels: dict[Any, str] = {}
    for item in items:
        value = item.get("value")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        labels[value] = item.get("label", "")
    return labels


def dataset_to_dict(dataset: Dataset) -> dict[str, Any]:
    variables = []
    for name in dataset.names():
        variable = dataset.var(name)
        variables.append(
            {
                "name": variable.name,
                "label": variable.label,
                "measure": variable.measure.value,
                "var_type": variable.var_type.value,
                "width": variable.width,
                "decimals": variable.decimals,
                "columns": variable.columns,
                "value_labels": _encode_value_labels(variable.value_labels),
                "missing": {
                    "discrete": sorted(float(v) for v in variable.missing.discrete),
                    "lo": variable.missing.lo,
                    "hi": variable.missing.hi,
                },
            }
        )

    records = [
        [_json_safe(cell) for cell in row]
        for row in dataset.frame.itertuples(index=False, name=None)
    ]

    return {
        "format": FORMAT_MARKER,
        "version": FORMAT_VERSION,
        "name": dataset.name,
        "weight_var": dataset.weight_var,
        "columns": dataset.names(),
        "variables": variables,
        "rows": records,
    }


def dataset_from_dict(payload: dict[str, Any]) -> Dataset:
    if payload.get("format") not in (FORMAT_MARKER, *LEGACY_MARKERS):
        raise ValueError("Файл не является набором данных Winnow")

    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    frame = pd.DataFrame(rows, columns=columns)

    variables: OrderedDict[str, Variable] = OrderedDict()
    for meta in payload.get("variables", []):
        missing = meta.get("missing") or {}
        variables[meta["name"]] = Variable(
            name=meta["name"],
            label=meta.get("label", ""),
            measure=Measure(meta.get("measure", "scale")),
            var_type=VarType(meta.get("var_type", "numeric")),
            width=int(meta.get("width", 8)),
            decimals=int(meta.get("decimals", 2)),
            columns=int(meta.get("columns", 0)),
            value_labels=_decode_value_labels(meta.get("value_labels") or []),
            missing=MissingSpec(
                discrete={float(v) for v in missing.get("discrete") or []},
                lo=missing.get("lo"),
                hi=missing.get("hi"),
            ),
        )

    dataset = Dataset(frame=frame, variables=variables, name=payload.get("name", "Набор1"))
    dataset.weight_var = payload.get("weight_var")
    return dataset


def write_native(dataset: Dataset, path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dataset_to_dict(dataset), handle, ensure_ascii=False, indent=1)
    return path


def read_native(path: str | Path) -> Dataset:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return dataset_from_dict(payload)


__all__ = [
    "FORMAT_MARKER",
    "FORMAT_VERSION",
    "LEGACY_MARKERS",
    "dataset_from_dict",
    "dataset_to_dict",
    "read_native",
    "write_native",
]
