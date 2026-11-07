"""«Простыми словами»: человеческий вывод из чисел отчёта.

Отчёт показывает «t = -2,695, p = 0,008, d = -0,38». Опытный исследователь
прочитает это сразу, начинающий видит набор чисел и не понимает, что из них
следует. А нужен именно вывод: значима ли разница, в какую сторону, велика ли
она и чего из результата НЕ следует.

Почему формулировки собраны в одном месте. Одна и та же мысль должна звучать
одинаково во всех процедурах, иначе программа выглядит собранной из кусков.
Процедура передаёт сюда числа, а текст получается здесь.

Почему функции возвращают пары «вид, текст», а не готовые выводы. Вид
(«вывод»/«предупреждение»/«пояснение») определяет процедура-владелец отчёта,
и она же решает, в каком порядке выводы идут. Здесь только слова.
"""

from __future__ import annotations

import math

# Виды выводов - те же, что понимает Result.
CONCLUSION = "conclusion"
CAUTION = "caution"
NOTE = "note"

Finding = tuple[str, str]


def format_p(p_value: float) -> str:
    """Значимость в русской записи: 0,008 или «меньше 0,001»."""
    if p_value is None or not math.isfinite(p_value):
        return "значимость не определена"
    if p_value < 0.001:
        return "p < 0,001"
    return f"p = {p_value:.3f}".replace(".", ",")


def format_number(value: float, decimals: int = 2) -> str:
    """Число в русской записи: десятичная запятая вместо точки."""
    if value is None or not math.isfinite(value):
        return "—"
    text = f"{value:.{decimals}f}"
    # Тысячи разделяются пробелом: «47 571» читается, «47571.32» - нет.
    whole, _dot, fraction = text.partition(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    grouped = f"{int(digits):,}".replace(",", " ") if digits.isdigit() else digits
    return f"{sign}{grouped},{fraction}" if fraction else f"{sign}{grouped}"


def effect_word(value: float) -> str:
    """Словесная оценка размера эффекта по Коэну."""
    magnitude = abs(value)
    if magnitude < 0.2:
        return "очень малый"
    if magnitude < 0.5:
        return "малый"
    if magnitude < 0.8:
        return "средний"
    if magnitude < 1.3:
        return "большой"
    return "очень большой"


def _significance(p_value: float) -> bool:
    return math.isfinite(p_value) and p_value < 0.05


def compare_two_groups(
    *,
    outcome: str,
    group1: str,
    group2: str,
    n1: int,
    n2: int,
    mean1: float,
    mean2: float,
    p_value: float,
    effect: float | None = None,
    welch: bool = False,
) -> list[Finding]:
    """Вывод о сравнении двух групп."""
    findings: list[Finding] = []
    if not math.isfinite(p_value):
        return [(CAUTION, f"{outcome}: значимость не вычислилась, сравнение ненадёжно.")]

    difference = mean1 - mean2
    higher, lower = (group1, group2) if difference > 0 else (group2, group1)
    higher_mean = max(mean1, mean2)
    lower_mean = min(mean1, mean2)

    if _significance(p_value):
        sentence = (
            f"Различия статистически значимы: группы «{group1}» и «{group2}» "
            f"различаются по показателю «{outcome}» ({format_p(p_value)}). "
            f"Среднее значение выше у группы «{higher}»: "
            f"{format_number(higher_mean)} против {format_number(lower_mean)}"
        )
        if effect is not None and math.isfinite(effect):
            # Величина по модулю: направление уже сказано словами («выше у
            # группы ...»), а минус рядом с ним только сбивает с толку.
            sentence += (
                f", величина эффекта d = {format_number(abs(effect))} — "
                f"{effect_word(effect)}."
            )
        else:
            sentence += "."
        sentence += f" В группах {n1} и {n2} случаев."
        findings.append((CONCLUSION, sentence))
    else:
        findings.append(
            (
                CONCLUSION,
                f"Статистически значимых различий не найдено: средние значения по "
                f"показателю «{outcome}» у групп «{group1}» и «{group2}» "
                f"различаются случайно ({format_p(p_value)}). Средние: "
                f"{format_number(mean1)} и {format_number(mean2)}, в группах "
                f"{n1} и {n2} случаев.",
            )
        )
        findings.append(
            (
                NOTE,
                "Отсутствие значимых различий не доказывает, что группы "
                "одинаковы: при небольшом числе случаев даже заметная разница "
                "может оказаться случайной.",
            )
        )

    if n1 < 10 or n2 < 10:
        findings.append(
            (
                CAUTION,
                f"В одной из групп меньше десяти случаев ({n1} и {n2}). "
                "Критерий Стьюдента на таких данных чувствителен к выбросам — "
                "проверьте вывод непараметрическим критерием.",
            )
        )

    if effect is not None and math.isfinite(effect) and abs(effect) >= 1.5:
        findings.append(
            (
                CAUTION,
                "Разница неправдоподобно велика. Проверьте, не выведена ли "
                "переменная-группа из самого показателя: например, возраст, "
                "разбитый на возрастные группы, всегда будет от них отличаться. "
                "Такой результат ничего не доказывает.",
            )
        )

    if welch:
        findings.append(
            (
                NOTE,
                "Здесь читается строка с неравными дисперсиями (поправка Уэлча). "
                "Тест Ливиня в таблице показывает, почему выбран этот вариант: "
                "он значим, то есть дисперсии групп различаются.",
            )
        )
    return findings


def correlation(
    *,
    first: str,
    second: str,
    coefficient: float,
    p_value: float,
    n: int,
    method: str = "pearson",
) -> list[Finding]:
    """Вывод о связи двух количественных показателей."""
    findings: list[Finding] = []
    if not math.isfinite(coefficient):
        return [(CAUTION, f"{first} и {second}: связь не вычислилась.")]

    strength = abs(coefficient)
    if strength < 0.3:
        word = "слабая"
    elif strength < 0.5:
        word = "умеренная"
    elif strength < 0.7:
        word = "заметная"
    else:
        word = "сильная"
    direction = "прямая" if coefficient > 0 else "обратная"
    trend = (
        "чем больше одно, тем больше другое"
        if coefficient > 0
        else "чем больше одно, тем меньше другое"
    )

    if _significance(p_value):
        findings.append(
            (
                CONCLUSION,
                f"Связь статистически значима и {word}: r = "
                f"{format_number(coefficient, 3)} ({format_p(p_value)}, "
                f"{n} случаев). Связь {direction} — {trend}.",
            )
        )
    else:
        findings.append(
            (
                CONCLUSION,
                f"Статистически значимой связи между «{first}» и «{second}» не "
                f"найдено (r = {format_number(coefficient, 3)}, "
                f"{format_p(p_value)}, {n} случаев).",
            )
        )

    findings.append(
        (
            CAUTION,
            "Связь не означает причину: возможно, на оба показателя влияет "
            "третий, которого нет в расчёте. Проверить это позволяет "
            "регрессия с несколькими предикторами.",
        )
    )
    if method == "pearson" and n < 30:
        findings.append(
            (
                CAUTION,
                f"Случаев немного ({n}). Коэффициент Пирсона чувствителен к "
                "выбросам — сравните результат с ранговой корреляцией "
                "(Спирмен), она устойчивее.",
            )
        )
    return findings


def association(
    *,
    first: str,
    second: str,
    p_value: float,
    cramers_v: float | None,
    n: int,
    has_small_expected: bool = False,
) -> list[Finding]:
    """Вывод о связи двух категориальных переменных."""
    findings: list[Finding] = []
    if not math.isfinite(p_value):
        return [(CAUTION, f"{first} и {second}: связь не вычислилась.")]

    if cramers_v is not None and math.isfinite(cramers_v):
        strength = abs(cramers_v)
        word = (
            "слабая"
            if strength < 0.2
            else "умеренная"
            if strength < 0.35
            else "заметная"
            if strength < 0.5
            else "сильная"
        )
        measure = f"V Крамера = {format_number(cramers_v, 3)} ({word} связь)"
    else:
        measure = "сила связи не определена"

    if _significance(p_value):
        findings.append(
            (
                CONCLUSION,
                f"Признаки связаны: распределение «{first}» зависит от «{second}» "
                f"({format_p(p_value)}, {measure}, {n} случаев).",
            )
        )
    else:
        findings.append(
            (
                CONCLUSION,
                f"Связи между «{first}» и «{second}» не найдено "
                f"({format_p(p_value)}, {measure}, {n} случаев).",
            )
        )

    if has_small_expected:
        findings.append(
            (
                CAUTION,
                "Часть ожидаемых частот меньше пяти. Хи-квадрат в таком случае "
                "ненадёжен: объедините редкие категории или соберите больше "
                "данных.",
            )
        )
    return findings


def normality_caution(
    *, outcome: str, groups: list[str], alternative: str
) -> list[Finding]:
    """Предупреждение о ненормальности распределения вместе с советом.

    Проверка сама по себе бесполезна: пользователь видит «Шапиро p = 0,003» и не
    знает, что с этим делать. Поэтому числу сопутствует название критерия, который
    подходит вместо применённого.
    """
    if not groups:
        return []
    listed = "», «".join(groups)
    return [
        (
            CAUTION,
            f"Распределение показателя «{outcome}» в группе «{listed}» отличается "
            "от нормального (критерий Шапиро-Уилка, p < 0,05). Критерий Стьюдента "
            f"предполагает нормальность; на таких данных надёжнее {alternative} — "
            "он сравнивает не средние, а ранги.",
        )
    ]


def eta_word(value: float) -> str:
    """Словесная оценка доли объяснённой дисперсии (эта- и омега-квадрат).

    Пороги здесь другие, чем у d Коэна: 0,01 - малая доля, 0,06 - средняя,
    0,14 - большая. Это не «на глаз»: так принято в литературе, и путать шкалы
    оценок нельзя.
    """
    magnitude = abs(value)
    if magnitude < 0.01:
        return "ничтожный"
    if magnitude < 0.06:
        return "малый"
    if magnitude < 0.14:
        return "средний"
    return "большой"


def compare_several_groups(
    *,
    outcome: str,
    factor: str,
    group_count: int,
    n: int,
    f_value: float,
    df_between: float,
    df_within: float,
    p_value: float,
    eta_squared: float | None = None,
    extremes: tuple[str, str, str, str] | None = None,
) -> list[Finding]:
    """Вывод о сравнении трёх и более групп.

    extremes - (группа с наибольшим средним, её среднее, группа с наименьшим,
    её среднее): без этого вывод сообщает только «различия есть», а человеку
    нужно знать, между кем.
    """
    findings: list[Finding] = []
    if not math.isfinite(p_value):
        return [(CAUTION, f"{outcome}: значимость не вычислилась, сравнение ненадёжно.")]

    statistic = (
        f"F({df_between:.0f}, {df_within:.0f}) = {format_number(f_value)}, "
        f"{format_p(p_value)}"
    )
    if _significance(p_value):
        sentence = (
            f"Различия между группами статистически значимы: показатель "
            f"«{outcome}» различается по «{factor}» ({statistic}, групп "
            f"{group_count}, случаев {n})."
        )
        if extremes is not None:
            high_label, high_mean, low_label, low_mean = extremes
            sentence += (
                f" Наибольшее среднее у группы «{high_label}» "
                f"({format_number(high_mean)}), наименьшее — у «{low_label}» "
                f"({format_number(low_mean)})."
            )
        if eta_squared is not None and math.isfinite(eta_squared):
            sentence += (
                f" Группировка объясняет {format_number(eta_squared * 100, 1)} % "
                f"разброса показателя — эффект {eta_word(eta_squared)}."
            )
        findings.append((CONCLUSION, sentence))
        findings.append(
            (
                NOTE,
                "Дисперсионный анализ отвечает на вопрос «есть ли различия хотя "
                "бы между двумя группами», но не говорит, между какими именно. "
                "Смотрите апостериорные сравнения ниже.",
            )
        )
    else:
        findings.append(
            (
                CONCLUSION,
                f"Статистически значимых различий между группами не найдено: "
                f"показатель «{outcome}» не различается по «{factor}» "
                f"({statistic}, групп {group_count}, случаев {n}).",
            )
        )
        findings.append(
            (
                NOTE,
                "Отсутствие значимых различий не доказывает, что группы "
                "одинаковы: при небольшом числе случаев разница могла остаться "
                "незамеченной.",
            )
        )
    return findings


def variance_caution(
    *, outcome: str, levene_p: float, robust: str
) -> list[Finding]:
    """Совет при неоднородных дисперсиях: обычный F-критерий ненадёжен."""
    if not math.isfinite(levene_p) or levene_p >= 0.05:
        return []
    return [
        (
            CAUTION,
            f"Дисперсии групп различаются (тест Ливиня, {format_p(levene_p)}). "
            f"Обычный F-критерий для «{outcome}» в таком случае ненадёжен: "
            f"читайте {robust}.",
        )
    ]


def linear_model(
    *,
    outcome: str,
    n: int,
    r_squared: float,
    adj_r_squared: float | None,
    f_value: float,
    df_regression: float,
    df_residual: float,
    p_value: float,
    predictors: list[tuple[str, float, float]],
    durbin_watson: float | None = None,
    duplicated: list[str] | None = None,
) -> list[Finding]:
    """Вывод по линейной регрессии.

    predictors - список троек «название, коэффициент, значимость», по одному на
    предиктор. В вывод попадают только значимые: перечислять все подряд в
    человеческой фразе бессмысленно.
    """
    findings: list[Finding] = []
    if not math.isfinite(r_squared) or not math.isfinite(p_value):
        return [(CAUTION, f"{outcome}: модель не удалось оценить, проверьте пропуски.")]

    share = format_number(r_squared * 100, 1)
    statistic = (
        f"R² = {format_number(r_squared, 3)}, "
        f"F({df_regression:.0f}, {df_residual:.0f}) = {format_number(f_value)}, "
        f"{format_p(p_value)}"
    )

    significant = [
        (name, coefficient)
        for name, coefficient, predictor_p in predictors
        if math.isfinite(predictor_p) and predictor_p < 0.05
    ]

    if _significance(p_value):
        sentence = (
            f"Модель значима: она объясняет {share} % разброса показателя "
            f"«{outcome}» ({statistic}, случаев {n})."
        )
        if significant:
            listed = ", ".join(
                f"«{name}» (коэффициент {format_number(coefficient)})"
                for name, coefficient in significant[:3]
            )
            sentence += f" Значимые предикторы: {listed}."
            if len(significant) > 3:
                sentence += f" Всего значимых предикторов: {len(significant)}."
        else:
            sentence += " Но ни один отдельный предиктор не значим."
        if adj_r_squared is not None and math.isfinite(adj_r_squared):
            sentence += (
                f" С поправкой на число предикторов объяснённая доля "
                f"{format_number(adj_r_squared * 100, 1)} %."
            )
        findings.append((CONCLUSION, sentence))
    else:
        findings.append(
            (
                CONCLUSION,
                f"Модель статистически незначима: предикторы не объясняют "
                f"показатель «{outcome}» ({statistic}, случаев {n}).",
            )
        )

    if significant:
        findings.append(
            (
                NOTE,
                "Коэффициент показывает, на сколько в среднем меняется показатель "
                "при увеличении этого признака на единицу, если остальные признаки "
                "не меняются. Знак говорит о направлении связи.",
            )
        )

    if r_squared > 0.95:
        findings.append(
            (
                CAUTION,
                f"Модель объясняет {share} % разброса — почти всё. Для реальных "
                "данных это редкость: проверьте, не входит ли в предикторы сам "
                "показатель, его пересчёт или признак, из которого он получен.",
            )
        )

    if durbin_watson is not None and math.isfinite(durbin_watson):
        if durbin_watson < 1.0 or durbin_watson > 3.0:
            findings.append(
                (
                    CAUTION,
                    f"Значение Дарбина-Уотсона {format_number(durbin_watson)} далеко "
                    "от 2. Остатки модели связаны между собой, и оценки "
                    "коэффициентов могут быть смещены: проверьте, не зависят ли "
                    "случаи друг от друга (например, это повторные измерения).",
                )
            )

    if duplicated:
        findings.append(
            (
                CAUTION,
                "Предикторы «" + "», «".join(duplicated) + "» дублируют друг друга "
                "(высокий VIF). Оставьте один из них: иначе коэффициенты "
                "неустойчивы и меняются от добавления любого случая.",
            )
        )
    return findings


def logistic_model(
    *,
    outcome: str,
    event: str,
    n: int,
    pseudo_r_squared: float | None,
    accuracy: float | None,
    predictors: list[tuple[str, float, float]],
    converged: bool = True,
) -> list[Finding]:
    """Вывод по логистической регрессии.

    predictors - тройки «название, отношение шансов, значимость». Отношение
    шансов переводится на человеческий язык: «шансы выше в 2,4 раза» вместо
    «Exp(B) = 2,4».
    """
    findings: list[Finding] = []
    significant = [
        (name, odds)
        for name, odds, predictor_p in predictors
        if math.isfinite(predictor_p) and predictor_p < 0.05
    ]

    sentence = f"Модель предсказывает событие «{event}» у переменной «{outcome}»"
    if accuracy is not None and math.isfinite(accuracy):
        sentence += f": доля верных предсказаний {format_number(accuracy * 100, 1)} %"
    if pseudo_r_squared is not None and math.isfinite(pseudo_r_squared):
        sentence += (
            f", объяснённая доля (псевдо-R² Найджелкерка) "
            f"{format_number(pseudo_r_squared, 3)}"
        )
    sentence += f", случаев {n}."

    if significant:
        parts = []
        for name, odds in significant[:3]:
            if not math.isfinite(odds) or odds <= 0:
                continue
            if odds >= 1:
                parts.append(
                    f"«{name}» повышает шансы в {format_number(odds)} раза"
                )
            else:
                # Обратное отношение понятнее, чем «в 0,4 раза».
                parts.append(
                    f"«{name}» снижает шансы в {format_number(1 / odds)} раза"
                )
        if parts:
            sentence += " Значимые признаки: " + "; ".join(parts) + "."
        else:
            sentence += " Но ни один отдельный признак не значим."
    else:
        sentence += " Ни один отдельный признак не значим."

    findings.append((CONCLUSION, sentence))

    if significant:
        findings.append(
            (
                NOTE,
                "«Повышает шансы в 2 раза» означает: при увеличении признака на "
                "единицу шансы события удваиваются, а не вероятность. Остальные "
                "признаки при этом считаются неизменными.",
            )
        )
    else:
        findings.append(
            (
                NOTE,
                "Отсутствие значимых признаков не значит, что предсказать нечего: "
                "возможно, признаков мало, они измерены грубо или событий слишком "
                "мало для устойчивых оценок.",
            )
        )

    if not converged:
        findings.append(
            (
                CAUTION,
                "Расчёт не сошёлся: оценки коэффициентов ненадёжны. Обычно это "
                "бывает при полном разделении — когда признак идеально предсказывает "
                "событие. Проверьте, нет ли такого признака.",
            )
        )
    if accuracy is not None and math.isfinite(accuracy) and accuracy < 0.7:
        findings.append(
            (
                CAUTION,
                f"Доля верных предсказаний {format_number(accuracy * 100, 1)} % "
                "невысока. Для практического прогноза такой модели мало, хотя "
                "отдельные признаки могут быть значимы.",
            )
        )
    return findings


def rank_difference(
    *,
    outcome: str,
    method_title: str,
    p_value: float,
    statistic_name: str,
    statistic: float,
    groups: list[tuple[str, float, int]],
    effect: float | None = None,
) -> list[Finding]:
    """Вывод по ранговому критерию (Манна-Уитни, Краскела-Уоллиса).

    groups - тройки «название, средний ранг, число случаев». Сравниваются именно
    ранги, а не средние: путать их нельзя, потому что «средний ранг выше» не
    означает «среднее значение выше» без дополнительной проверки.
    """
    findings: list[Finding] = []
    if not math.isfinite(p_value):
        return [(CAUTION, f"{outcome}: значимость не вычислилась, критерий не применён.")]

    ordered = sorted(
        [group for group in groups if math.isfinite(group[1])],
        key=lambda group: group[1],
        reverse=True,
    )
    statistic_text = (
        f"{statistic_name} = {format_number(statistic)}, {format_p(p_value)}"
    )

    if _significance(p_value):
        if len(ordered) == 2:
            (high_label, high_rank, _high_n), (low_label, low_rank, _low_n) = ordered
            sentence = (
                f"Значения различаются статистически значимо: в группе "
                f"«{high_label}» они в среднем выше, чем в «{low_label}» "
                f"(средний ранг {format_number(high_rank, 1)} против "
                f"{format_number(low_rank, 1)}; {method_title}, {statistic_text})."
            )
            if effect is not None and math.isfinite(effect):
                sentence += (
                    f" Величина эффекта {format_number(abs(effect), 2)} — "
                    f"{effect_word(effect)}."
                )
        else:
            sentence = (
                f"Хотя бы две группы различаются статистически значимо "
                f"({method_title}, {statistic_text}). Групп {len(ordered)}."
            )
            if ordered:
                sentence += (
                    f" Выше всего значения в группе «{ordered[0][0]}» "
                    f"(средний ранг {format_number(ordered[0][1], 1)}), ниже всего — "
                    f"в «{ordered[-1][0]}» ({format_number(ordered[-1][1], 1)})."
                )
        findings.append((CONCLUSION, sentence))
        findings.append(
            (
                NOTE,
                "Критерий сравнивает не средние значения, а порядок: он отвечает "
                "на вопрос «в какой группе значения в целом выше», а не «на "
                "сколько». Это надёжнее при ненормальном распределении, но менее "
                "чувствительно.",
            )
        )
    else:
        findings.append(
            (
                CONCLUSION,
                f"Статистически значимых различий не найдено ({method_title}, "
                f"{statistic_text}, групп {len(groups)}).",
            )
        )
        findings.append(
            (
                NOTE,
                "Отсутствие различий не доказывает, что группы одинаковы: "
                "ранговые критерии менее чувствительны, и на малой выборке "
                "разница могла остаться незамеченной.",
            )
        )
    return findings


def factor_structure(
    *,
    variables: int,
    n_factors: int,
    explained: float,
    kmo: float,
    bartlett_p: float,
) -> list[Finding]:
    """Вывод по факторному анализу.

    Главный вопрос новичка здесь не «сколько факторов», а «можно ли вообще было
    это делать»: ответ на него даёт KMO вместе с критерием Бартлетта.
    """
    findings: list[Finding] = []

    if math.isfinite(kmo):
        if kmo >= 0.8:
            quality = "хорошая"
        elif kmo >= 0.7:
            quality = "приемлемая"
        elif kmo >= 0.6:
            quality = "посредственная"
        elif kmo >= 0.5:
            quality = "слабая"
        else:
            quality = "недостаточная"
        sentence = (
            f"Выделено факторов: {n_factors}. Они объясняют "
            f"{format_number(explained * 100, 1)} % разброса "
            f"{variables} переменных. Мера адекватности KMO = "
            f"{format_number(kmo, 2)} — пригодность данных {quality}."
        )
        if math.isfinite(bartlett_p):
            sentence += (
                f" Критерий Бартлетта {format_p(bartlett_p)}: "
                + (
                    "корреляции между переменными есть, анализ имеет смысл."
                    if _significance(bartlett_p)
                    else "связи между переменными не обнаружено, выделять факторы "
                    "не из чего."
                )
            )
        findings.append((CONCLUSION, sentence))
    else:
        findings.append(
            (
                CONCLUSION,
                f"Выделено факторов: {n_factors}, они объясняют "
                f"{format_number(explained * 100, 1)} % разброса переменных.",
            )
        )

    if math.isfinite(kmo) and kmo < 0.5:
        findings.append(
            (
                CAUTION,
                "Значение KMO ниже 0,5 означает, что данные плохо подходят для "
                "факторного анализа: общих закономерностей между переменными почти "
                "нет. Результат стоит воспринимать как предварительный.",
            )
        )

    findings.append(
        (
            NOTE,
            "Факторный анализ показывает, какие переменные меняются вместе, но не "
            "называет факторы: смысл каждому фактору присваивает исследователь по "
            "наибольшим нагрузкам. Проверьте, что в одном факторе собрались "
            "переменные, близкие по смыслу.",
        )
    )
    return findings


def reliability(
    *,
    items: int,
    alpha: float,
    n: int,
    worst_item: str | None = None,
    worst_alpha: float | None = None,
) -> list[Finding]:
    """Вывод о согласованности пунктов анкеты."""
    findings: list[Finding] = []
    if not math.isfinite(alpha):
        return [(CAUTION, "Согласованность не вычислилась: проверьте пропуски в пунктах.")]

    if alpha >= 0.9:
        word = "очень высокая"
    elif alpha >= 0.8:
        word = "высокая"
    elif alpha >= 0.7:
        word = "приемлемая"
    elif alpha >= 0.6:
        word = "спорная"
    else:
        word = "низкая"

    findings.append(
        (
            CONCLUSION,
            f"Согласованность пунктов {word}: альфа Кронбаха = "
            f"{format_number(alpha, 3)} по {items} пунктам, полных ответов {n}. "
            + (
                "Пункты можно объединить в одну шкалу и считать по ней сумму или "
                "среднее."
                if alpha >= 0.7
                else "Объединять пункты в одну шкалу рано: они измеряют разное."
            ),
        )
    )

    if worst_item and worst_alpha is not None and math.isfinite(worst_alpha):
        if worst_alpha > alpha + 0.01:
            findings.append(
                (
                    NOTE,
                    f"После удаления пункта «{worst_item}» согласованность "
                    f"выросла бы до {format_number(worst_alpha, 3)}. Посмотрите "
                    "его формулировку: возможно, он про другое.",
                )
            )

    findings.append(
        (
            CAUTION,
            "Высокая альфа сама по себе не доказывает, что шкала одномерна: она "
            "растёт с числом пунктов. Для проверки структуры нужен факторный "
            "анализ.",
        )
    )
    return findings


def format_count(value: int) -> str:
    """Число случаев: разряды разделяются пробелом, дробной части нет."""
    return f"{int(value):,}".replace(",", " ")


def format_plain(value: float) -> str:
    """Число без дробной части, если она нулевая.

    «Возраст от 18 до 69» читается лучше, чем «от 18,00 до 69,00»: у целых
    показателей дробная часть ничего не значит, а глаз за неё цепляется.
    """
    if abs(value - round(value)) < 1e-9:
        return format_count(int(round(value)))
    return format_number(value)


def _categories_word(count: int) -> str:
    """Согласование слова «категория» с числом: «1 категория», «2 категории»."""
    if count % 10 == 1 and count % 100 != 11:
        return "категория"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "категории"
    return "категорий"


def _distribution_phrase(
    items: list[tuple[str, int]], n_valid: int, limit: int = 3
) -> str:
    """Распределение одной переменной одной фразой: «113 «Женский» (56,5 %)»."""
    filled = [(label, count) for label, count in items if count]
    if not filled or n_valid <= 0:
        return ""
    filled.sort(key=lambda item: item[1], reverse=True)
    listed = ", ".join(
        f"{format_count(count)} «{label}» "
        f"({format_number(count / n_valid * 100, 1)} %)"
        for label, count in filled[:limit]
    )
    if len(filled) > limit:
        rest = len(filled) - limit
        listed += f" и ещё {rest} {_categories_word(rest)}"
    return listed


def describe_categories(
    *,
    name: str,
    items: list[tuple[str, int]],
    n_valid: int,
    n_missing: int = 0,
    limit: int = 5,
) -> list[Finding]:
    """Вывод по таблице частот: что за распределение у одной переменной.

    items - пары «подпись категории, частота». Пустые категории не выводятся:
    «0 человек» в человеческой фразе только мешает.
    """
    listed = _distribution_phrase(items, n_valid, limit=limit)
    if not listed:
        return []
    findings: list[Finding] = [(CONCLUSION, f"«{name}»: {listed}.")]

    filled = sorted(
        [(label, count) for label, count in items if count],
        key=lambda item: item[1],
        reverse=True,
    )
    # Одна категория почти на всю выборку - переменная не различает случаи, и об
    # этом надо сказать: иначе такие переменные тащат в корреляции и сравнения.
    share = filled[0][1] / n_valid
    if share >= 0.9:
        findings.append(
            (
                CAUTION,
                f"Почти все ответы — «{filled[0][0]}» "
                f"({format_number(share * 100, 1)} %). Такая переменная почти не "
                "различает случаи: в сравнениях групп и корреляциях она ничего "
                "не покажет.",
            )
        )

    if n_missing:
        share_missing = n_missing / (n_valid + n_missing)
        if share_missing >= 0.3:
            findings.append(
                (
                    CAUTION,
                    f"Не заполнено у {format_count(n_missing)} случаев "
                    f"({format_number(share_missing * 100, 1)} %). Больше трети "
                    "ответов отсутствует: выводы по этой переменной ненадёжны.",
                )
            )
    return findings


def describe_sample(
    *,
    n_cases: int,
    scales: list[tuple[str, float, float, float | None, float | None, int]],
    categories: list[tuple[str, list[tuple[str, int]], int]] | None = None,
    code_variables: list[str] | None = None,
    missing: list[tuple[str, int]] | None = None,
) -> list[Finding]:
    """Вывод по описательным статистикам: что это за данные и что в них есть.

    scales - «название, среднее, стд. отклонение, минимум, максимум, случаев» для
    количественных показателей. categories - «название, список «ответ, частота»,
    число ответивших» для категориальных и порядковых. code_variables - названия
    НОМИНАЛЬНЫХ переменных, у которых значения являются кодами.

    Разделение обязательно, а не косметика: у номинальной переменной значения -
    это коды ответов, и среднее по ним не значит ничего. «Пол — в среднем 1,56»
    звучит как факт, хотя это бессмыслица, и сказанная словами она опаснее
    таблицы: таблицу человек хотя бы не станет читать как вывод.

    Порядковые переменные в этот список не попадают: у них порядок категорий
    осмыслен, и среднее по баллам считается (в исследованиях так и делают). Но и
    для них распределение ответов информативнее среднего, поэтому оно и
    показывается.
    """
    findings: list[Finding] = []
    categories = categories or []
    code_variables = code_variables or []

    if not scales and not categories:
        return [(NOTE, "Описывать нечего: переменные не выбраны.")]

    # --- количественные показатели
    if scales:
        listed: list[str] = []
        for name, mean, _std, low, high, n in scales[:4]:
            piece = f"«{name}» — в среднем {format_number(mean)}"
            if low is not None and high is not None:
                piece += f" (от {format_plain(low)} до {format_plain(high)})"
            piece += f", случаев {format_count(n)}"
            listed.append(piece)
        sentence = (
            f"В наборе {format_count(n_cases)} случаев. Числовые показатели: "
            + "; ".join(listed)
            + "."
        )
        if len(scales) > 4:
            sentence += f" Всего числовых переменных: {len(scales)}."
    else:
        sentence = f"В наборе {format_count(n_cases)} случаев."
    findings.append((CONCLUSION, sentence))

    # --- категориальные и порядковые: распределение ответов, а не среднее
    if categories:
        listed_categories: list[str] = []
        for name, items, n_valid in categories[:4]:
            phrase = _distribution_phrase(items, n_valid, limit=3)
            if phrase:
                listed_categories.append(f"«{name}» — {phrase}")
        if listed_categories:
            tail = (
                f" Всего таких переменных: {len(categories)}."
                if len(categories) > 4
                else ""
            )
            findings.append(
                (
                    CONCLUSION,
                    "Ответы распределились так: "
                    + "; ".join(listed_categories)
                    + "."
                    + tail,
                )
            )

    if code_variables:
        names = "», «".join(code_variables[:4])
        findings.append(
            (
                CAUTION,
                f"Для переменных «{names}» среднее значение не приводится: их "
                "значения — коды ответов (1, 2, 3…), а не числа. Складывать и "
                "усреднять коды нельзя — смотрите распределение ответов ниже.",
            )
        )
    elif categories:
        findings.append(
            (
                NOTE,
                "Для переменных с готовыми вариантами ответа показано "
                "распределение: у порядка категорий среднее зависит от того, как "
                "они пронумерованы.",
            )
        )

    if missing:
        total = sum(count for _name, count in missing)
        if total:
            worst = sorted(missing, key=lambda item: item[1], reverse=True)[:2]
            listed_missing = ", ".join(
                f"«{name}» — {format_count(count)}" for name, count in worst if count
            )
            findings.append(
                (
                    CAUTION,
                    f"Незаполненных ответов: {format_count(total)}"
                    + (f" ({listed_missing})" if listed_missing else "")
                    + ". Они не участвуют в расчёте средних, поэтому по разным "
                    "показателям число случаев различается. Если пропусков много, "
                    "средние по этим переменным ненадёжны.",
                )
            )
    return findings


def describe_scale(
    *, name: str, n: int, mean: float, std: float, minimum: float, maximum: float
) -> list[Finding]:
    """Короткий вывод об одной количественной переменной."""
    return [
        (
            NOTE,
            f"«{name}»: в среднем {format_number(mean)}, разброс "
            f"{format_number(std)}, значения от {format_number(minimum)} до "
            f"{format_number(maximum)}, случаев {n}.",
        )
    ]


__all__ = [
    "CAUTION",
    "CONCLUSION",
    "NOTE",
    "association",
    "compare_several_groups",
    "compare_two_groups",
    "correlation",
    "describe_categories",
    "describe_sample",
    "describe_scale",
    "effect_word",
    "eta_word",
    "factor_structure",
    "format_count",
    "format_number",
    "format_p",
    "format_plain",
    "linear_model",
    "logistic_model",
    "normality_caution",
    "rank_difference",
    "reliability",
    "variance_caution",
]
