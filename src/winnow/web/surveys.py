"""Опросы: структура анкеты, проверка ответов и защита от накрутки.

HTTP-слой живёт в api.py, а правила «какой вопрос допустим» и «какой ответ
принять» - здесь. Так их можно проверить тестами без браузера, а этап 2
(превращение опроса в набор) возьмёт те же типы и те же метки вариантов: у
вопроса и ответа те же роли, что у переменной и значения, и угадывать уровни
измерения по данным не придётся.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from winnow.web.core import (
    SURVEY_RATE_LIMIT,
    Question,
    Survey,
    SurveyResponse,
)

#: Типы вопросов. Набор намеренно короткий: каждый тип отображается в понятный
#: уровень измерения, а экзотика (сетка, ранжирование) появится, когда для неё
#: будет готов анализ.
SINGLE = "single"
MULTI = "multi"
NUMBER = "number"
SCALE = "scale"
TEXT = "text"

KINDS = (SINGLE, MULTI, NUMBER, SCALE, TEXT)

#: Подписи для интерфейса и сообщений: человек не должен видеть «single».
KIND_TITLES = {
    SINGLE: "Один вариант",
    MULTI: "Несколько вариантов",
    NUMBER: "Число",
    SCALE: "Шкала 1–5",
    TEXT: "Текст",
}

MAX_QUESTIONS = 100
MAX_CHOICES = 50
MAX_QUESTION_TEXT = 500
MAX_CHOICE_LABEL = 200
MAX_TEXT_ANSWER = 5000
DEFAULT_TEXT_LIMIT = 2000
DEFAULT_SCALE_MAX = 5

#: Статусы. draft не открывается по ссылке, open принимает ответы, closed нет.
DRAFT = "draft"
OPEN = "open"
CLOSED = "closed"

STATUS_TITLES = {
    DRAFT: "Черновик",
    OPEN: "Открыт",
    CLOSED: "Закрыт",
}


# ------------------------------------------------------------ варианты ответа


def _choices(question_options: dict) -> list[dict]:
    """Варианты вопроса в постоянном виде: список словарей с id и меткой."""
    raw = (question_options or {}).get("choices")
    if not isinstance(raw, list):
        return []
    return [
        {"id": str(item.get("id", "")), "label": str(item.get("label", ""))}
        for item in raw
        if isinstance(item, dict)
    ]


def _labels(question_options: dict) -> dict[str, str]:
    return {item["id"]: item["label"] for item in _choices(question_options)}


def question_choices(question: Question) -> list[dict]:
    """Варианты вопроса в постоянном виде: список словарей с id и меткой.

    Публичный вариант нужен сборке набора (survey_dataset.py): она строит по
    варианту переменную-отметку и берёт метку отсюда, а не из JSON напрямую.
    """
    return _choices(question.options or {})


def _number(value) -> float | None:
    """Приводит введённое к числу. Пустое значение - это «нет ограничения»."""
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"«{value}» — не число") from exc


def _options_for(kind: str, item: dict, number: int) -> dict:
    """Собирает options для хранения, проверяя то, что относится к типу."""
    if kind in (SINGLE, MULTI):
        raw = item.get("choices")
        if raw is None:
            raw = (item.get("options") or {}).get("choices")
        if not isinstance(raw, list):
            raise ValueError(f"Вопрос {number}: нужны варианты ответа")
        labels: list[str] = []
        for value in raw:
            if isinstance(value, dict):
                value = value.get("label", "")
            label = " ".join(str(value or "").split())
            if not label:
                continue
            if len(label) > MAX_CHOICE_LABEL:
                raise ValueError(
                    f"Вопрос {number}: вариант длиннее {MAX_CHOICE_LABEL} символов"
                )
            labels.append(label)
        if not labels:
            raise ValueError(f"Вопрос {number}: нужен хотя бы один вариант ответа")
        if len(labels) > MAX_CHOICES:
            raise ValueError(
                f"Вопрос {number}: вариантов больше {MAX_CHOICES}, это уже не анкета"
            )
        # Номера вариантов короткие и идут по порядку: ответ хранит их, и по ним
        # этап 2 отличит один вариант от другого, не разбирая текст метки.
        return {
            "choices": [
                {"id": str(index), "label": label}
                for index, label in enumerate(labels, start=1)
            ]
        }

    if kind == NUMBER:
        minimum = _number(item.get("min"))
        maximum = _number(item.get("max"))
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"Вопрос {number}: нижняя граница больше верхней")
        options: dict = {}
        if minimum is not None:
            options["min"] = minimum
        if maximum is not None:
            options["max"] = maximum
        unit = " ".join(str(item.get("unit") or "").split())[:20]
        if unit:
            options["unit"] = unit
        return options

    if kind == SCALE:
        minimum = _number(item.get("min"))
        maximum = _number(item.get("max"))
        minimum = 1.0 if minimum is None else minimum
        maximum = float(DEFAULT_SCALE_MAX) if maximum is None else maximum
        for label, value in (("нижняя", minimum), ("верхняя", maximum)):
            if not float(value).is_integer() or not 1 <= value <= 10:
                raise ValueError(
                    f"Вопрос {number}: {label} граница шкалы — целое число от 1 до 10"
                )
        if minimum >= maximum:
            raise ValueError(f"Вопрос {number}: шкала пустая, границы совпали")
        # Баллы шкалы - целые: в JSON и в интерфейсе это 1..5, а не 1.0..5.0.
        return {"min": int(minimum), "max": int(maximum)}

    # Текст: длину ограничиваем, чтобы база не росла от одной вставки.
    limit = _number(item.get("max_length"))
    length = DEFAULT_TEXT_LIMIT if limit is None else int(limit)
    if not 1 <= length <= MAX_TEXT_ANSWER:
        raise ValueError(
            f"Вопрос {number}: предел текста — от 1 до {MAX_TEXT_ANSWER} символов"
        )
    return {"max_length": length}


def parse_questions(raw) -> list[dict]:
    """Проверяет присланную структуру анкеты и приводит её к виду для базы.

    Ошибка - ValueError с текстом для человека: номер вопроса и что именно не
    так. Молча «починить» структуру нельзя, иначе человек увидит не то, что
    составлял.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Вопросы должны быть списком")
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"В одном опросе не больше {MAX_QUESTIONS} вопросов")

    result: list[dict] = []
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Вопрос {number}: неверный формат")
        kind = str(item.get("kind") or "").strip()
        if kind not in KINDS:
            raise ValueError(f"Вопрос {number}: неизвестный тип вопроса")
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            raise ValueError(f"Вопрос {number}: не заполнен текст вопроса")
        if len(text) > MAX_QUESTION_TEXT:
            raise ValueError(
                f"Вопрос {number}: текст длиннее {MAX_QUESTION_TEXT} символов"
            )
        result.append(
            {
                "position": number - 1,
                "kind": kind,
                "text": text,
                "required": bool(item.get("required")),
                "options": _options_for(kind, item, number),
            }
        )
    return result


# ------------------------------------------------------------------ ответы


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _answer_value(question: Question, item: dict | None) -> dict | None:
    """Проверяет ответ на один вопрос. None - ответа нет.

    Пустой ответ и «ответ не пришёл» здесь одно и то же: обязательность
    проверяется отдельно, по вопросу, а не по тому, прислали ли поле.
    """
    if not isinstance(item, dict):
        return None

    options = question.options or {}
    kind = question.kind

    if kind in (SINGLE, MULTI):
        labels = _labels(options)
        raw = item.get("option_ids")
        if raw is None:
            raw = item.get("value")
        if isinstance(raw, (str, int)):
            raw = [raw]
        if not isinstance(raw, list):
            raw = []
        chosen: list[str] = []
        for value in raw:
            key = str(value).strip()
            if not key:
                continue
            if key not in labels:
                raise ValueError(
                    f"Вопрос «{question.text}»: такого варианта ответа нет"
                )
            if key not in chosen:
                chosen.append(key)
        if not chosen:
            return None
        if kind == SINGLE and len(chosen) > 1:
            raise ValueError(
                f"Вопрос «{question.text}»: здесь можно выбрать только один вариант"
            )
        return {"option_ids": chosen}

    if kind in (NUMBER, SCALE):
        raw = item.get("value_number", item.get("value"))
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        try:
            number = float(str(raw).strip().replace(",", "."))
        except ValueError as exc:
            raise ValueError(
                f"Вопрос «{question.text}»: «{raw}» — не число"
            ) from exc
        minimum = options.get("min")
        maximum = options.get("max")
        if minimum is not None and number < minimum:
            raise ValueError(
                f"Вопрос «{question.text}»: значение меньше {_pretty(minimum)}"
            )
        if maximum is not None and number > maximum:
            raise ValueError(
                f"Вопрос «{question.text}»: значение больше {_pretty(maximum)}"
            )
        if kind == SCALE and not number.is_integer():
            raise ValueError(
                f"Вопрос «{question.text}»: на шкале нужен целый балл"
            )
        return {"value_number": number}

    # Текст
    raw = item.get("value_text", item.get("value"))
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    limit = int(options.get("max_length", DEFAULT_TEXT_LIMIT))
    if len(text) > limit:
        raise ValueError(
            f"Вопрос «{question.text}»: ответ длиннее {limit} символов"
        )
    return {"value_text": text}


def validate_submission(survey: Survey, raw_answers) -> list[dict]:
    """Проверяет присланные ответы и возвращает строки для таблицы answers.

    Возвращаются только непустые ответы: пропуск необязательного вопроса - это
    отсутствие строки, а не строка с пустотой.
    """
    questions = {question.id: question for question in survey.questions}
    submitted: dict[int, dict] = {}
    for item in raw_answers or []:
        question_id = _as_int(item.get("question_id")) if isinstance(item, dict) else None
        if question_id is None:
            continue
        if question_id not in questions:
            # Опрос могли поправить, пока человек заполнял: лучше попросить
            # обновить страницу, чем записать ответ на чужой вопрос.
            raise ValueError(
                "Ответ пришёл на вопрос, которого нет в опросе. "
                "Обновите страницу и заполните анкету заново."
            )
        submitted[question_id] = item

    saved: list[dict] = []
    for question in survey.questions:
        value = _answer_value(question, submitted.get(question.id))
        if value is None:
            if question.required:
                raise ValueError(
                    f"Вопрос «{question.text}»: обязательный вопрос без ответа"
                )
            continue
        saved.append(
            {
                "question_id": question.id,
                "value_text": value.get("value_text"),
                "value_number": value.get("value_number"),
                "option_ids": value.get("option_ids", []),
            }
        )
    return saved


def _pretty(number: float) -> str:
    """Число для сообщения: 5, а не 5.0."""
    return str(int(number)) if float(number).is_integer() else str(number)


def answer_display(question: Question, answer) -> str:
    """Ответ так, как его прочитает человек: метки вариантов, а не номера."""
    if answer is None:
        return ""
    if question.kind in (SINGLE, MULTI):
        labels = _labels(question.options or {})
        return ", ".join(
            labels.get(str(option), str(option)) for option in (answer.option_ids or [])
        )
    if question.kind in (NUMBER, SCALE):
        if answer.value_number is None:
            return ""
        return _pretty(answer.value_number)
    return answer.value_text or ""


# ------------------------------------------------------------ представление


def effective_status(survey: Survey) -> str:
    """Статус с учётом даты закрытия: просроченный опрос уже не принимает.

    Статус в базе при этом не переписывается: дата - это правило, а не
    действие человека, и «закрыт» в списке должен означать именно закрытие.
    """
    if survey.status == CLOSED:
        return CLOSED
    closes_at = survey.closes_at
    if closes_at is not None and _aware(closes_at) <= datetime.now(timezone.utc):
        return CLOSED
    return survey.status


def _aware(value: datetime) -> datetime:
    """В SQLite время приходит без часового пояса, а сравнивать нужно с UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    """Время в ISO с часовым поясом: браузер иначе примет UTC за местное."""
    if value is None:
        return None
    return _aware(value).isoformat()


def closes_at_iso(survey: Survey) -> str | None:
    return iso_utc(survey.closes_at)


def question_payload(question: Question) -> dict:
    """Вопрос для конструктора и для формы: одно описание на два экрана."""
    options = question.options or {}
    return {
        "id": question.id,
        "position": question.position,
        "kind": question.kind,
        "kind_title": KIND_TITLES.get(question.kind, question.kind),
        "text": question.text,
        "required": bool(question.required),
        "choices": _choices(options),
        "min": options.get("min"),
        "max": options.get("max"),
        "unit": options.get("unit", ""),
        "max_length": options.get("max_length"),
    }


def survey_summary_payload(survey: Survey, n_responses: int = 0) -> dict:
    return {
        "id": survey.id,
        "title": survey.title,
        "status": effective_status(survey),
        "stored_status": survey.status,
        "slug": survey.slug,
        "allow_multiple": bool(survey.allow_multiple),
        "n_questions": len(survey.questions),
        "n_responses": n_responses,
        "created_at": iso_utc(survey.created_at),
        "closes_at": closes_at_iso(survey),
    }


def survey_detail_payload(survey: Survey, n_responses: int = 0) -> dict:
    return {
        **survey_summary_payload(survey, n_responses),
        "description": survey.description,
        "questions": [question_payload(question) for question in survey.questions],
        "can_edit": n_responses == 0,
    }


def public_survey_payload(survey: Survey) -> dict:
    """Опрос глазами респондента: без служебных полей вроде владельца."""
    status = effective_status(survey)
    return {
        "title": survey.title,
        "description": survey.description,
        "slug": survey.slug,
        "status": status,
        "allow_multiple": bool(survey.allow_multiple),
        # Закрытый опрос вопросов не отдаёт: заполнять всё равно нечего.
        "questions": (
            [question_payload(question) for question in survey.questions]
            if status == OPEN
            else []
        ),
    }


def response_payload(survey: Survey, response: SurveyResponse) -> dict:
    """Один ответ в виде «вопрос → что человек выбрал»."""
    questions = {question.id: question for question in survey.questions}
    answers = {answer.question_id: answer for answer in response.answers}
    items = []
    for question in survey.questions:
        answer = answers.get(question.id)
        if answer is None:
            continue
        items.append(
            {
                "question_id": question.id,
                "question": question.text,
                "kind": question.kind,
                "value": answer_display(question, answer),
            }
        )
    return {
        "id": response.id,
        "submitted_at": iso_utc(response.submitted_at),
        "answers": items,
    }


# ------------------------------------------------------------------ защита


class RateLimiter:
    """Скользящее окно: не больше ``limit`` действий с одного ключа за окно.

    Живёт в памяти процесса. Для одного сервера этого достаточно; при
    нескольких процессах понадобится общий счётчик (Redis), иначе лимит
    умножится на число процессов.
    """

    def __init__(self, limit: int, seconds: float = 3600.0):
        self.limit = max(1, int(limit))
        self.seconds = float(seconds)
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """True - действие можно выполнить; False - лимит исчерпан."""
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] > self.seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            # Пустые ключи не копятся: счётчик за час без обращений исчезает.
            if len(self._events) > 5000:
                for stale in [k for k, v in self._events.items() if not v]:
                    self._events.pop(stale, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


#: Ограничение частоты ответов: ключ - адрес клиента и адрес опроса.
SUBMIT_LIMITER = RateLimiter(SURVEY_RATE_LIMIT)


def new_slug(db: Session) -> str:
    """Случайный адрес опроса. Уникальный: по нему опрос и находят.

    8 случайных байт - это 11 символов. Перебрать такие адреса, чтобы найти
    чужой опрос, нереально, а человеку ссылку не нужно набирать руками.
    """
    for _ in range(10):
        slug = secrets.token_urlsafe(8)
        if db.scalar(select(Survey.id).where(Survey.slug == slug)) is None:
            return slug
    raise RuntimeError("Не удалось подобрать свободный адрес опроса")


def new_respondent_token() -> str:
    """Номер браузера для cookie. Случайный: ни к человеку, ни к аккаунту
    отношения не имеет."""
    return secrets.token_urlsafe(24)


__all__ = [
    "CLOSED",
    "DRAFT",
    "KINDS",
    "KIND_TITLES",
    "MAX_TEXT_ANSWER",
    "MULTI",
    "NUMBER",
    "OPEN",
    "RateLimiter",
    "SCALE",
    "SINGLE",
    "STATUS_TITLES",
    "SUBMIT_LIMITER",
    "TEXT",
    "answer_display",
    "closes_at_iso",
    "effective_status",
    "iso_utc",
    "new_respondent_token",
    "new_slug",
    "parse_questions",
    "public_survey_payload",
    "question_choices",
    "question_payload",
    "response_payload",
    "survey_detail_payload",
    "survey_summary_payload",
    "validate_submission",
]
