"""Настройки, база данных и модели веб-приложения Winnow.

Здесь же подключается движок статистики: он лежит в ``src/winnow`` и не знает
про Qt, поэтому в вебе используется тот самый код, что и в настольной версии.
"""

from __future__ import annotations

import os
import sys
import pathlib
import sys
from datetime import datetime, timezone

# Движок подключается до всего остального: пакет winnow живёт в src, и без
# этого путь импорта зависит от того, как установлен проект.
_SRC = pathlib.Path(__file__).resolve().parents[2]  # .../src
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import (  # noqa: E402
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import (  # noqa: E402
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

#: Папка проекта (...\winnow): рядом с src лежит web с файлами приложения.
# В собранном виде (PyInstaller) код лежит во временной папке, и путь от __file__
# вёл бы внутрь неё: база и файлы наборов пропадали бы после закрытия программы.
# Поэтому рядом с exe создаётся папка web - так же, как у настольной версии.
if getattr(sys, "frozen", False):
    PROJECT_DIR = pathlib.Path(sys.executable).resolve().parent
else:
    PROJECT_DIR = pathlib.Path(__file__).resolve().parents[3]

WEB_DIR = PROJECT_DIR / "web"

#: Строка подключения. По умолчанию SQLite - так разработка не требует сервера
#: базы. На сервере достаточно задать WINNOW_DB_URL с PostgreSQL, код не меняется.
DATABASE_URL = os.environ.get("WINNOW_DB_URL", f"sqlite:///{WEB_DIR / 'winnow.db'}")

#: Секрет для подписи cookie сессии. На сервере обязан быть заменён.
SECRET = os.environ.get("WINNOW_SECRET", "dev-secret-please-change")

#: Куда складываются файлы наборов данных.
DATA_DIR = pathlib.Path(os.environ.get("WINNOW_DATA", WEB_DIR / "data"))

#: Сколько живёт сессия.
SESSION_DAYS = int(os.environ.get("WINNOW_SESSION_DAYS", "30"))

#: Регистрация по приглашению. Первый пользователь создаётся без приглашения -
#: иначе некому будет выдать первое приглашение.
INVITE_ONLY = os.environ.get("WINNOW_INVITE_ONLY", "1") != "0"

#: Ограничение размера загружаемого файла (байт).
MAX_UPLOAD = int(os.environ.get("WINNOW_MAX_UPLOAD", str(50 * 1024 * 1024)))

#: Сколько ответов на опрос принимается с одного адреса за час.
#: Защита от накрутки: без входа по ссылке ответить может кто угодно, и скрипт
#: иначе заполнит опрос за минуту. Счётчик живёт в памяти и нигде не хранится:
#: сам адрес - это персональные данные, хранить его незачем.
SURVEY_RATE_LIMIT = int(os.environ.get("WINNOW_SURVEY_RATE", "30"))

#: Имя cookie, по которой узнаётся «этот браузер уже отвечал».
#: В ней случайный номер, а не идентификатор человека: привязать ответ к
#: аккаунту по ней нельзя.
RESPONDENT_COOKIE = "winnow_respondent"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс моделей."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    datasets: Mapped[list["Dataset"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    surveys: Mapped[list["Survey"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Invite(Base):
    """Приглашение: одноразовый код для регистрации."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Dataset(Base):
    """Загруженный набор данных. Самой таблицы в базе нет.

    Таблица лежит файлом в собственном формате Winnow: он проверен на
    сохранении и повторном чтении, и так база не растёт на сотни мегабайт из-за
    данных, которые всё равно читаются в память целиком.
    """

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(500))
    n_cases: Mapped[int] = mapped_column(Integer, default=0)
    n_variables: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[User] = relationship(back_populates="datasets")


# --------------------------------------------------------------- опросы
#
# Ответы лежат в таблицах, а не в файле набора: опрос закрывается, а данные
# остаются и переживают перезапуск. Из этих строк этап 2 соберёт обычный набор
# Winnow, поэтому у вопроса и ответа те же роли, что у переменной и значения:
# тип вопроса задаёт уровень измерения, варианты - метки.


class Survey(Base):
    """Опрос: анкета, которую заполняют по ссылке без входа.

    ``slug`` - та самая случайная часть адреса ``/s/<slug>``. Он же защита:
    угадать чужой опрос перебором ссылок нельзя, а индекс уникальный.
    """

    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    #: draft - черновик (по ссылке не открывается), open - принимает ответы,
    #: closed - закрыт вручную или по дате.
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    #: Разрешить одному браузеру отвечать несколько раз. По умолчанию нет -
    #: как в Google Forms.
    allow_multiple: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: Дата автоматического закрытия. Пусто - опрос открыт, пока его не закроют.
    closes_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Набор, собранный из ответов (кнопка «Исследовать в Winnow»). Ссылка
    #: нужна, чтобы повторное нажатие пересобирало тот же набор, а не плодило
    #: копии: человек правит данные в «Данных», и терять эту связь нельзя.
    dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasets.id"), nullable=True
    )

    owner: Mapped[User] = relationship(back_populates="surveys")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="survey",
        cascade="all, delete-orphan",
        order_by="Question.position",
    )
    responses: Mapped[list["SurveyResponse"]] = relationship(
        back_populates="survey", cascade="all, delete-orphan"
    )


class Question(Base):
    """Вопрос опроса. ``options`` - JSON с тем, что нужно именно этому типу.

    single/multi: ``{"choices": [{"id": "1", "label": "Мужской"}, ...]}``
    number:       ``{"min": 14, "max": 100}``
    scale:        ``{"min": 1, "max": 5}``
    text:         ``{"max_length": 2000}``

    Идентификаторы вариантов короткие («1», «2»): ответ хранит именно их, и по
    ним этап 2 отличит вариант от варианта, не разбирая текст метки.
    """

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    #: single, multi, number, scale или text.
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String(500))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[dict] = mapped_column(JSON, default=dict)

    survey: Mapped[Survey] = relationship(back_populates="questions")


class SurveyResponse(Base):
    """Один заполненный опрос.

    Класс назван ``SurveyResponse``, а не ``Response``, чтобы не путаться с
    HTTP-ответом FastAPI: таблица при этом называется ``responses``, как в плане.
    """

    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: Случайный номер браузера из cookie. Не аккаунт и не адрес: по нему
    #: нельзя узнать, кто ответил, но можно не принимать второй ответ.
    respondent_token: Mapped[str] = mapped_column(String(64), index=True, default="")
    #: Запасное поле для будущих пометок (например, источник ссылки).
    meta: Mapped[dict] = mapped_column("meta", JSON, default=dict)

    survey: Mapped[Survey] = relationship(back_populates="responses")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="response", cascade="all, delete-orphan"
    )


class Answer(Base):
    """Ответ на один вопрос.

    Отдельная таблица, а не JSON внутри ответа: распределения считаются
    запросом к базе, а не разбором JSON в памяти.
    """

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("responses.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    value_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Номера выбранных вариантов: для single один, для multi несколько.
    option_ids: Mapped[list] = mapped_column(JSON, default=list)

    response: Mapped[SurveyResponse] = relationship(back_populates="answers")


def _engine_args(url: str) -> dict:
    if url.startswith("sqlite"):
        # SQLite по умолчанию привязан к потоку, а FastAPI выполняет запросы в
        # пуле потоков.
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


engine = create_engine(DATABASE_URL, **_engine_args(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _add_missing_columns() -> None:
    """Добавляет поля, которых нет в уже существующей базе.

    ``create_all`` создаёт только недостающие таблицы, но не колонки в готовых.
    Без этого база, сделанная прошлой версией, падала бы на новом поле с
    «no such column». Полноценные миграции (Alembic) появятся при публичном
    сервисе; здесь достаточно одной необязательной колонки, поэтому шаг
    намеренно узкий и явный, а не универсальный.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if not inspector.has_table("surveys"):
        return
    columns = {column["name"] for column in inspector.get_columns("surveys")}
    if "dataset_id" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE surveys ADD COLUMN dataset_id INTEGER"))


def init_db() -> None:
    """Создаёт папки и таблицы.

    Папка нужна ДО подключения к базе: SQLite не создаёт файл в
    несуществующем каталоге (в собранном виде это папка web рядом с exe).
    Таблицы создаются при старте: для диплома этого достаточно, при
    публичном сервисе понадобятся миграции (Alembic).
    """
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _add_missing_columns()


def get_db():
    """Зависимость FastAPI: сессия базы на один запрос."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = [
    "PROJECT_DIR",
    "WEB_DIR",
    "DATA_DIR",
    "DATABASE_URL",
    "INVITE_ONLY",
    "MAX_UPLOAD",
    "RESPONDENT_COOKIE",
    "SECRET",
    "SESSION_DAYS",
    "SURVEY_RATE_LIMIT",
    "Answer",
    "Base",
    "Dataset",
    "Invite",
    "Question",
    "SessionLocal",
    "Survey",
    "SurveyResponse",
    "User",
    "engine",
    "get_db",
    "init_db",
    "utcnow",
]
