"""Проверки, которые не дают агенту выйти за рамки.

Три вещи здесь принципиальны:

1. **Аргументы инструментов проверяются схемой.** Модель может прислать
   `{"variables": "оценка"}` вместо списка или лишнее поле; это должно стать
   понятной ошибкой вызова, а не падением процедуры.
2. **Числа в ответе сверяются с результатами расчётов.** Это эвристика, а не
   доказательство: она ловит «p = 0,03» там, где расчёт дал 0,31, но не спасает
   от неверной интерпретации. Полную гарантию даёт интерфейс: он показывает
   числа из сохранённого расчёта, а не из текста модели.
3. **Квоты считаются на сервере.** Бесплатные модели имеют суточный лимит, и
   один человек не должен исчерпать его для всех.
"""

from __future__ import annotations

import re
from typing import Any

#: Сколько символов можно прислать в одном сообщении.
MAX_MESSAGE_CHARS = 4000

_NUMBER = re.compile(
    r"-?\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?"
    r"|-?\d+[.,]\d+"
)


class AIGuardError(ValueError):
    """Ошибка, которую нужно показать пользователю."""


class ToolArgumentsError(AIGuardError):
    """Аргументы вызова не соответствуют схеме."""


class QuotaExceeded(AIGuardError):
    """Суточный лимит сообщений исчерпан."""


def check_message(text: str) -> str:
    """Проверяет сообщение пользователя и возвращает его без крайних пробелов."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise AIGuardError("Сообщение пустое")
    if len(cleaned) > MAX_MESSAGE_CHARS:
        raise AIGuardError(
            f"Сообщение длиннее {MAX_MESSAGE_CHARS} символов. "
            "Сократите вопрос — контекст данных агент соберёт сам."
        )
    return cleaned


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_arguments(schema: dict[str, Any], value: Any) -> None:
    """Проверяет аргументы по подмножеству JSON Schema, которого нам хватает.

    Полноценный валидатор тянул бы зависимость ради десяти правил; здесь
    поддерживаются object/array/string/integer/number/boolean, enum,
    обязательные поля, запрет лишних полей и границы чисел.
    """
    _check(schema, value, "arguments")


def _check(schema: dict[str, Any], value: Any, path: str) -> None:
    expected = schema.get("type")
    if expected is not None:
        variants = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(kind, value) for kind in variants):
            raise ToolArgumentsError(
                f"{path}: ожидался тип {expected}, пришло {type(value).__name__}"
            )

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(str(item) for item in schema["enum"])
        raise ToolArgumentsError(f"{path}: допустимые значения — {allowed}")

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for name in required:
            if name not in value:
                raise ToolArgumentsError(f"{path}: не хватает обязательного поля «{name}»")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ToolArgumentsError(
                    f"{path}: неизвестные поля {', '.join(unknown)}"
                )
        for name, item in value.items():
            if name in properties:
                _check(properties[name], item, f"{path}.{name}")
        return

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _check(items, item, f"{path}[{index}]")
        if schema.get("maxItems") is not None and len(value) > schema["maxItems"]:
            raise ToolArgumentsError(
                f"{path}: максимум {schema['maxItems']} элементов"
            )
        return

    if isinstance(value, str):
        if schema.get("minLength") is not None and len(value) < schema["minLength"]:
            raise ToolArgumentsError(f"{path}: слишком короткая строка")
        if schema.get("maxLength") is not None and len(value) > schema["maxLength"]:
            raise ToolArgumentsError(f"{path}: строка длиннее {schema['maxLength']}")
        return

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if schema.get("minimum") is not None and value < schema["minimum"]:
            raise ToolArgumentsError(f"{path}: значение меньше {schema['minimum']}")
        if schema.get("maximum") is not None and value > schema["maximum"]:
            raise ToolArgumentsError(f"{path}: значение больше {schema['maximum']}")


def extract_numbers(text: str) -> list[str]:
    """Вытаскивает числа из текста, сохраняя исходное написание."""
    return [match.group(0) for match in _NUMBER.finditer(text or "")]


def _as_float(token: str) -> float | None:
    cleaned = token.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _collect_numbers(value: Any, into: list[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        into.append(float(value))
        return
    if isinstance(value, str):
        for token in extract_numbers(value):
            number = _as_float(token)
            if number is not None:
                into.append(number)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_numbers(item, into)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_numbers(item, into)


def _decimals(token: str) -> int:
    """Сколько знаков после запятой в числе так, как его написали."""
    for separator in (",", "."):
        if separator in token:
            return len(token.split(separator, 1)[1])
    return 0


def unverified_numbers(text: str, payloads: list[dict[str, Any]]) -> list[str]:
    """Возвращает числа из текста, которых нет в результатах инструментов.

    Сравнение идёт с точностью, которую человек видит в тексте: «0,03» может
    означать 0,031 из расчёта, а «99,5» — нет, даже если рядом есть 100.
    Поэтому допуск зависит от числа знаков после запятой, а не от процента:
    процентная точность принимала бы 99,5 за 100.

    Проверяются числа с дробной частью и числа от 10: именно они похожи на
    статистику. Мелкие целые («3 группы») — обычная речь, их пропускаем, как и
    годы: иначе проверка ругалась бы на «2024 год» в описании данных.
    """
    known: list[float] = []
    for payload in payloads:
        _collect_numbers(payload, known)

    unmatched: list[str] = []
    for match in _NUMBER.finditer(text):
        token = match.group(0)
        number = _as_float(token)
        if number is None:
            continue
        has_fraction = ("." in token) or ("," in token)
        if not has_fraction and abs(number) < 10:
            continue
        if not has_fraction and 1900 <= abs(number) <= 2100:
            continue

        decimals = _decimals(token)
        tolerance = 0.5 * 10 ** (-decimals)
        # «p < 0,001» — не число, а граница: расчёт мог дать 0,0004, и это
        # утверждение верно. Поэтому для сравнений проверяем неравенство, а не
        # совпадение.
        before = text[max(0, match.start() - 3) : match.start()]
        operator = "<" if "<" in before else ">" if ">" in before else ""

        matched = False
        for known_value in known:
            # Для сравнений проценты и доли не пересчитываем: «p < 0,0001»
            # не должно выполняться из-за того, что 0,0004/100 меньше границы.
            candidates = (
                (known_value,)
                if operator
                else (known_value, known_value * 100.0, known_value / 100.0)
            )
            for candidate in candidates:
                if operator == "<":
                    matched = candidate < number + tolerance
                elif operator == ">":
                    matched = candidate > number - tolerance
                else:
                    matched = abs(candidate - number) <= tolerance
                if matched:
                    break
            if matched:
                break
        if not matched and token not in unmatched:
            unmatched.append(token)
    return unmatched


__all__ = [
    "AIGuardError",
    "MAX_MESSAGE_CHARS",
    "QuotaExceeded",
    "ToolArgumentsError",
    "check_message",
    "extract_numbers",
    "unverified_numbers",
    "validate_arguments",
]
