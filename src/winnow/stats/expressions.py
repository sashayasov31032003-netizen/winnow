"""Безопасные выражения для вычисления и отбора переменных.

Зачем свой вычислитель, а не обычный Python: пользователь вводит выражение в
диалоге, и оно должно вычисляться, но при этом не иметь доступа к файлам, сети
и вообще ни к чему, кроме данных. Поэтому выражение разбирается в дерево, и
разрешены только перечислённые ниже операции и функции - всё остальное
отвергается с понятным сообщением.

Поддерживается ровно то, что нужно для работы с данными:

* арифметика: ``+ - * / // % **``
* сравнения: ``< <= > >= == !=``
* логика: ``and or not``
* скобки и унарный минус
* функции: ``abs, min, max, round, sqrt, log, exp, ln, log10``
* переменные набора данных по имени
* числа и строки в кавычках

Пример: ``income / 1000`` или ``age >= 30 and gender == 1``.
"""

from __future__ import annotations

import ast
import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from winnow.stats.command import CommandError

# Разрешённые функции: имя -> реализация.
FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
    "round": np.round,
    "sqrt": np.sqrt,
    "log": np.log,
    "ln": np.log,
    "log10": np.log10,
    "exp": np.exp,
    "floor": np.floor,
    "ceil": np.ceil,
    "sign": np.sign,
}

# Разрешённые операции.
_BINARY_OPERATORS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

_COMPARISONS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}

_UNARY_OPERATORS: dict[type, Callable[[Any], Any]] = {
    ast.USub: lambda value: -value,
    ast.UAdd: lambda value: value,
    ast.Not: lambda value: np.logical_not(value),
}

_FORBIDDEN_NODES: tuple[type, ...] = (
    ast.Attribute,
    ast.Subscript,
    ast.Lambda,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.Await,
    ast.Yield,
    ast.Import,
    ast.ImportFrom,
    ast.Call,  # вызовы разрешаются отдельно, только для белого списка функций
)


class _Evaluator(ast.NodeVisitor):
    """Вычисляет выражение, не выходя за пределы разрешённых операций."""

    def __init__(self, variables: dict[str, Any]) -> None:
        self.variables = variables

    # ------------------------------------------------------------------ вход

    def evaluate(self, node: ast.AST) -> Any:
        return self.visit(node)

    # --------------------------------------------------------------- операции

    def visit_Expression(self, node: ast.Expression) -> Any:  # noqa: N802
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:  # noqa: N802
        if isinstance(node.value, (int, float, bool, str)):
            return node.value
        raise CommandError(f"Недопустимое значение в выражении: {node.value!r}")

    def visit_Name(self, node: ast.Name) -> Any:  # noqa: N802
        if node.id in self.variables:
            return self.variables[node.id]
        if node.id in FUNCTIONS:
            return FUNCTIONS[node.id]
        if node.id in ("True", "False"):
            return node.id == "True"
        raise CommandError(
            f"Неизвестное имя в выражении: {node.id!r}. "
            f"Доступны переменные набора: {', '.join(sorted(self.variables)[:8])}"
            + (" и другие" if len(self.variables) > 8 else "")
        )

    def visit_BinOp(self, node: ast.BinOp) -> Any:  # noqa: N802
        operator = _BINARY_OPERATORS.get(type(node.op))
        if operator is None:
            raise CommandError(f"Операция {type(node.op).__name__} не поддерживается")
        left = self.visit(node.left)
        right = self.visit(node.right)
        try:
            return operator(left, right)
        except ZeroDivisionError:
            raise CommandError("Деление на ноль в выражении") from None
        except (TypeError, ValueError) as exc:
            raise CommandError(f"Ошибка в операции: {exc}") from None

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:  # noqa: N802
        operator = _UNARY_OPERATORS.get(type(node.op))
        if operator is None:
            raise CommandError(f"Унарная операция {type(node.op).__name__} не поддерживается")
        return operator(self.visit(node.operand))

    def visit_Compare(self, node: ast.Compare) -> Any:  # noqa: N802
        result: Any = True
        left = self.visit(node.left)
        for operator_node, comparator in zip(node.ops, node.comparators):
            operator = _COMPARISONS.get(type(operator_node))
            if operator is None:
                raise CommandError(
                    f"Сравнение {type(operator_node).__name__} не поддерживается"
                )
            right = self.visit(comparator)
            result = np.logical_and(result, operator(left, right))
            left = right
        return result

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:  # noqa: N802
        values = [self.visit(value) for value in node.values]
        if isinstance(node.op, ast.And):
            result = values[0]
            for value in values[1:]:
                result = np.logical_and(result, value)
            return result
        if isinstance(node.op, ast.Or):
            result = values[0]
            for value in values[1:]:
                result = np.logical_or(result, value)
            return result
        raise CommandError("Логическая операция не поддерживается")

    def visit_IfExp(self, node: ast.IfExp) -> Any:  # noqa: N802
        condition = self.visit(node.test)
        return np.where(condition, self.visit(node.body), self.visit(node.orelse))

    def visit_Call(self, node: ast.Call) -> Any:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise CommandError("Такую функцию вызывать нельзя")
        name = node.func.id
        function = FUNCTIONS.get(name)
        if function is None:
            raise CommandError(
                f"Функция {name!r} не поддерживается. Доступны: {', '.join(sorted(FUNCTIONS))}"
            )
        if node.keywords:
            raise CommandError("Именованные аргументы в функциях не поддерживаются")
        arguments = [self.visit(argument) for argument in node.args]
        try:
            return function(*arguments)
        except (TypeError, ValueError) as exc:
            raise CommandError(f"Ошибка в функции {name}: {exc}") from None

    # ------------------------------------------------------------- запрещённое

    def generic_visit(self, node: ast.AST) -> Any:
        if isinstance(node, _FORBIDDEN_NODES):
            raise CommandError(
                f"В выражении нельзя использовать {type(node).__name__}. "
                "Разрешены арифметика, сравнения, логика и функции: "
                f"{', '.join(sorted(FUNCTIONS))}"
            )
        raise CommandError(f"Неподдерживаемая конструкция в выражении: {type(node).__name__}")


def parse_expression(expression: str) -> ast.Expression:
    """Разбирает выражение в дерево, не выполняя его."""
    text = (expression or "").strip()
    if not text:
        raise CommandError("Выражение пустое")
    # Запись «a = b» не является выражением сравнения: подскажем про «==».
    if "=" in text and "==" not in text and ">=" not in text and "<=" not in text and "!=" not in text:
        raise CommandError(
            "Похоже, в выражении используется «=». Для сравнения нужно «==», "
            "например: age == 30"
        )
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise CommandError(f"Не удалось разобрать выражение: {exc.msg}") from None
    return tree


def evaluate(expression: str, variables: dict[str, Any]) -> Any:
    """Вычисляет выражение со словарём переменных.

    Возвращает число, логический массив или строку - в зависимости от выражения.
    """
    tree = parse_expression(expression)
    return _Evaluator(variables).evaluate(tree)


def variable_names(expression: str, known: list[str]) -> list[str]:
    """Возвращает имена переменных набора, использованные в выражении.

    Порядок — как переменные объявлены в наборе, а не как их обошёл разборщик:
    так список стабилен и совпадает с тем, что пользователь видит в таблице
    переменных. Иначе порядок зависел бы от формы выражения и менялся бы без
    причины.
    """
    tree = parse_expression(expression)
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return [name for name in known if name in used]


def check_expression(expression: str, known: list[str]) -> list[str]:
    """Проверяет выражение, не выполняя его на данных.

    Возвращает список использованных переменных. Пустой список означает, что
    выражение не зависит от данных (например, просто число).
    """
    parse_expression(expression)
    return variable_names(expression, known)
