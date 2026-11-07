"""Синтаксис: сохранение и разбор файлов `.sps`.

Зачем это нужно. В SPSS синтаксис - не украшение, а способ работы: его сохраняют,
чтобы повторить анализ через месяц и объяснить в статье, что именно считалось.
Один раз собранный анализ можно воспроизвести точно, а не «примерно помню, какие
там были галочки». Поэтому программа умеет и записывать накопленный синтаксис в
файл, и читать его обратно.

Как это устроено:

* каждая команда уже умеет отдавать себя текстом (`Command.syntax()`), поэтому
  сохранение - это сборка блока из уже готовых строк;
* чтение разбирает файл на команды по точке в конце, а каждую команду - на
  подкоманды (строки, начинающиеся с `/`);
* из разобранного набора подкоманд собирается объект команды, который затем
  выполняется обычным движком.

Чего нет и что честно сообщается ошибкой: произвольные выражения SPSS вроде
`COMPUTE x = ...` с функциями, которых нет в нашем вычислителе, и команды,
которых в программе нет. Лучше понятная ошибка с номером строки, чем молча
пропущенная команда: пользователь должен знать, что часть анализа не выполнена.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from winnow.stats.command import Command, CommandError
from winnow.stats.engine import REGISTRY, REGISTRY_BY_KEY


@dataclass
class SyntaxCommand:
    """Одна команда синтаксиса: имя процедуры и её подкоманды."""

    name: str
    body: str
    line: int = 1
    subcommands: dict[str, str] = field(default_factory=dict)


class SyntaxError_(CommandError):
    """Ошибка разбора синтаксиса с указанием места в файле.

    Наследуется от CommandError, поэтому вызывающий код может ловить и общий тип,
    и конкретную ошибку с номером строки.
    """

    def __init__(self, message: str, line: int = 1, text: str = "") -> None:
        location = f"Строка {line}"
        detail = f" ({text.strip()})" if text.strip() else ""
        super().__init__(f"{location}: {message}{detail}")
        self.line = line
        self.text = text


def build_syntax(commands: list[Command], title: str = "") -> str:
    """Собирает текст синтаксиса из списка команд."""
    parts: list[str] = []
    if title:
        parts.append(f"* {title}.")
    for command in commands:
        text = command.syntax().strip()
        if not text:
            continue
        # Команды в файле разделяются точкой. Если команда её не поставила,
        # добавляем: без разделителя следующая команда не прочитается.
        if not text.endswith("."):
            text += "."
        parts.append(text)
    return "\n\n".join(parts) + "\n" if parts else ""


def split_commands(text: str) -> list[tuple[int, str]]:
    """Разбивает файл на команды по точке в конце.

    Возвращает список пар «номер первой строки команды» и «текст команды».
    Точка внутри числа (3.14) или внутри кавычек командой не считается: иначе
    файл развалился бы на куски на первом же десятичном числе.
    """
    commands: list[tuple[int, str]] = []
    current: list[str] = []
    start_line = 1
    line_number = 1
    in_quotes = False

    for line in text.splitlines():
        stripped = line.strip()
        # Комментарии SPSS начинаются со звёздочки: пропускаем их, но нумерацию
        # строк сохраняем, чтобы сообщения об ошибках указывали на файл.
        if stripped.startswith("*") and not current:
            line_number += 1
            continue

        if not current:
            start_line = line_number
        current.append(line)

        for index, character in enumerate(line):
            if character in ("'", '"'):
                in_quotes = not in_quotes
            elif character == "." and not in_quotes:
                # Точка считается концом команды, только если после неё до конца
                # строки ничего нет (кроме пробелов).
                if not line[index + 1 :].strip():
                    commands.append((start_line, "\n".join(current)))
                    current = []
                    break
        line_number += 1

    if current and "\n".join(current).strip():
        commands.append((start_line, "\n".join(current)))
    return commands


# Имена процедур из двух слов. Перебираются от длинных к коротким, иначе
# «LOGISTIC REGRESSION» распалось бы на «LOGISTIC» и остаток.
_TWO_WORD_PROCEDURES = ("LOGISTIC REGRESSION", "NPAR TESTS", "T-TEST")


# Поля подкоманд, которые встречаются в синтаксисе процедур. Список нужен, чтобы
# отличить подкоманду («VARIABLES=age») от строки выражения («income / 1000»).
_KNOWN_FIELDS = frozenset(
    {
        "VARIABLES", "TABLES", "CELLS", "STATISTICS", "PERCENTILES", "MISSING",
        "DEPENDENT", "METHOD", "CRITERIA", "PRINT", "ORIGIN", "SAVE", "ANALYSIS",
        "ROTATION", "EXTRACTION", "SCALE", "SUMMARY", "MODEL", "PAIRS", "TEST",
        "GROUP", "GROUPS", "FACTOR", "POSTHOC", "DESCRIPTIVES", "LABEL", "INTO",
        "HISTOGRAM", "BOXPLOT", "SCATTERPLOT", "BAR", "PIE", "LINE", "LAYERS",
    }
)


def parse_subcommands(body: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Разбирает тело команды на имя процедуры и подкоманды.

    Возвращает имя процедуры, словарь подкоманд `{ключ: значение}` и словарь
    позиционных значений (то, что стояло сразу после имени, без `/`).
    """
    # Убираем точку в конце; переводы строк сохраняем - они разделяют подкоманды.
    text = body.strip().rstrip(".").strip()
    if not text:
        raise SyntaxError_("пустая команда")

    lines = [line.strip() for line in text.split("\n")]
    header = lines[0]
    # Имя процедуры может состоять из двух слов: «LOGISTIC REGRESSION»,
    # «NPAR TESTS». Проверяем такие варианты до разбора по первому пробелу.
    name = ""
    rest = header
    upper_header = header.upper()
    for candidate in _TWO_WORD_PROCEDURES:
        if upper_header.startswith(candidate):
            name = candidate
            rest = header[len(candidate) :]
            break
    if not name:
        name, _sep, rest = header.partition(" ")
        name = name.strip().upper()
    if not name:
        raise SyntaxError_("не указано имя процедуры")

    # Строки после заголовка разбираются по порядку: подкоманда начинается со
    # «/» или с заглавного слова-поля, всё остальное - продолжение позиционной
    # части. Порядок важен: значение поля может лежать на следующей строке
    # («VARIABLES» на одной строке, список переменных на следующей).
    subcommands: dict[str, str] = {}
    positional: dict[str, str] = {}
    first_chunk: list[str] = []
    pending_key: str | None = None

    tail_lines: list[str] = []
    if rest.strip():
        tail_lines.append(rest.strip())
    tail_lines.extend(line for line in lines[1:] if line.strip())

    # Незаполненное поле приводится к индексам строк, чтобы взять значение из
    # следующей строки. Так разбирается запись «LOGISTIC REGRESSION VARIABLES
    # special_software», где переменная стоит на строке с именем процедуры.
    for index, stripped in enumerate(tail_lines):
        body_line = stripped.lstrip("/")
        head, _sep, value = body_line.partition("=")
        head_word = head.split(None, 1)[0].upper() if head.split() else ""
        is_field = stripped.startswith("/") or (
            head_word in _KNOWN_FIELDS or _looks_like_field(body_line)
        )
        if not is_field:
            # Не подкоманда: это либо значение поля, стоявшего выше без своего
            # значения, либо продолжение позиционной части.
            if pending_key is not None and not positional.get("_first"):
                subcommands[pending_key] = stripped
                pending_key = None
            else:
                first_chunk.append(stripped)
            continue

        # Подкоманда найдена. Значение берётся после «=», а если его нет - из
        # остатка строки: «MISSING LISTWISE» это поле и его значение.
        rest_value = value.strip() if _sep else ""
        if not _sep:
            parts = head.split(None, 1)
            rest_value = parts[1].strip() if len(parts) > 1 else ""
        subcommands[head_word] = rest_value
        # Если у поля значения нет, оно может оказаться на следующей строке там,
        # где ещё нет никаких переменных.
        if not rest_value and not first_chunk and index + 1 < len(tail_lines):
            following = tail_lines[index + 1]
            following_head = following.lstrip("/").split(None, 1)[0].upper()
            if following_head not in _KNOWN_FIELDS and not _looks_like_field(
                following.lstrip("/")
            ):
                subcommands[head_word] = following
                pending_key = None
                tail_lines[index + 1] = ""
                continue
        pending_key = head_word if not rest_value else None

    if first_chunk:
        positional["_first"] = " ".join(chunk for chunk in first_chunk if chunk)
    return name, subcommands, positional


def _looks_like_field(line: str) -> bool:
    """Похожа ли строка на подкоманду «ПОЛЕ=значение» или «ПОЛЕ значение»?

    Признак подкоманды - слово заглавными буквами в начале строки. Строка вида
    «income / 1000» подкомандой не является: первое слово написано строчными.
    Это важно, иначе выражение вычисляемой переменной развалилось бы на части.
    """
    parts = line.split(None, 1)
    if not parts:
        return False
    word = parts[0].split("=")[0]
    if not word or not word.replace("-", "").isalpha():
        return False
    return word.upper() == word


def _split_variables(value: str) -> list[str]:
    """Разбирает список переменных, разделённых пробелами или запятыми.

    Слова с «=» (например «VARIABLES=age») отбрасываются: значение поля может
    прийти вместе со своим именем, и имя поля переменной не является.
    """
    cleaned = value.replace(",", " ")
    result: list[str] = []
    for part in cleaned.split():
        if "=" in part:
            # «VARIABLES=age» или «METHOD=ENTER»: берём часть после «=».
            tail = part.split("=", 1)[1]
            if tail:
                result.append(tail)
            continue
        result.append(part)
    return result


def _first_variable(value: str) -> str | None:
    variables = _split_variables(value)
    return variables[0] if variables else None


def _numbers(value: str) -> list[float]:
    numbers: list[float] = []
    for part in value.replace(",", " ").split():
        try:
            numbers.append(float(part))
        except ValueError:
            continue
    return numbers


def build_command(name: str, subcommands: dict[str, str], positional: dict[str, str], dataset):
    """Собирает объект команды по имени процедуры и подкомандам.

    Разбор идёт по имени процедуры, а не по её ключу: в файле синтаксиса стоит
    именно имя (FREQUENCIES, DESCRIPTIVES, REGRESSION), как его пишет сама
    программа при сохранении.
    """
    from winnow.stats import charts as charts_module

    name = name.upper()
    handler = _HANDLERS.get(name)
    if handler is None:
        known = ", ".join(sorted(_HANDLERS))
        raise SyntaxError_(f"команда «{name}» не поддерживается. Известны: {known}")
    return handler(subcommands, positional, dataset)


# ---------------------------------------------------------------------------
# Сборка команд по имени процедуры
# ---------------------------------------------------------------------------


def _variables_from(subcommands: dict[str, str], positional: dict[str, str], *keys: str) -> str:
    """Ищет список переменных в подкомандах или в позиционной части.

    Значение подкоманды может содержать служебное слово: «METHOD=ENTER age
    anxiety» - здесь переменные идут после ENTER. Служебное слово отбрасывается.
    """
    for key in keys:
        base = key.split("=")[0]
        value = subcommands.get(base)
        if not value:
            continue
        if "=" in key:
            marker = key.split("=")[1].upper()
            upper = value.upper()
            if marker in upper:
                position = upper.index(marker) + len(marker)
                return value[position:].strip()
            continue
        return value
    # Значения может не быть в подкоманде: тогда переменные идут в позиционной
    # части первым списком.
    return positional.get("_first", "")


def _by_parts(value: str) -> tuple[list[str], list[str]]:
    """Разбирает запись «A BY B» на две части.

    Используется в ANOVA и непараметрических критериях: слева зависимые
    переменные, справа группирующая.
    """
    upper = value.upper()
    if " BY " in upper:
        position = upper.index(" BY ")
        left = value[:position]
        right = value[position + 4 :]
        return _split_variables(left), _split_variables(right)
    return _split_variables(value), []


def _frequencies(subcommands, positional, dataset):
    from winnow.stats.command import FrequenciesCommand

    variables = _split_variables(_variables_from(subcommands, positional, "VARIABLES"))
    return FrequenciesCommand(dataset=dataset, variables=variables)


def _descriptives(subcommands, positional, dataset):
    from winnow.stats.command import DescriptivesCommand

    variables = _split_variables(_variables_from(subcommands, positional, "VARIABLES"))
    return DescriptivesCommand(dataset=dataset, variables=variables)


def _crosstabs(subcommands, positional, dataset):
    from winnow.stats.command import CrosstabsCommand

    tables = subcommands.get("TABLES") or positional.get("_first", "")
    row_vars: list[str] = []
    col_vars: list[str] = []
    if " BY " in tables.upper():
        left, _sep, right = tables.upper().partition(" BY ")
        # В подкоманде TABLES имена пишутся в исходном регистре, поэтому режем
        # исходную строку по той же позиции, что нашли в верхнем регистре.
        left_original = tables[: len(left)]
        right_original = tables[len(left) + 4 :]
        row_vars = _split_variables(left_original)
        col_vars = _split_variables(right_original)
    elif tables:
        row_vars = _split_variables(tables)
    return CrosstabsCommand(dataset=dataset, row_vars=row_vars, col_vars=col_vars)


def _ttest(subcommands, positional, dataset):
    from winnow.stats.command import TTestCommand

    variables = _split_variables(subcommands.get("VARIABLES", ""))
    if not variables:
        variables = _split_variables(_variables_from(subcommands, positional, "TEST"))
    groups = subcommands.get("GROUPS", "")
    kind = "independent"
    group_var = None
    group_values: list[float] = []
    if groups:
        # Запись «gender(1 2)»: имя группирующей переменной и коды групп.
        head, _sep, tail = groups.partition("(")
        group_var = _first_variable(head)
        group_values = _numbers(tail.rstrip(")"))
    if subcommands.get("PAIRS"):
        kind = "related"
    return TTestCommand(
        dataset=dataset,
        kind=kind,
        test_vars=variables,
        group_var=group_var,
        group_values=group_values,
    )


def _anova(subcommands, positional, dataset):
    from winnow.stats.command import AnovaCommand

    body = _variables_from(subcommands, positional, "VARIABLES")
    dependent, factors = _by_parts(body)
    factor = factors[0] if factors else _first_variable(subcommands.get("FACTOR", ""))
    post_hoc = (subcommands.get("POSTHOC") or "tukey").lower()
    return AnovaCommand(
        dataset=dataset, dependent=dependent, factor=factor, post_hoc=post_hoc
    )


def _nonparametric(subcommands, positional, dataset):
    from winnow.stats.command import NonparametricCommand

    # Запись «/M-W K-W=anxiety BY education»: слева метод, справа переменные.
    # Короткие имена методов из синтаксиса переводятся в полные.
    aliases = {
        "M-W": "mann_whitney",
        "MANN-WHITNEY": "mann_whitney",
        "K-W": "kruskal_wallis",
        "KRUSKAL-WALLIS": "kruskal_wallis",
        "WILCOXON": "wilcoxon",
        "FRIEDMAN": "friedman",
    }
    method = "auto"
    body = ""
    for key, value in subcommands.items():
        if key in aliases:
            method = aliases[key]
            body = value
            break
    if not body:
        body = positional.get("_first", "").lstrip("/")
        # Ключом может оказаться целая строка вида «M-W K-W=...»: отделяем метод
        # от переменных по знаку равенства.
        head, _sep, tail = body.partition("=")
        if _sep:
            first_method = head.split()[0] if head.split() else ""
            method = aliases.get(first_method.upper(), "auto")
            body = tail
    test_vars, factors = _by_parts(body)
    group_var = factors[0] if factors else None
    return NonparametricCommand(
        dataset=dataset,
        kind="independent",
        method=method,
        test_vars=test_vars,
        group_var=group_var,
    )


def _correlations(subcommands, positional, dataset):
    from winnow.stats.command import CorrelationsCommand

    variables = _split_variables(_variables_from(subcommands, positional, "VARIABLES"))
    return CorrelationsCommand(dataset=dataset, variables=variables)


def _linear_regression(subcommands, positional, dataset):
    from winnow.stats.command import LinearRegressionCommand

    dependent = _first_variable(subcommands.get("DEPENDENT", ""))
    predictors = _split_variables(
        _variables_from(subcommands, positional, "METHOD=ENTER", "METHOD")
    )
    return LinearRegressionCommand(dataset=dataset, dependent=dependent, predictors=predictors)


def _logistic_regression(subcommands, positional, dataset):
    from winnow.stats.command import LogisticRegressionCommand

    # Зависимая переменная стоит в позиционной части («LOGISTIC REGRESSION
    # VARIABLES xxx»), а подкоманды её не задают. Если поле VARIABLES без
    # значения, зависимая переменная окажется первой в позиционной части.
    variables = _split_variables(subcommands.get("VARIABLES", ""))
    if not variables:
        head = positional.get("_first", "").replace("VARIABLES", " ").strip()
        variables = _split_variables(head)
    dependent = variables[0] if variables else None
    predictors = _split_variables(
        _variables_from(subcommands, positional, "METHOD=ENTER", "METHOD")
    )
    return LogisticRegressionCommand(
        dataset=dataset, dependent=dependent, predictors=predictors
    )


def _compute(subcommands, positional, dataset):
    from winnow.stats.command import ComputeCommand

    first = positional.get("_first", "")
    # Выражение может содержать пробелы, поэтому режем только по первому «=».
    match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", first, re.DOTALL)
    if match is None:
        raise SyntaxError_(
            "не удалось разобрать вычисление: ожидается «ИМЯ = выражение»", text=first
        )
    return ComputeCommand(
        dataset=dataset,
        target=match.group(1),
        expression=match.group(2).strip(),
        label=subcommands.get("LABEL", ""),
    )


def _recode(subcommands, positional, dataset):
    from winnow.stats.command import RecodeCommand, RecodeRule

    first = positional.get("_first", "")
    source = _first_variable(first)
    target = _first_variable(subcommands.get("INTO", ""))
    return RecodeCommand(dataset=dataset, source=source, target=target or "", rules=[RecodeRule(kind="else", new_value=1)])


def _reliability(subcommands, positional, dataset):
    from winnow.stats.command import ReliabilityCommand

    items = _split_variables(_variables_from(subcommands, positional, "VARIABLES"))
    return ReliabilityCommand(dataset=dataset, items=items)


def _factor(subcommands, positional, dataset):
    from winnow.stats.command import FactorCommand

    variables = _split_variables(_variables_from(subcommands, positional, "VARIABLES"))
    rotation = (subcommands.get("ROTATION") or "varimax").lower()
    return FactorCommand(
        dataset=dataset,
        variables=variables,
        rotation=rotation if rotation != "norotate" else "none",
    )


def _graph(subcommands, positional, dataset):
    from winnow.stats.charts import ChartCommand

    kind = "histogram"
    variables: list[str] = []
    category = None
    if "HISTOGRAM" in subcommands:
        kind = "histogram"
        variables = _split_variables(subcommands["HISTOGRAM"])
    elif "BOXPLOT" in subcommands:
        kind = "boxplot"
        body = subcommands["BOXPLOT"]
        if " BY " in body.upper():
            position = body.upper().index(" BY ")
            variables = _split_variables(body[:position])
            category = _first_variable(body[position + 4 :])
        else:
            variables = _split_variables(body)
    elif "SCATTERPLOT" in subcommands:
        kind = "scatter"
        body = subcommands["SCATTERPLOT"]
        parts = body.upper().split(" WITH ")
        if len(parts) == 2:
            first_part = body[: len(parts[0])]
            second_part = body[len(parts[0]) + 6 :]
            variables = _split_variables(first_part) + _split_variables(second_part)
        else:
            variables = _split_variables(body)
    elif "BAR" in subcommands:
        kind = "bar"
        category = _first_variable(subcommands["BAR"])
    elif "PIE" in subcommands:
        kind = "pie"
        category = _first_variable(subcommands["PIE"])
    elif "LINE" in subcommands:
        kind = "line"
        body = subcommands["LINE"]
        variables = _split_variables(body.replace("(SIMPLE)", ""))
        category = _first_variable(body.split(" BY ")[-1]) if " BY " in body.upper() else None
    return ChartCommand(dataset=dataset, kind=kind, variables=variables, category=category)


_HANDLERS = {
    "FREQUENCIES": _frequencies,
    "DESCRIPTIVES": _descriptives,
    "CROSSTABS": _crosstabs,
    "T-TEST": _ttest,
    "TTEST": _ttest,
    "ONEWAY": _anova,
    "NPAR": _nonparametric,
    "NPAR TESTS": _nonparametric,
    "CORRELATIONS": _correlations,
    "REGRESSION": _linear_regression,
    "LOGISTIC REGRESSION": _logistic_regression,
    "COMPUTE": _compute,
    "RECODE": _recode,
    "RELIABILITY": _reliability,
    "FACTOR": _factor,
    "GRAPH": _graph,
}


# ---------------------------------------------------------------------------
# Разбор и выполнение
# ---------------------------------------------------------------------------


def parse_syntax(text: str, dataset) -> list[Command]:
    """Разбирает текст синтаксиса в список готовых к выполнению команд.

    Ошибка разбора останавливает работу и указывает строку: молча пропустить
    команду нельзя, иначе пользователь решит, что анализ выполнен полностью.
    """
    commands: list[Command] = []
    for line, body in split_commands(text):
        if not body.strip() or body.strip().startswith("*"):
            continue
        try:
            name, subcommands, positional = parse_subcommands(body)
        except CommandError as exc:
            raise SyntaxError_(str(exc), line, body) from None
        try:
            command = build_command(name, subcommands, positional, dataset)
        except CommandError as exc:
            raise SyntaxError_(str(exc), line, body) from None
        try:
            command.validate()
        except CommandError as exc:
            raise SyntaxError_(str(exc), line, body) from None
        commands.append(command)
    return commands


def execute_syntax(text: str, dataset) -> list[Any]:
    """Разбирает синтаксис и выполняет его, возвращая результаты."""
    results = []
    for command in parse_syntax(text, dataset):
        results.append(command.execute())
    return results


def save_syntax(commands: list[Command], path: str | Path, title: str = "") -> Path:
    """Сохраняет синтаксис в файл `.sps`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Кодировка utf-8: русские метки переменных в синтаксисе должны читаться.
    path.write_text(build_syntax(commands, title), encoding="utf-8")
    return path


def load_syntax(path: str | Path, dataset) -> list[Command]:
    """Читает файл `.sps` и возвращает готовые команды."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_syntax(text, dataset)


__all__ = [
    "SyntaxCommand",
    "SyntaxError_",
    "build_command",
    "build_syntax",
    "execute_syntax",
    "load_syntax",
    "parse_subcommands",
    "parse_syntax",
    "save_syntax",
    "split_commands",
]
