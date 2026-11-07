"""Excel: основной формат обмена для пользователей, приходящих из SPSS.

Метаданные пишутся на отдельный лист "Статус переменных" - это ровно тот лист,
который SPSS создаёт в .xlsx и который пользователи привыкли видеть.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, VarType

METADATA_SHEET = "Статус переменных"


def write_excel(dataset: Dataset, path: str | Path) -> Path:
    path = Path(path)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        dataset.frame.to_excel(writer, sheet_name="Данные", index=False)

        rows: list[dict[str, Any]] = []
        for name in dataset.names():
            variable = dataset.var(name)
            rows.append(
                {
                    "Имя": variable.name,
                    "Метка": variable.label,
                    "Тип": variable.var_type.value,
                    "Уровень измерения": variable.measure.value,
                    "Знаков после запятой": variable.decimals,
                    "Метки значений": "; ".join(
                        f"{k} = {v}" for k, v in variable.value_labels.items()
                    ),
                    "Пропущенные": variable.missing.summary(),
                }
            )
        pd.DataFrame(rows).to_excel(writer, sheet_name=METADATA_SHEET, index=False)
    return path


def _parse_value_labels(text: Any) -> dict[Any, str]:
    labels: dict[Any, str] = {}
    if not isinstance(text, str) or not text.strip():
        return labels
    for chunk in text.split(";"):
        if "=" not in chunk:
            continue
        key, _, label = chunk.partition("=")
        key = key.strip()
        try:
            numeric = float(key)
            labels[int(numeric) if numeric.is_integer() else numeric] = label.strip()
        except ValueError:
            labels[key] = label.strip()
    return labels


def read_excel(path: str | Path, sheet: str | int = 0) -> Dataset:
    path = Path(path)
    frame = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    frame.columns = [str(c) for c in frame.columns]
    dataset = Dataset(frame=frame.reset_index(drop=True), name=path.stem)

    # Если есть лист метаданных - читаем его и восстанавливаем паспорта.
    try:
        book = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    except Exception:
        return dataset

    meta_frame = book.get(METADATA_SHEET)
    if meta_frame is None:
        return dataset

    for _, row in meta_frame.iterrows():
        name = str(row.get("Имя", "")).strip()
        if name not in dataset.variables:
            continue
        variable = dataset.var(name)
        variable.label = str(row.get("Метка", "") or "")
        measure = str(row.get("Уровень измерения", "") or "").strip().lower()
        if measure in {m.value for m in Measure}:
            variable.measure = Measure(measure)
        var_type = str(row.get("Тип", "") or "").strip().lower()
        if var_type in {t.value for t in VarType}:
            variable.var_type = VarType(var_type)
        variable.value_labels = _parse_value_labels(row.get("Метки значений"))
    return dataset


__all__ = ["METADATA_SHEET", "read_excel", "write_excel"]
