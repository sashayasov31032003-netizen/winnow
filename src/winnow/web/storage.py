"""Хранилище наборов данных: разбор загруженного файла и выдача его наружу.

Здесь же всё, что фронтенду нужно знать о наборе: список переменных, первые
строки таблицы и подсказки советчика. Формирование ответов держится отдельно от
HTTP, чтобы его можно было проверить тестами без браузера.
"""

from __future__ import annotations

import math
import pathlib
import tempfile
import uuid

from winnow.data.io.native import read_native, write_native
from winnow.data.io.registry import read_dataset
from winnow.stats.advisor import suggest_scenarios
from winnow.stats.profile import profile_dataset
from winnow.web.core import DATA_DIR

#: Сколько строк отдавать для предпросмотра.
PREVIEW_ROWS = 50


def user_dir(user_id: int) -> pathlib.Path:
    path = DATA_DIR / "users" / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_safe(value):
    """Готовит значение ячейки к JSON: NaN и бесконечность не сериализуются."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):  # numpy-числа
        try:
            return _json_safe(value.item())
        except (ValueError, AttributeError):
            return str(value)
    return value


def import_file(user_id: int, filename: str, data: bytes) -> tuple[pathlib.Path, object]:
    """Разбирает загруженный файл и сохраняет его в формате Winnow.

    Возвращает путь к сохранённому набору и сам набор (объект движка).
    """
    suffix = pathlib.Path(filename).suffix.lower() or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        temp_path = pathlib.Path(handle.name)
    try:
        dataset = read_dataset(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)

    target = user_dir(user_id) / f"{uuid.uuid4().hex}.winnow"
    write_native(dataset, target)
    return target, dataset


def load_dataset(path: str | pathlib.Path):
    """Читает набор с диска."""
    return read_native(pathlib.Path(path))


def dataset_revision(path: str | pathlib.Path) -> str:
    """Отпечаток файла набора: время изменения и размер.

    Нужен, чтобы связать расчёт с состоянием данных. Если файл поправили после
    расчёта, отпечаток изменится, и старые числа нельзя будет выдать за новые.
    Хэш содержимого здесь избыточен: набор перезаписывается целиком.
    """
    try:
        stat = pathlib.Path(path).stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def variables_payload(dataset) -> list[dict]:
    """Список переменных с тем, что нужно показать в таблице."""
    result: list[dict] = []
    for name in dataset.names():
        variable = dataset.var(name)
        series = dataset.frame[name]
        result.append(
            {
                "name": name,
                "label": variable.label or "",
                "display": variable.display_name,
                "type": variable.var_type.value,
                "measure": variable.measure.value,
                "measure_ru": variable.measure.ru,
                "n_unique": int(series.nunique(dropna=True)),
                "n_missing": int(series.isna().sum()),
            }
        )
    return result


def preview_payload(dataset, limit: int = PREVIEW_ROWS, offset: int = 0) -> dict:
    """Страница строк таблицы в виде, удобном для отрисовки и правки."""
    offset = max(0, min(offset, max(0, len(dataset.frame) - 1)))
    head = dataset.frame.iloc[offset : offset + limit]
    rows = [
        {column: _json_safe(value) for column, value in zip(head.columns, row)}
        for row in head.itertuples(index=False, name=None)
    ]
    return {
        "columns": list(dataset.names()),
        "rows": rows,
        "limit": limit,
        "offset": offset,
        "total": int(len(dataset.frame)),
    }


def save_dataset(dataset, path: str | pathlib.Path) -> None:
    """Записывает набор обратно в его файл после правки."""
    write_native(dataset, pathlib.Path(path))


def _parse_cell(variable, value) -> float | str:
    """Приводит введённое значение к типу переменной.

    Ошибку возвращает текстом, а не исключением pandas: человек должен увидеть,
    какая именно ячейка и почему не подходит.
    """
    if variable.is_numeric:
        if value is None or (isinstance(value, str) and not value.strip()):
            return float("nan")
        try:
            return float(str(value).replace(",", ".").strip())
        except ValueError as exc:
            raise ValueError(
                f"«{value}» — не число, а переменная «{variable.name}» числовая"
            ) from exc
    return "" if value is None else str(value)


def apply_edits(dataset, edits: list[dict]) -> int:
    """Меняет значения ячеек в памяти. Сохранение — отдельным вызовом."""
    changed = 0
    positions = {name: index for index, name in enumerate(dataset.names())}
    rows_total = len(dataset.frame)
    for edit in edits:
        column = str(edit.get("column", ""))
        if column not in positions:
            raise ValueError(f"Переменной «{column}» нет в наборе")
        row = int(edit.get("row", -1))
        if row < 0 or row >= rows_total:
            raise ValueError(f"Строки {row + 1} нет в наборе (всего {rows_total})")
        parsed = _parse_cell(dataset.var(column), edit.get("value"))
        current = dataset.frame[column]
        # Целочисленный столбец не принимает ни дробное значение, ни пропуск:
        # pandas отказывается писать и выдаёт «Invalid value for dtype int64».
        # Поэтому при дробном значении столбец переводится в вещественные - это
        # честнее, чем молча округлить введённое человеком число.
        if current.dtype.kind in "iub" and isinstance(parsed, float):
            dataset.frame[column] = current.astype(float)
        dataset.frame.iat[row, positions[column]] = parsed
        changed += 1
    return changed


def scenarios_payload(dataset) -> dict:
    """Подсказки советчика: что можно сделать с этими данными."""
    profile = profile_dataset(dataset)
    scenarios = suggest_scenarios(dataset, profile=profile)
    return {
        "cases": int(profile.n_cases),
        "variables": int(profile.n_variables),
        "notes": list(profile.notes),
        "scenarios": [
            {
                "key": item.key,
                "title": item.title,
                "question": item.question,
                "why": item.why,
                "procedure": item.procedure,
                # В params попадают коды групп из pandas: это numpy-числа,
                # которые JSON-сериализатор FastAPI не принимает.
                "params": {
                    key: _json_safe(value) for key, value in item.params.items()
                },
                "roles": dict(item.roles),
                "confidence": item.confidence,
                "caveats": list(item.caveats),
            }
            for item in scenarios
        ],
    }


__all__ = [
    "PREVIEW_ROWS",
    "apply_edits",
    "dataset_revision",
    "save_dataset",
    "import_file",
    "load_dataset",
    "preview_payload",
    "scenarios_payload",
    "user_dir",
    "variables_payload",
]
