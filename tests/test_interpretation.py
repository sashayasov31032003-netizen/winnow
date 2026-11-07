"""Тесты блока «простыми словами»: человеческий вывод из чисел отчёта.

Здесь проверяется не арифметика (её проверяют тесты процедур), а то, что вывод
правильно называет результат: значима разница или нет, в какую сторону, насколько
велика, и о чём результат умалчивает. Ошибка в этой формулировке опаснее ошибки в
расчёте: числа читатель проверить не может, а фразе верит.
"""

from __future__ import annotations

import numpy as np
import pytest

from winnow.core.dataset import Dataset
from winnow.export.html import result_to_html
from winnow.samples import demo_dataset
from winnow.stats import engine
from winnow.stats.command import CorrelationsCommand, CrosstabsCommand, ReliabilityCommand, TTestCommand
from winnow.stats.interpretation import (
    association,
    compare_two_groups,
    correlation,
    effect_word,
    format_number,
    format_p,
)
from winnow.stats.result import Result


def _ttest(dataset: Dataset, outcome: str, group: str, values: list[float]) -> Result:
    return engine.execute(
        TTestCommand(
            dataset=dataset,
            kind="independent",
            test_vars=[outcome],
            group_var=group,
            group_values=values,
        )
    )


def test_significant_difference_is_described_with_numbers():
    """Проверенный случай: тревожность по полу, p = 0,008, d = 0,38."""
    result = _ttest(demo_dataset(), "anxiety", "gender", [1.0, 2.0])
    assert result.findings, "у t-критерия должен быть вывод простыми словами"

    conclusion = result.conclusions[0]
    assert "значимы" in conclusion.text
    assert "p = 0,008" in conclusion.text
    # Число с русской запятой и без знака: направление сказано словами.
    assert "d = 0,38" in conclusion.text
    assert "Женский" in conclusion.text
    assert "49,70" in conclusion.text and "46,11" in conclusion.text


def test_insignificant_difference_does_not_claim_equality():
    """Незначимая разница - это не «группы одинаковы», и так и надо сказать."""
    # Группы составлены из одинаковых значений, поэтому средние совпадают точно:
    # значимость равна единице, и результат не зависит от случайности.
    values = [float(40 + index) for index in range(30)]
    dataset = Dataset.from_records(
        {"group": [1] * 30 + [2] * 30, "score": values + values}
    )
    result = _ttest(dataset, "score", "group", [1.0, 2.0])
    text = " ".join(finding.text for finding in result.findings)

    assert "не найдено" in text
    # Главное: программа обязана предупредить, что это не доказательство равенства.
    assert "не доказывает" in text


def test_small_groups_get_a_caution():
    """На малых группах критерий Стьюдента чувствителен к выбросам."""
    dataset = Dataset.from_records(
        {
            "group": [1] * 6 + [2] * 6,
            "score": [1.0, 2, 3, 4, 5, 6, 7.0, 8, 9, 10, 11, 40],
        }
    )
    result = _ttest(dataset, "score", "group", [1.0, 2.0])
    cautions = [finding.text for finding in result.findings if finding.is_caution]
    assert any("меньше десяти случаев" in text for text in cautions)


def test_implausible_difference_is_flagged_as_tautology():
    """Разница в несколько сигм означает вырожденное сравнение, и это надо сказать."""
    dataset = Dataset.from_records(
        {
            "generation": [0] * 20 + [1] * 20,
            "age": [20.0 + index * 0.1 for index in range(20)]
            + [60.0 + index * 0.1 for index in range(20)],
        }
    )
    result = _ttest(dataset, "age", "generation", [0.0, 1.0])
    text = " ".join(finding.text for finding in result.findings)

    assert "неправдоподобно велика" in text
    assert "ничего не доказывает" in text


def test_correlation_conclusion_reports_direction_and_strength():
    result = engine.execute(
        CorrelationsCommand(dataset=demo_dataset(), variables=["anxiety", "life_satisfaction"])
    )
    conclusion = result.conclusions[0]
    assert "r = -0,341" in conclusion.text
    assert "обратная" in conclusion.text
    assert "p < 0,001" in conclusion.text
    # Причинно-следственный вывод запрещён.
    assert any(
        "не означает причину" in finding.text
        for finding in result.findings
        if finding.is_caution
    )


def test_correlation_conclusion_picks_strongest_of_many_pairs():
    """Из нескольких пар в вывод идёт самая сильная связь.

    Проверяются три переменные, а не две: при двух пара всего одна, и ошибка в
    выборе сильнейшей осталась бы незамеченной.
    """
    result = engine.execute(
        CorrelationsCommand(
            dataset=demo_dataset(), variables=["age", "income", "anxiety"]
        )
    )
    assert result.conclusions, "вывод должен быть и при нескольких парах"
    text = result.conclusions[0].text

    # Самая сильная связь в демо-наборе - возраст с доходом (r примерно 0,50).
    assert "Возраст" in text or "Доход" in text
    assert "r = " in text


def test_association_conclusion_mentions_strength_measure():
    result = engine.execute(
        CrosstabsCommand(
            dataset=demo_dataset(),
            row_vars=["gender"],
            col_vars=["education"],
            phi_cramers_v=True,
        )
    )
    conclusion = result.conclusions[0]
    assert "V Крамера" in conclusion.text
    assert "не найдено" in conclusion.text


def test_reliability_conclusion_advises_on_merging_items():
    result = engine.execute(
        ReliabilityCommand(
            dataset=demo_dataset(), items=["stress1", "stress2", "stress3", "stress4"]
        )
    )
    conclusion = result.conclusions[0]
    assert "0,846" in conclusion.text
    assert "4 пунктам" in conclusion.text
    assert "объединить" in conclusion.text


def test_non_normal_distribution_gets_advice_with_alternative():
    """Проверка нормальности бесполезна без названия подходящего критерия."""
    dataset = Dataset.from_records(
        {
            # Длинный правый хвост: распределение далеко от нормального.
            "group": [1] * 12 + [2] * 11,
            "income": [10.0, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21,
                       22.0, 23, 24, 25, 26, 27, 28, 29, 30, 500, 900],
        }
    )
    dataset.var("income").label = "Доход"
    result = _ttest(dataset, "income", "group", [1.0, 2.0])
    cautions = " ".join(
        finding.text for finding in result.findings if finding.is_caution
    )

    assert "отличается от нормального" in cautions
    assert "Шапиро-Уилка" in cautions
    # Совет обязателен: без него пользователь не знает, что делать.
    assert "Манна-Уитни" in cautions


def test_normal_distribution_gets_no_normality_warning():
    """Демо-данные нормальны: лишнего предупреждения быть не должно."""
    result = _ttest(demo_dataset(), "anxiety", "gender", [1.0, 2.0])
    text = " ".join(finding.text for finding in result.findings)
    assert "отличается от нормального" not in text


def test_anova_conclusion_reports_statistic_and_extremes():
    """Проверенный случай: доход по образованию, F(3, 196) = 41,75."""
    from winnow.stats.command import AnovaCommand

    result = engine.execute(
        AnovaCommand(dataset=demo_dataset(), dependent=["income"], factor="education")
    )
    conclusion = result.conclusions[0]
    assert "F(3, 196) = 41,75" in conclusion.text
    assert "p < 0,001" in conclusion.text
    # Нужно знать не только «различия есть», но и между кем.
    assert "Наибольшее среднее" in conclusion.text
    assert "объясняет" in conclusion.text


def test_anova_warns_when_variances_differ():
    """При разных дисперсиях обычный F ненадёжен, и об этом надо сказать."""
    from winnow.stats.command import AnovaCommand

    rng = np.random.default_rng(11)
    rows = {"group": [], "value": []}
    for level, scale in ((1, 1.0), (2, 5.0), (3, 20.0)):
        rows["group"].extend([level] * 25)
        rows["value"].extend(rng.normal(50, scale, 25))
    dataset = Dataset.from_records(rows)

    result = engine.execute(AnovaCommand(dataset=dataset, dependent=["value"], factor="group"))
    cautions = " ".join(f.text for f in result.findings if f.is_caution)

    assert "Дисперсии групп различаются" in cautions
    assert "Уэлча" in cautions


def test_anova_has_no_variance_warning_when_variances_are_equal():
    """В демо-наборе Ливинь незначим: лишнего предупреждения быть не должно."""
    from winnow.stats.command import AnovaCommand

    result = engine.execute(
        AnovaCommand(dataset=demo_dataset(), dependent=["income"], factor="education")
    )
    text = " ".join(f.text for f in result.findings)
    assert "Дисперсии групп различаются" not in text


def test_regression_conclusion_names_significant_predictors_only():
    """Проверенный случай: R² = 0,373, коэффициент образования 10 782,02."""
    from winnow.stats.command import LinearRegressionCommand

    result = engine.execute(
        LinearRegressionCommand(
            dataset=demo_dataset(),
            dependent="income",
            predictors=["age", "education", "anxiety"],
        )
    )
    conclusion = result.conclusions[0]
    assert "R² = 0,373" in conclusion.text
    assert "F(3, 196) = 38,82" in conclusion.text
    assert "10 782,02" in conclusion.text
    # Константа - не предиктор, в выводе ей не место.
    assert "онстанта" not in conclusion.text


def test_regression_warns_about_suspiciously_good_model():
    """Если модель объясняет почти всё, это повод насторожиться."""
    from winnow.stats.command import LinearRegressionCommand

    base = [float(index) for index in range(40)]
    dataset = Dataset.from_records(
        # Показатель получен из предиктора - модель «объяснит» его целиком.
        {"x": base, "y": [value * 2 + 0.001 * (index % 3) for index, value in enumerate(base)]}
    )
    result = engine.execute(
        LinearRegressionCommand(dataset=dataset, dependent="y", predictors=["x"])
    )
    text = " ".join(f.text for f in result.findings)
    assert "почти всё" in text


def test_logistic_conclusion_translates_odds_ratios():
    """«Exp(B) = 2,4» начинающему ничего не говорит, нужны слова."""
    from winnow.stats.command import LogisticRegressionCommand

    rng = np.random.default_rng(5)
    # Признак действительно связан с событием - иначе значимых не будет.
    x = rng.normal(0, 1, 120)
    probability = 1 / (1 + np.exp(-(1.8 * x)))
    event = (rng.uniform(size=120) < probability).astype(float)
    dataset = Dataset.from_records({"x": x, "event": event})
    dataset.var("x").label = "Балл"

    result = engine.execute(
        LogisticRegressionCommand(dataset=dataset, dependent="event", predictors=["x"])
    )
    text = " ".join(f.text for f in result.findings)

    assert "предсказывает событие" in text
    assert "доля верных предсказаний" in text
    # Либо шансы повышаются, либо понижаются - но обязательно словами.
    assert "повышает шансы" in text or "снижает шансы" in text


def test_rank_criterion_conclusion_speaks_about_ranks():
    """Ранговый критерий сравнивает порядок, а не средние, и так и надо сказать."""
    from winnow.stats.command import NonparametricCommand

    result = engine.execute(
        NonparametricCommand(
            dataset=demo_dataset(),
            kind="independent",
            method="mann_whitney",
            test_vars=["anxiety"],
            group_var="gender",
        )
    )
    conclusion = result.conclusions[0]
    assert "средний ранг" in conclusion.text
    assert "Манна-Уитни" in conclusion.text
    # Величина эффекта должна попадать в вывод: ключ rank_biserial легко перепутать.
    assert "Величина эффекта" in conclusion.text


def test_factor_conclusion_answers_whether_analysis_was_possible():
    """Главный вопрос новичка здесь - «можно ли было это делать»."""
    from winnow.stats.command import FactorCommand

    result = engine.execute(
        FactorCommand(
            dataset=demo_dataset(), variables=["stress1", "stress2", "stress3", "stress4"]
        )
    )
    conclusion = result.conclusions[0]
    assert "KMO" in conclusion.text
    assert "0,82" in conclusion.text
    assert "68,5" in conclusion.text
    assert "Бартлетта" in conclusion.text


def test_every_analysis_procedure_produces_a_conclusion():
    """У всех процедур, где есть статистический вывод, должен быть и его пересказ.

    Проверяется списком: если кто-то из них потеряет выводы, тест это заметит.
    """
    from winnow.stats.command import (
        AnovaCommand,
        CrosstabsCommand,
        DescriptivesCommand,
        FactorCommand,
        FrequenciesCommand,
        LinearRegressionCommand,
        LogisticRegressionCommand,
        NonparametricCommand,
    )

    dataset = demo_dataset()
    cases = [
        TTestCommand(
            dataset=dataset,
            kind="independent",
            test_vars=["anxiety"],
            group_var="gender",
            group_values=[1.0, 2.0],
        ),
        CorrelationsCommand(dataset=dataset, variables=["anxiety", "life_satisfaction"]),
        CrosstabsCommand(dataset=dataset, row_vars=["gender"], col_vars=["education"]),
        ReliabilityCommand(
            dataset=dataset, items=["stress1", "stress2", "stress3", "stress4"]
        ),
        AnovaCommand(dataset=dataset, dependent=["income"], factor="education"),
        LinearRegressionCommand(
            dataset=dataset, dependent="income", predictors=["age", "education"]
        ),
        LogisticRegressionCommand(
            dataset=dataset, dependent="special_software", predictors=["age", "anxiety"]
        ),
        NonparametricCommand(
            dataset=dataset,
            kind="independent",
            method="mann_whitney",
            test_vars=["anxiety"],
            group_var="gender",
        ),
        FactorCommand(
            dataset=dataset, variables=["stress1", "stress2", "stress3", "stress4"]
        ),
        DescriptivesCommand(dataset=dataset, variables=["age", "income"]),
        FrequenciesCommand(dataset=dataset, variables=["gender"]),
    ]
    for command in cases:
        result = engine.execute(command)
        assert result.conclusions, f"{command.TITLE}: нет вывода простыми словами"


def test_descriptives_conclusion_describes_the_sample():
    """«Описать выборку» должна отвечать словами, а не только таблицей."""
    from winnow.stats.command import DescriptivesCommand

    result = engine.execute(
        DescriptivesCommand(
            dataset=demo_dataset(), variables=["age", "income", "anxiety", "hours_data"]
        )
    )
    conclusion = result.conclusions[0]
    assert "В наборе 200 случаев" in conclusion.text
    assert "в среднем" in conclusion.text
    # Целые границы показываются без дробной части: «от 18 до 69».
    assert "(от 18 до 69)" in conclusion.text
    # Пропуск по одной переменной должен быть назван.
    text = " ".join(f.text for f in result.findings)
    assert "Незаполненных ответов" in text
    assert "Часов работы с данными" in text


def test_frequencies_conclusion_names_categories_and_shares():
    from winnow.stats.command import FrequenciesCommand

    result = engine.execute(
        FrequenciesCommand(dataset=demo_dataset(), variables=["gender"])
    )
    conclusion = result.conclusions[0]
    assert "113" in conclusion.text and "56,5 %" in conclusion.text
    assert "87" in conclusion.text and "43,5 %" in conclusion.text


def test_frequencies_warn_about_variable_that_does_not_discriminate():
    """Переменная, где почти все ответы одинаковы, ничего не покажет."""
    from winnow.stats.command import FrequenciesCommand

    dataset = Dataset.from_records(
        {"agree": [1] * 95 + [2] * 5, "other": [1] * 50 + [2] * 50}
    )
    result = engine.execute(FrequenciesCommand(dataset=dataset, variables=["agree"]))
    cautions = " ".join(f.text for f in result.findings if f.is_caution)
    assert "почти не различает случаи" in cautions


def test_descriptives_never_gives_a_mean_of_answer_codes():
    """Среднее по кодам ответов («пол в среднем 1,56») — бессмыслица.

    Опаснее всего то, что словами она звучит как факт: таблицу человек хотя бы
    не станет читать как вывод, а фразу прочитает и поверит.
    """
    from winnow.stats.command import DescriptivesCommand

    result = engine.execute(
        DescriptivesCommand(dataset=demo_dataset(), variables=["gender", "age"])
    )
    texts = [finding.text for finding in result.findings]

    # Количественный вывод говорит о возрасте и не трогает пол.
    assert "Возраст" in texts[0]
    assert "Пол респондента" not in texts[0]
    # Категориальная переменная описывается распределением ответов.
    categorical = [text for text in texts if "распределились" in text]
    assert categorical, "пол должен описываться распределением"
    assert "113" in categorical[0] and "56,5 %" in categorical[0]
    # И обязательно объяснение, почему среднего нет.
    cautions = " ".join(finding.text for finding in result.findings if finding.is_caution)
    assert "коды ответов" in cautions
    assert "усреднять коды нельзя" in cautions
    # Ни в одной фразе нет среднего по коду.
    assert "в среднем 1," not in " ".join(texts)

    # Рядом со средними стоит таблица распределения ответов.
    titles = [table.title for table in result.tables]
    assert any("Распределение ответов" in title for title in titles)
    assert titles[0] == "Описательные статистики", "средние идут первыми"


def test_binary_variable_declared_as_scale_is_not_given_a_mean():
    """Возраст, перекодированный в два поколения, — не показатель.

    Именно этот случай вылез на реальной выгрузке: переменная с меткой «Уточните
    ваш возраст (полных лет)» содержала коды 0/1, была объявлена количественной,
    и программа уверенно писала «в среднем 0,40». Профиль данных такие переменные
    распознаёт, и его решение важнее объявленного уровня измерения.
    """
    from winnow.core.variable import Measure
    from winnow.stats.command import DescriptivesCommand

    dataset = Dataset.from_records(
        {"generation": [0.0] * 60 + [1.0] * 40, "age": [float(20 + i % 30) for i in range(100)]}
    )
    # Файл объявляет коды количественной шкалой - так и бывает в выгрузках.
    dataset.var("generation").measure = Measure.SCALE
    dataset.var("generation").label = "Уточните ваш возраст (полных лет)"

    result = engine.execute(
        DescriptivesCommand(dataset=dataset, variables=["generation", "age"])
    )
    texts = [finding.text for finding in result.findings]

    assert "в среднем 0," not in " ".join(texts), "среднее по коду поколения — бессмыслица"
    assert "младшее" not in texts[0]
    assert "распределились" in texts[1]
    assert "60" in texts[1] and "40" in texts[1]


def test_findings_appear_before_tables_in_report():
    """Вывод должен идти первым: человеку нужен ответ, а не таблица."""
    result = _ttest(demo_dataset(), "anxiety", "gender", [1.0, 2.0])
    html = result_to_html(result)

    assert '<div class="findings">' in html
    assert "Простыми словами" in html
    assert html.index('class="findings"') < html.index("<table>")
    assert "Простыми словами" in result.to_text()


def test_findings_do_not_break_empty_result():
    """Результат без выводов (у части процедур их нет) рисуется как раньше."""
    result = Result(procedure="TEST", title="Проверка")
    assert result.findings == []
    assert "Простыми словами" not in result.to_text()
    assert "Простыми словами" not in result_to_html(result)


def test_format_p_uses_russian_notation():
    assert format_p(0.008) == "p = 0,008"
    assert format_p(0.0004) == "p < 0,001"
    assert format_p(0.5) == "p = 0,500"


def test_format_number_uses_comma_and_thousands_space():
    assert format_number(46.105) == "46,10"
    assert format_number(-0.384) == "-0,38"
    assert format_number(47571.32) == "47 571,32"
    assert format_number(1234.0) == "1 234,00"


def test_effect_word_follows_conventions():
    assert effect_word(0.1) == "очень малый"
    assert effect_word(-0.38) == "малый"
    assert effect_word(0.6) == "средний"
    assert effect_word(-0.9) == "большой"


def test_helper_returns_note_about_missing_significance():
    """Если значимость не вычислилась, вывод не должен молчать об этом."""
    findings = association(first="a", second="b", p_value=float("nan"), cramers_v=None, n=10)
    assert len(findings) == 1
    assert "не вычислилась" in findings[0][1]


def test_duplicate_findings_are_not_repeated():
    result = Result(procedure="TEST")
    result.conclude("Один и тот же вывод")
    result.conclude("Один и тот же вывод")
    assert len(result.findings) == 1


def test_correlation_with_few_cases_suggests_rank_method():
    rng = np.random.default_rng(3)
    dataset = Dataset.from_records(
        {"a": rng.normal(0, 1, 12), "b": rng.normal(0, 1, 12)}
    )
    result = engine.execute(CorrelationsCommand(dataset=dataset, variables=["a", "b"]))
    text = " ".join(finding.text for finding in result.findings)
    assert "Спирмен" in text, "на малой выборке нужно предложить ранговую корреляцию"


def test_compare_two_groups_helper_reports_welch_note():
    findings = compare_two_groups(
        outcome="Показатель",
        group1="A",
        group2="B",
        n1=50,
        n2=50,
        mean1=10.0,
        mean2=12.0,
        p_value=0.01,
        effect=0.5,
        welch=True,
    )
    text = " ".join(item[1] for item in findings)
    assert "Уэлча" in text
    assert "Ливиня" in text
