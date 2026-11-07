"""CSV: универсальный обмен данными.

Метаданные переменных пишутся комментариями в начале файла. Формально это
расширение CSV, но большинство инструментов (Excel, LibreOffice, pandas,
R read.csv) спокойно пропускают строки, начинающиеся с "#", поэтому файл
остаётся совместимым.
"""

from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pandas as pd

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec, Variable, VarType

META_PREFIX = "# winnow-variable: "


def _variable_to_meta(variable: Variable) -> dict[str, Any]:
    return {
        "name": variable.name,
        "label": variable.label,
        "measure": variable.measure.value,
        "var_type": variable.var_type.value,
        "decimals": variable.decimals,
        "value_labels": {str(k): v for k, v in variable.value_labels.items()},
        "missing": {
            "discrete": sorted(variable.missing.discrete),
            "lo": variable.missing.lo,
            "hi": variable.missing.hi,
        },
    }


def _meta_to_variable(meta: dict[str, Any]) -> Variable:
    labels: dict[Any, str] = {}
    for key, label in (meta.get("value_labels") or {}).items():
        try:
            numeric = float(key)
            labels[int(numeric) if numeric.is_integer() else numeric] = label
        except (TypeError, ValueError):
            labels[key] = label
    missing = meta.get("missing") or {}
    return Variable(
        name=meta["name"],
        label=meta.get("label", ""),
        measure=Measure(meta.get("measure", "scale")),
        var_type=VarType(meta.get("var_type", "numeric")),
        decimals=int(meta.get("decimals", 2)),
        value_labels=labels,
        missing=MissingSpec(
            discrete={float(v) for v in missing.get("discrete") or []},
            lo=missing.get("lo"),
            hi=missing.get("hi"),
        ),
    )


def write_csv(dataset: Dataset, path: str | Path, delimiter: str = ",") -> Path:
    path = Path(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        for name in dataset.names():
            meta = _variable_to_meta(dataset.var(name))
            handle.write(META_PREFIX + json.dumps(meta, ensure_ascii=False) + "\n")
        dataset.frame.to_csv(handle, sep=delimiter, index=False)
    return path


def read_csv(path: str | Path, delimiter: str | None = None) -> Dataset:
    path = Path(path)
    metadata: list[dict[str, Any]] = []
    skip = 0

    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.startswith(META_PREFIX):
                metadata.append(json.loads(line[len(META_PREFIX):]))
                skip += 1
            elif line.startswith("#"):
                skip += 1
            else:
                break

    if delimiter is None:
        # Разделитель определяется по первой строке данных, а не по расширению:
        # файлы .csv с точкой с запятой - обычное дело в русской локали.
        with path.open("r", encoding="utf-8-sig") as handle:
            for _ in range(skip):
                handle.readline()
            sample = handle.readline()
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        if not sample:
            delimiter = ","

    frame = pd.read_csv(path, sep=delimiter, skiprows=skip, encoding="utf-8-sig")
    frame = frame.reset_index(drop=True)

    variables: OrderedDict[str, Variable] = OrderedDict()
    for meta in metadata:
        if meta.get("name") in frame.columns:
            variables[meta["name"]] = _meta_to_variable(meta)
    return Dataset(frame=frame, variables=variables, name=path.stem)


__all__ = ["META_PREFIX", "read_csv", "write_csv"]
