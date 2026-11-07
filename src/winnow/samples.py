"""Демонстрационный набор данных.

Нужен не для красоты: пока нет своих данных, пользователь не может оценить
программу. Демо-набор должен сразу показывать всю ценность модели данных -
метки переменных, метки значений, шкалы измерения, пропущенные коды, - поэтому
он собран вручную, а не сгенерирован "просто случайными числами".
"""

from __future__ import annotations

import numpy as np

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure, MissingSpec

GENDERS = ["Мужской", "Женский"]
EDUCATIONS = ["Среднее", "Среднее специальное", "Высшее", "Учёная степень"]
CITIES = ["Москва", "Санкт-Петербург", "Другой город"]
EMPLOYMENT = ["Работает", "Учится", "Не работает"]

_GENDER_LABELS = {1: GENDERS[0], 2: GENDERS[1]}
_EDUCATION_LABELS = {1: EDUCATIONS[0], 2: EDUCATIONS[1], 3: EDUCATIONS[2], 4: EDUCATIONS[3]}
_CITY_LABELS = {1: CITIES[0], 2: CITIES[1], 3: CITIES[2]}
_EMPLOYMENT_LABELS = {1: EMPLOYMENT[0], 2: EMPLOYMENT[1], 3: EMPLOYMENT[2]}
_YES_NO_LABELS = {0: "Нет", 1: "Да"}


def demo_dataset(n: int = 200, seed: int = 20240517) -> Dataset:
    """Создаёт воспроизводимый демонстрационный набор (опросник).

    Seed фиксирован: два запуска демо должны давать одинаковые числа, иначе
    пользователь решит, что программа считает нестабильно.
    """
    rng = np.random.default_rng(seed)

    gender = rng.integers(1, 3, n)                       # 1 - мужской, 2 - женский
    age = np.clip(rng.normal(38, 12, n), 18, 78).round(0)
    education = rng.choice([1, 2, 3, 4], n, p=[0.18, 0.30, 0.42, 0.10])
    city = rng.choice([1, 2, 3], n, p=[0.40, 0.20, 0.40])
    employment = rng.choice([1, 2, 3], n, p=[0.66, 0.20, 0.14])

    # Доход зависит от образования и города - так в демо появляется осмысленная
    # связь, которую можно найти процедурами.
    base_income = 30000 + 9000 * (education - 1) + 12000 * (city == 1) + 6000 * (city == 2)
    income = np.clip(base_income + rng.normal(0, 12000, n), 12000, None).round(-2)

    # Тревожность: 20-80 баллов, ниже у работающих.
    anxiety_base = 48 - 3 * (employment == 1) + np.where(gender == 2, 2.5, 0)
    anxiety = np.clip(anxiety_base + rng.normal(0, 9, n), 20, 80).round(1)

    # Часы работы с данными: есть системный код "нет ответа" (-1).
    hours = np.clip(rng.gamma(2.2, 3.1, n), 0, 45).round(1).astype(float)
    hours[rng.random(n) < 0.08] = -1.0

    life_satisfaction = np.clip(
        7.2 - (anxiety - 48) * 0.06 + rng.normal(0, 1.6, n), 1, 10
    ).round(1)
    uses_special_software = (rng.random(n) < 0.34).astype(int)

    # Шкала из четырёх пунктов: один скрытый конструкт плюс шум. Без такой шкалы
    # в демо нельзя показать ни надёжность, ни факторный анализ - а это те
    # процедуры, ради которых пакет и нужен в работах с опросниками.
    latent = rng.normal(0, 1, n)
    scale_items: dict[str, list[float]] = {}
    for index in range(1, 5):
        item = np.clip(3.0 + latent * 0.9 + rng.normal(0, 0.7, n), 1, 5).round(0)
        scale_items[f"stress{index}"] = item.tolist()

    dataset = Dataset.from_records(
        {
            "gender": gender.tolist(),
            "age": age.tolist(),
            "education": education.tolist(),
            "city": city.tolist(),
            "employment": employment.tolist(),
            "income": income.tolist(),
            "anxiety": anxiety.tolist(),
            "hours_data": hours.tolist(),
            "life_satisfaction": life_satisfaction.tolist(),
            "special_software": uses_special_software.tolist(),
            **scale_items,
        },
        name="Демо-опрос",
    )

    # Паспорта переменных: именно этот блок делает демо похожим на настоящие
    # данные из SPSS, а не на таблицу из Excel.
    meta = [
        ("gender", "Пол респондента", Measure.NOMINAL, _GENDER_LABELS),
        ("age", "Возраст, полных лет", Measure.SCALE, {}),
        ("education", "Уровень образования", Measure.ORDINAL, _EDUCATION_LABELS),
        ("city", "Город проживания", Measure.NOMINAL, _CITY_LABELS),
        ("employment", "Занятость", Measure.NOMINAL, _EMPLOYMENT_LABELS),
        ("income", "Доход в месяц, руб.", Measure.SCALE, {}),
        ("anxiety", "Тревожность (20-80 баллов)", Measure.SCALE, {}),
        ("hours_data", "Часов работы с данными в неделю", Measure.SCALE, {}),
        ("life_satisfaction", "Удовлетворённость жизнью (1-10)", Measure.SCALE, {}),
        ("special_software", "Использует специальное ПО", Measure.NOMINAL, _YES_NO_LABELS),
    ]
    for name, label, measure, labels in meta:
        variable = dataset.var(name)
        variable.label = label
        variable.measure = measure
        if labels:
            variable.value_labels = dict(labels)

    # Паспорта пунктов шкалы: порядковая шкала от 1 до 5 с метками ответов.
    for index in range(1, 5):
        name = f"stress{index}"
        variable = dataset.var(name)
        variable.label = f"Пункт шкалы стресса {index}"
        variable.measure = Measure.ORDINAL
        variable.decimals = 0
        variable.value_labels = {
            1: "Совсем не верно",
            2: "Скорее не верно",
            3: "Затрудняюсь",
            4: "Скорее верно",
            5: "Совершенно верно",
        }

    dataset.var("income").decimals = 0
    dataset.var("life_satisfaction").decimals = 1
    dataset.var("hours_data").decimals = 1
    dataset.var("hours_data").missing = MissingSpec(discrete={-1.0})
    return dataset


__all__ = ["demo_dataset"]
