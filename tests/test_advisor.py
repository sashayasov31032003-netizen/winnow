"""Тесты советчика: подсказки должны быть верными и выполнимыми.

Советчик адресован человеку, который не может проверить его сам. Поэтому мало
того, что подсказка выглядит разумно: важно, чтобы числа в объяснении совпадали
с расчётом, чтобы предложенный сценарий действительно запускался и чтобы
бессмысленные сравнения (например, возрастных групп по возрасту) не предлагались
вовсе.
"""

from __future__ import annotations

import pytest

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats import engine
from winnow.stats.advisor import Scenario, _plural, suggest_scenarios


def _by_key(scenarios: list[Scenario], key: str) -> Scenario | None:
    for scenario in scenarios:
        if scenario.key == key:
            return scenario
    return None


def test_demo_dataset_gets_a_full_set_of_scenarios():
    """На демо-наборе должны найтись все основные виды исследований."""
    scenarios = suggest_scenarios(demo_dataset())
    keys = [scenario.key for scenario in scenarios]

    assert keys[0] == "describe", "описание выборки должно идти первым"
    assert "reliability" in keys
    assert "compare_two_groups" in keys
    assert "correlation" in keys
    assert "compare_groups" in keys
    assert "crosstabs" in keys


def test_demo_reliability_matches_reference_value():
    """Альфа Кронбаха для stress1..stress4 равна 0,846 - это проверенное значение."""
    scenario = _by_key(suggest_scenarios(demo_dataset()), "reliability")
    assert scenario is not None
    assert scenario.params["items"] == ["stress1", "stress2", "stress3", "stress4"]
    assert "0.846" in scenario.why


def test_demo_two_group_scenario_is_gender_by_anxiety():
    """Проверенное сравнение: тревожность по полу, p = 0,008, d = -0,38."""
    scenario = _by_key(suggest_scenarios(demo_dataset()), "compare_two_groups")
    assert scenario is not None
    assert scenario.roles == {"группа": "gender", "показатель": "anxiety"}
    assert scenario.params["test_vars"] == ["anxiety"]
    assert scenario.params["group_var"] == "gender"
    assert "0,008" in scenario.why
    assert scenario.is_confident


def test_demo_correlation_scenario_is_anxiety_with_life_satisfaction():
    """Проверенная связь: r = -0,341."""
    scenario = _by_key(suggest_scenarios(demo_dataset()), "correlation")
    assert scenario is not None
    assert set(scenario.roles.values()) == {"anxiety", "life_satisfaction"}
    assert "-0.341" in scenario.why


def test_every_suggested_scenario_actually_runs():
    """Подсказка бесполезна, если предложенный сценарий не запускается.

    Это же проверяет, что имена полей в сценарии совпадают с полями команд: если
    поле переименуют, тест это заметит сразу, а не пользователь.
    """
    dataset = demo_dataset()
    scenarios = suggest_scenarios(dataset)
    assert scenarios

    for scenario in scenarios:
        info = engine.REGISTRY_BY_KEY.get(scenario.procedure)
        assert info is not None, f"процедура не зарегистрирована: {scenario.procedure}"
        command = info.command_type(dataset=dataset, **scenario.params)
        result = engine.execute(command)
        assert result.tables, f"сценарий «{scenario.title}» ничего не посчитал"


def test_derived_grouping_is_not_offered_as_a_finding():
    """Возрастные группы, выведенные из возраста, сравнивать с возрастом нельзя.

    Такое сравнение всегда даёт огромную разницу, но не содержит знания. Новичок
    же примет его за результат и понесёт в работу.
    """
    ages = [18 + index for index in range(60)]
    dataset = Dataset.from_records(
        {
            "age": ages,
            # Группа выведена из самого показателя.
            "generation": [0 if age < 48 else 1 for age in ages],
            "anxiety": [40 + (index % 13) for index in range(60)],
        }
    )
    scenarios = suggest_scenarios(dataset)

    derived = [
        scenario
        for scenario in scenarios
        if scenario.key == "compare_two_groups"
        and scenario.roles.get("показатель") == "age"
        and scenario.roles.get("группа") == "generation"
    ]
    assert not derived, "тавтологичное сравнение не должно предлагаться"


def test_identifiers_are_never_used_in_scenarios():
    """Номер случая - не показатель: в подсказках он появляться не должен."""
    dataset = Dataset.from_records(
        {
            "respondent": list(range(1, 41)),
            "age": [20 + index % 20 for index in range(40)],
            "score": [float(index % 17) for index in range(40)],
            "gender": [1, 2] * 20,
        }
    )
    scenarios = suggest_scenarios(dataset)

    for scenario in scenarios:
        assert "respondent" not in scenario.variables()


def test_scenarios_explain_themselves():
    """У каждой подсказки должно быть объяснение: почему она предложена."""
    for scenario in suggest_scenarios(demo_dataset()):
        assert scenario.why.strip(), f"нет объяснения у «{scenario.title}»"
        assert scenario.question.strip(), f"нет вопроса у «{scenario.title}»"
        assert scenario.roles or scenario.key == "describe"


def test_empty_dataset_gives_no_scenarios():
    import pandas as pd

    profile_only = Dataset(frame=pd.DataFrame({"a": pd.Series(dtype="float64")}))
    assert suggest_scenarios(profile_only) == []


def test_plural_agrees_with_russian_numbers():
    """«1 пункт», «2 пункта», «5 пунктов» - и не «4 пунктов»."""
    assert _plural(1, "пункт", "пункта", "пунктов") == "1 пункт"
    assert _plural(2, "пункт", "пункта", "пунктов") == "2 пункта"
    assert _plural(4, "пункт", "пункта", "пунктов") == "4 пункта"
    assert _plural(5, "пункт", "пункта", "пунктов") == "5 пунктов"
    assert _plural(11, "пункт", "пункта", "пунктов") == "11 пунктов"
    assert _plural(21, "пункт", "пункта", "пунктов") == "21 пункт"
    assert _plural(22, "пункт", "пункта", "пунктов") == "22 пункта"


def test_scenario_limit_is_respected():
    scenarios = suggest_scenarios(demo_dataset(), limit=3)
    assert len(scenarios) == 3
    assert scenarios[0].key == "describe"


def test_advisor_does_not_change_metadata():
    """Подсказки только читают данные."""
    dataset = demo_dataset()
    before = {name: dataset.var(name).measure for name in dataset.names()}
    suggest_scenarios(dataset)
    after = {name: dataset.var(name).measure for name in dataset.names()}
    assert before == after
