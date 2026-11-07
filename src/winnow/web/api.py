"""HTTP-интерфейс приложения.

Только приём запроса, проверка прав и формирование ответа. Вся работа с данными
и статистикой - в движке и в storage.py, поэтому этот файл читается как оглавление
того, что сервис умеет.
"""

from __future__ import annotations

import ipaddress
import os
import pathlib
import secrets
import socket
import tempfile
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from winnow.data.io.csv_io import write_csv
from winnow.data.io.excel import write_excel
from winnow.data.io.sav_writer import write_sav
from winnow.analysis.quality import quality_report
from winnow.export import report_to_html, result_to_docx, result_to_xlsx
from winnow.stats.charts import CHART_TYPES, build_chart_data, chart_caption
from winnow.stats.multianswer import detect_multi_answer, format_report, split_all
from winnow.ui.procedure_specs import DIALOG_SPECS
from winnow.web import charts_svg
from winnow.stats.engine import REGISTRY_BY_KEY, execute
from winnow.web import storage, survey_dataset, surveys
from winnow.web.policy import ALLOWED_PROCEDURES
from winnow.web.core import (
    INVITE_ONLY,
    MAX_UPLOAD,
    RESPONDENT_COOKIE,
    SESSION_DAYS,
    Answer,
    Dataset,
    Invite,
    Question,
    Survey,
    SurveyResponse,
    User,
    get_db,
    utcnow,
)
from winnow.web.security import (
    COOKIE_NAME,
    current_user,
    hash_password,
    issue_token,
    verify_password,
)

router = APIRouter(prefix="/api")

#: Сколько ячеек можно изменить за один запрос.
MAX_EDITS_PER_REQUEST = 500

#: Ставить ли флаг secure у cookie. На сервере с HTTPS - да, локально - нет,
#: иначе браузер не сохранит cookie по http.
#: Отправлять cookie сессии только по HTTPS. Для локальной работы не нужно, при
#: доступе через туннель Cloudflare (адрес https://...) - обязательно: иначе
#: cookie уходит и по открытому http, если тот же сервер доступен локально.
#: Включается переменной окружения: set WINNOW_COOKIE_SECURE=1
COOKIE_SECURE = os.environ.get("WINNOW_COOKIE_SECURE", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    invite: str = Field(default="", max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str


class DatasetOut(BaseModel):
    id: int
    name: str
    original_filename: str
    n_cases: int
    n_variables: int
    ai_full_access: bool = False
    created_at: str


def _dataset_out(row: Dataset) -> DatasetOut:
    return DatasetOut(
        id=row.id,
        name=row.name,
        original_filename=row.original_filename,
        n_cases=row.n_cases,
        n_variables=row.n_variables,
        ai_full_access=bool(row.ai_full_access),
        created_at=row.created_at.isoformat(),
    )


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------- регистрация


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(
    payload: RegisterRequest, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="Такой адрес уже зарегистрирован")

    users = int(db.scalar(select(func.count(User.id))) or 0)
    invite: Invite | None = None
    if INVITE_ONLY and users > 0:
        # Регистрация по приглашению: без него публичный сервис заполнится
        # случайными людьми за сутки.
        if not payload.invite.strip():
            raise HTTPException(
                status_code=403,
                detail="Регистрация по приглашению: введите код",
            )
        invite = db.scalar(select(Invite).where(Invite.code == payload.invite.strip()))
        if invite is None:
            raise HTTPException(status_code=403, detail="Код приглашения не найден")
        if invite.used_by is not None:
            raise HTTPException(status_code=403, detail="Это приглашение уже использовано")

    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = User(email=email, password_hash=password_hash)
    db.add(user)
    db.flush()
    if invite is not None:
        invite.used_by = user.id
        invite.used_at = utcnow()
    db.commit()

    # Сразу входим: заставлять человека вводить пароль второй раз незачем.
    response.set_cookie(
        COOKIE_NAME,
        issue_token(user.id),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )
    return UserOut(id=user.id, email=user.email)


@router.post("/auth/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    # Одинаковый ответ для «нет такого» и «неверный пароль»: иначе по разнице
    # сообщений можно узнать, кто зарегистрирован.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный адрес или пароль")
    response.set_cookie(
        COOKIE_NAME,
        issue_token(user.id),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )
    return UserOut(id=user.id, email=user.email)


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email)


# ------------------------------------------------------------------- наборы


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[DatasetOut]:
    rows = db.scalars(
        select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc())
    ).all()
    return [_dataset_out(row) for row in rows]


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DatasetOut:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"Файл больше {MAX_UPLOAD // (1024 * 1024)} МБ",
        )
    try:
        path, dataset = storage.import_file(user.id, file.filename or "data.csv", data)
    except Exception as exc:
        # Ошибка разбора файла - это ответ пользователю, а не падение сервера.
        raise HTTPException(
            status_code=422,
            detail=f"Не удалось прочитать файл: {exc}",
        ) from exc

    row = Dataset(
        user_id=user.id,
        name=(file.filename or "данные").rsplit(".", 1)[0][:200],
        original_filename=(file.filename or "")[:255],
        path=str(path),
        n_cases=int(len(dataset.frame)),
        n_variables=len(dataset.names()),
    )
    db.add(row)
    db.commit()
    return _dataset_out(row)



def _load_stored(row) -> object:
    """Читает набор с диска, объясняя пропажу файла по-человечески.

    Файл может исчезнуть: его удалили, перенесли папку данных, восстановили базу
    из копии без файлов. Раньше это давало 500 и «Ошибка соединения» в браузере,
    хотя причина понятна и поправима.
    """
    try:
        return storage.load_dataset(row.path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Файл набора не найден на сервере — загрузите данные заново",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=422, detail=f"Не удалось прочитать файл набора: {exc}"
        ) from exc

def _owned(dataset_id: int, user: User, db: Session) -> Dataset:
    row = db.get(Dataset, dataset_id)
    # Чужой набор выглядит как несуществующий: иначе можно узнать, что он есть.
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Набор не найден")
    return row


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    return {
        **_dataset_out(row).model_dump(),
        "variables": storage.variables_payload(dataset),
    }


@router.get("/datasets/{dataset_id}/preview")
def get_preview(
    dataset_id: int,
    limit: int = storage.PREVIEW_ROWS,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _owned(dataset_id, user, db)
    limit = max(1, min(limit, 500))
    return storage.preview_payload(
        _load_stored(row), limit=limit, offset=offset
    )


@router.get("/datasets/{dataset_id}/scenarios")
def get_scenarios(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _owned(dataset_id, user, db)
    return storage.scenarios_payload(_load_stored(row))


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    row = _owned(dataset_id, user, db)
    path = row.path
    # Если набор собран из опроса, ссылка снимается: иначе опрос указывал бы на
    # удалённый набор, и кнопка «Исследовать в Winnow» падала бы с 500.
    db.execute(
        update(Survey).where(Survey.dataset_id == row.id).values(dataset_id=None)
    )
    db.delete(row)
    db.commit()
    try:
        import pathlib

        pathlib.Path(path).unlink(missing_ok=True)
    except OSError:
        # Файл мог исчезнуть - запись в базе уже удалена, это главное.
        pass
    return Response(status_code=204)


# ------------------------------------------------------------------- опросы
#
# Опросы живут в том же приложении, что и анализ: вход общий, а на этапе 2
# ответы превратятся в обычный набор без выгрузки и повторной загрузки файла.
# Публичная часть (ниже) не требует входа - иначе опрос не пройти.


class SurveyIn(BaseModel):
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    allow_multiple: bool = False
    #: Дата закрытия строкой ISO. Пусто - опрос открыт, пока его не закроют.
    closes_at: str | None = None
    #: Список вопросов: разбирает и проверяет surveys.parse_questions, чтобы
    #: сообщения об ошибках были на русском, а не языком валидатора.
    questions: list[dict] = Field(default_factory=list)


class StatusRequest(BaseModel):
    status: str


class SubmissionRequest(BaseModel):
    answers: list[dict] = Field(default_factory=list)


def _parse_closes_at(value: str | None) -> datetime | None:
    """Разбирает дату закрытия и приводит её к UTC.

    Время без часового пояса считается местным временем сервера: человек
    вводит его в форме «когда закрыть» и имеет в виду свои часы.
    """
    text = (value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Дата закрытия: нужен формат вроде 2026-01-31T18:00",
        ) from exc
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _clean_title(value: str) -> str:
    title = " ".join(value.split())
    if not title:
        raise HTTPException(status_code=422, detail="У опроса должно быть название")
    return title[:200]


def _clean_description(value: str) -> str:
    return value.strip()[:2000]


def _owned_survey(survey_id: int, user: User, db: Session) -> Survey:
    row = db.get(Survey, survey_id)
    # Чужой опрос выглядит как несуществующий - так же, как чужой набор.
    if row is None or row.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Опрос не найден")
    return row


def _response_counts(db: Session, user: User) -> dict[int, int]:
    """Сколько ответов у каждого опроса - одним запросом, без обхода в цикле."""
    rows = db.execute(
        select(SurveyResponse.survey_id, func.count(SurveyResponse.id))
        .join(Survey, Survey.id == SurveyResponse.survey_id)
        .where(Survey.owner_id == user.id)
        .group_by(SurveyResponse.survey_id)
    ).all()
    return {survey_id: int(count) for survey_id, count in rows}


def _n_responses(db: Session, survey_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(SurveyResponse.id)).where(
                SurveyResponse.survey_id == survey_id
            )
        )
        or 0
    )


def _save_questions(survey: Survey, raw: list[dict]) -> None:
    """Заменяет вопросы опроса целиком.

    Правка структуры разрешена только пока ответов нет: иначе старые ответы
    потеряли бы смысл (вариант исчез, вопрос стал другим). Это проверяет
    вызывающий код, здесь только сборка.
    """
    try:
        parsed = surveys.parse_questions(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    survey.questions.clear()
    for item in parsed:
        survey.questions.append(Question(**item))


@router.get("/surveys")
def list_surveys(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(Survey)
        .where(Survey.owner_id == user.id)
        .options(selectinload(Survey.questions))
        .order_by(Survey.created_at.desc())
    ).all()
    counts = _response_counts(db, user)
    return [
        surveys.survey_summary_payload(row, counts.get(row.id, 0)) for row in rows
    ]


@router.post("/surveys", status_code=201)
def create_survey(
    payload: SurveyIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Создаёт черновик. Вопросы можно прислать сразу или добавить потом."""
    survey = Survey(
        owner_id=user.id,
        title=_clean_title(payload.title),
        description=_clean_description(payload.description),
        allow_multiple=payload.allow_multiple,
        closes_at=_parse_closes_at(payload.closes_at),
        slug=surveys.new_slug(db),
        status=surveys.DRAFT,
    )
    db.add(survey)
    db.flush()
    _save_questions(survey, payload.questions)
    db.commit()
    return surveys.survey_detail_payload(survey, 0)


@router.get("/surveys/{survey_id}")
def get_survey(
    survey_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _owned_survey(survey_id, user, db)
    return surveys.survey_detail_payload(row, _n_responses(db, row.id))


@router.put("/surveys/{survey_id}")
def update_survey(
    survey_id: int,
    payload: SurveyIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Сохраняет конструктор: название, описание, настройки и вопросы."""
    row = _owned_survey(survey_id, user, db)
    answered = _n_responses(db, row.id)
    if answered:
        # Мягко, но твёрдо: ответы уже есть, и менять анкету под ними нельзя.
        raise HTTPException(
            status_code=409,
            detail=(
                "Опрос уже собрал ответы: структуру менять нельзя, иначе старые "
                "ответы потеряют смысл. Его можно только закрыть."
            ),
        )
    row.title = _clean_title(payload.title)
    row.description = _clean_description(payload.description)
    row.allow_multiple = payload.allow_multiple
    row.closes_at = _parse_closes_at(payload.closes_at)
    _save_questions(row, payload.questions)
    db.commit()
    return surveys.survey_detail_payload(row, answered)


@router.post("/surveys/{survey_id}/status")
def change_survey_status(
    survey_id: int,
    payload: StatusRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Публикация и закрытие опроса.

    Открыть можно только анкету с вопросами: пустая ссылка - это не опрос.
    Закрытый опрос открывается снова, если дата закрытия не прошла.
    """
    row = _owned_survey(survey_id, user, db)
    status = payload.status.strip().lower()
    if status not in (surveys.DRAFT, surveys.OPEN, surveys.CLOSED):
        raise HTTPException(status_code=422, detail="Статус: черновик, открыт или закрыт")
    if status == surveys.OPEN:
        if not row.questions:
            raise HTTPException(
                status_code=422,
                detail="Сначала добавьте хотя бы один вопрос: пустой опрос открывать нечего",
            )
        if row.closes_at is not None and surveys.effective_status(row) == surveys.CLOSED:
            raise HTTPException(
                status_code=422,
                detail="Дата закрытия уже прошла: поставьте другую дату или снимите её",
            )
    row.status = status
    db.commit()
    return surveys.survey_detail_payload(row, _n_responses(db, row.id))


@router.delete("/surveys/{survey_id}", status_code=204)
def delete_survey(
    survey_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Удаляет черновик или опрос без ответов.

    Опрос с ответами не удаляется: это чужие заполненные анкеты, и пропадать
    они не должны. Архив и мягкое удаление - этап 3.
    """
    row = _owned_survey(survey_id, user, db)
    if _n_responses(db, row.id):
        raise HTTPException(
            status_code=409,
            detail="У опроса есть ответы: удалять его нельзя. Закройте его - ответы сохранятся",
        )
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.get("/surveys/{survey_id}/responses")
def list_responses(
    survey_id: int,
    offset: int = 0,
    limit: int = 50,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Ответы как есть, без сводок и процентов: сводка - этап 3.

    Нужны, чтобы человек видел, что ответы действительно сохраняются, и чтобы
    проверить это можно было без просмотра базы.
    """
    row = _owned_survey(survey_id, user, db)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = _n_responses(db, row.id)
    rows = db.scalars(
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == row.id)
        .options(selectinload(SurveyResponse.answers))
        .order_by(SurveyResponse.submitted_at.desc(), SurveyResponse.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "responses": [surveys.response_payload(row, item) for item in rows],
    }


# --------------------------------------------------- опрос → набор данных
#
# Этап 2 плана: ответы превращаются в обычный набор Winnow. Данные не
# копируются вручную и не выгружаются в CSV: набор собирается из тех же строк
# базы, поэтому метки и уровни измерения известны точно, а не угадываются.


@router.post("/surveys/{survey_id}/dataset", status_code=201)
def build_survey_dataset(
    survey_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Собирает набор из ответов — кнопка «Исследовать в Winnow».

    Набор пересобирается при каждом нажатии: ответы приходят и после первого
    сбора. Запись и файл набора при этом остаются те же, поэтому в «Данных» не
    появляются копии «Опрос: …». Правки, сделанные в наборе вручную, при
    пересборке заменяются свежими ответами — так и должно быть, источник здесь
    опрос, а не файл.
    """
    row = _owned_survey(survey_id, user, db)
    total = _n_responses(db, row.id)
    if not total:
        raise HTTPException(
            status_code=422, detail="Ответов пока нет: набор собирать не из чего"
        )

    responses = db.scalars(
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == row.id)
        .options(selectinload(SurveyResponse.answers))
        .order_by(SurveyResponse.submitted_at, SurveyResponse.id)
    ).all()
    try:
        dataset = survey_dataset.build(row, list(responses))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    target = db.get(Dataset, row.dataset_id) if row.dataset_id else None
    if target is None or target.user_id != user.id:
        # Первая сборка (или набор удалили в «Данных»): заводится новый.
        target = Dataset(
            user_id=user.id,
            name=f"Опрос: {row.title}"[:200],
            original_filename=f"survey-{row.slug}.winnow",
            path=str(storage.user_dir(user.id) / f"{uuid.uuid4().hex}.winnow"),
            n_cases=0,
            n_variables=0,
        )
        db.add(target)
        db.flush()
        row.dataset_id = target.id
    target.name = f"Опрос: {row.title}"[:200]
    target.n_cases = dataset.n_cases
    target.n_variables = dataset.n_vars
    storage.save_dataset(dataset, target.path)
    db.commit()
    return {**_dataset_out(target).model_dump(), "survey_id": row.id}


# ---------------------------------------------------------- публичная форма
#
# Здесь входа нет намеренно: ссылку отправляют человеку, которому Winnow не
# нужен. Защита вместо входа - случайный slug, ограничение частоты и закрытие
# опроса.


def _public_survey(slug: str, db: Session) -> Survey:
    row = db.scalar(select(Survey).where(Survey.slug == slug))
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Опрос не найден: возможно, ссылка неверная или опрос удалён",
        )
    return row


def _set_respondent_cookie(response: Response, token: str) -> None:
    """Cookie «этот браузер уже отвечал».

    Год жизни: человек может вернуться к опросу позже. Значение - случайный
    номер, а не идентификатор: связать его с аккаунтом или адресом нельзя.
    """
    response.set_cookie(
        RESPONDENT_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=365 * 24 * 3600,
        path="/",
    )


@router.get("/public/surveys/{slug}")
def get_public_survey(
    slug: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Анкета для заполнения: без входа, только нужные поля."""
    row = _public_survey(slug, db)
    status = surveys.effective_status(row)
    if status == surveys.DRAFT:
        # Черновик не должен открываться по ссылке: его ещё не показывали людям.
        raise HTTPException(
            status_code=404, detail="Опрос не найден или ещё не опубликован"
        )
    token = request.cookies.get(RESPONDENT_COOKIE, "")
    answered = False
    if token and not row.allow_multiple:
        answered = (
            db.scalar(
                select(SurveyResponse.id).where(
                    SurveyResponse.survey_id == row.id,
                    SurveyResponse.respondent_token == token,
                )
            )
            is not None
        )
    return {**surveys.public_survey_payload(row), "already_answered": answered}


@router.post("/public/surveys/{slug}/responses", status_code=201)
def submit_response(
    slug: str,
    payload: SubmissionRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    """Принимает заполненную анкету и сохраняет её в базу.

    Порядок проверок: существует ли опрос, открыт ли, не слишком ли часто, не
    отвечал ли этот браузер, и только потом - правильность самих ответов.
    Дешёвые проверки идут первыми, чтобы накрутку не считали дорогим разбором.
    """
    row = _public_survey(slug, db)
    status = surveys.effective_status(row)
    if status == surveys.DRAFT:
        raise HTTPException(
            status_code=404, detail="Опрос не найден или ещё не опубликован"
        )
    if status == surveys.CLOSED:
        raise HTTPException(
            status_code=403, detail="Опрос закрыт: ответы больше не принимаются"
        )

    # Ключ - адрес клиента и адрес опроса. Сам адрес нигде не сохраняется:
    # счётчик живёт в памяти и нужен только на время окна.
    client = request.client.host if request.client else "unknown"
    if not surveys.SUBMIT_LIMITER.allow(f"{client}|{row.slug}"):
        raise HTTPException(
            status_code=429,
            detail="Слишком много ответов подряд. Подождите несколько минут и повторите",
        )

    token = request.cookies.get(RESPONDENT_COOKIE, "")
    if not token or len(token) > 64:
        token = surveys.new_respondent_token()
    if not row.allow_multiple:
        already = db.scalar(
            select(SurveyResponse.id).where(
                SurveyResponse.survey_id == row.id,
                SurveyResponse.respondent_token == token,
            )
        )
        if already is not None:
            raise HTTPException(
                status_code=409,
                detail="Вы уже отвечали на этот опрос. Спасибо!",
            )

    try:
        saved = surveys.validate_submission(row, payload.answers)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record = SurveyResponse(
        survey_id=row.id,
        respondent_token=token,
        meta={"source": "link"},
    )
    db.add(record)
    db.flush()
    for item in saved:
        db.add(Answer(response_id=record.id, **item))
    db.commit()

    _set_respondent_cookie(response, token)
    return {
        "id": record.id,
        "submitted_at": surveys.iso_utc(record.submitted_at),
        "status": "saved",
    }


# ------------------------------------------------------------- приглашения


@router.post("/invites", status_code=201)
def create_invite(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """Создаёт код приглашения. Пока это доступно любому вошедшему.

    Для публичного сервиса право выдавать приглашения должно быть только у
    администратора - это помечено в качестве следующего шага.
    """
    code = secrets.token_urlsafe(9)
    invite = Invite(code=code, note=f"выдал {user.email}")
    db.add(invite)
    db.commit()
    return {"code": code}


class QualityRequest(BaseModel):
    """Параметры проверки качества.

    Без target проверяются только данные; с target — ещё и линейная модель,
    поэтому predictors имеют смысл лишь вместе с зависимой переменной.
    """

    target: str | None = None
    predictors: list[str] = Field(default_factory=list)


@router.post("/datasets/{dataset_id}/quality")
def check_quality(
    dataset_id: int,
    payload: QualityRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Проверяет данные и, если задана цель, диагностику линейной модели.

    Ничего не меняет и не сохраняет: это отчёт, по которому человек решает,
    что делать с пропусками, выбросами и предикторами.
    """
    if len(payload.predictors) > 20:
        raise HTTPException(
            status_code=422, detail="Слишком много предикторов: максимум 20"
        )
    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    try:
        report = quality_report(
            dataset,
            target=payload.target or None,
            predictors=list(payload.predictors),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"report": report.as_payload()}


class RunRequest(BaseModel):
    procedure: str
    #: Готовые параметры команды - так работают сценарии советчика.
    params: dict = Field(default_factory=dict)
    #: Значения формы процедуры - так работает ручной выбор переменных.
    #: Команда собирается тем же описанием окна, что и в настольной версии.
    values: dict | None = None
    #: Переменная, по которой считается каждая группа отдельно.
    split_by: str | None = None
    #: Переменная весов: сколько случаев представляет каждая строка.
    weight: str | None = None
    #: Тема оформления отчёта: светлая или тёмная. Отчёт собирает движок,
    #: поэтому перекрашивать готовый HTML снаружи не нужно и вредно.
    theme: str = "light"


@router.post("/datasets/{dataset_id}/run")
def run_procedure(
    dataset_id: int,
    payload: RunRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Выполняет процедуру на наборе и возвращает готовый отчёт.

    Отчёт приходит в двух видах: готовый HTML (его и показывает интерфейс) и
    список выводов простыми словами - пригодится, когда понадобится собирать
    сводку из нескольких расчётов.
    """
    if payload.procedure not in ALLOWED_PROCEDURES:
        raise HTTPException(
            status_code=403,
            detail=f"Процедура «{payload.procedure}» через API не запускается",
        )
    info = REGISTRY_BY_KEY.get(payload.procedure)
    if info is None:
        raise HTTPException(status_code=404, detail="Процедура не найдена")

    row = _owned(dataset_id, user, db)
    dataset = _configure(_load_stored(row), payload)
    try:
        result = _execute_command(dataset, payload)
    except (ValueError, TypeError) as exc:
        # Неверные параметры - это ответ пользователю, а не падение сервера.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "procedure": result.procedure,
        "title": result.title,
        "html": report_to_html(
            [result], show_title=False, include_syntax=False, theme=payload.theme
        ),
        "conclusions": [
            {"kind": finding.kind, "text": finding.text} for finding in result.findings
        ],
        "n_tables": len(result.tables),
        "warnings": list(result.warnings),
    }


# ---------------------------------------------------------------- правка


class CellEdit(BaseModel):
    row: int
    column: str
    value: str | float | int | None = None


class EditRequest(BaseModel):
    edits: list[CellEdit]
    limit: int = storage.PREVIEW_ROWS
    offset: int = 0


@router.patch("/datasets/{dataset_id}/cells")
def edit_cells(
    dataset_id: int,
    payload: EditRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Правка отдельных ячеек таблицы.

    Принимаются только существующие переменные и существующие строки: иначе
    правка была бы способом записать в набор что угодно. Значение приводится к
    типу переменной, ошибка возвращается текстом с номером строки.
    """
    if not payload.edits:
        raise HTTPException(status_code=422, detail="Нет изменений")
    if len(payload.edits) > MAX_EDITS_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=f"За один раз можно изменить не больше {MAX_EDITS_PER_REQUEST} ячеек",
        )

    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    try:
        changed = storage.apply_edits(
            dataset, [edit.model_dump() for edit in payload.edits]
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    storage.save_dataset(dataset, row.path)
    preview = storage.preview_payload(
        dataset, limit=max(1, min(payload.limit, 500)), offset=max(0, payload.offset)
    )
    return {"changed": changed, **preview}


def _configure(dataset, payload: "RunRequest"):
    """Включает на наборе разбиение по группам и веса, если их просили.

    Ничего не сохраняется: настройка действует на текущий расчёт. Иначе однажды
    включённое разбиение незаметно меняло бы все последующие отчёты.
    """
    if payload.split_by:
        if payload.split_by not in dataset.names():
            raise HTTPException(
                status_code=422,
                detail=f"Переменной «{payload.split_by}» нет в наборе",
            )
        dataset.set_split(payload.split_by)
    if payload.weight:
        if payload.weight not in dataset.names():
            raise HTTPException(
                status_code=422, detail=f"Переменной весов «{payload.weight}» нет в наборе"
            )
        dataset.weight_var = payload.weight
    return dataset


def _execute_command(dataset, payload: "RunRequest"):
    """Собирает команду по запросу и выполняет её.

    Один разбор на два случая: готовые параметры сценария советчика или значения
    формы процедуры. Так и запуск, и выгрузка идут одним путём и не расходятся.
    """
    if payload.values is not None:
        spec = DIALOG_SPECS.get(payload.procedure)
        if spec is None:
            raise HTTPException(
                status_code=404,
                detail=f"У процедуры «{payload.procedure}» нет описания формы",
            )
        command = spec.build(payload.values, dataset)
    else:
        info = REGISTRY_BY_KEY[payload.procedure]
        command = info.command_type(dataset=dataset, **payload.params)
    command.validate()
    return execute(command)


class ExportRequest(RunRequest):
    format: str = "docx"


@router.post("/datasets/{dataset_id}/export")
def export_result(
    dataset_id: int,
    payload: ExportRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Отдаёт отчёт файлом: Word, Excel или HTML.

    Результат пересчитывается, а не хранится: наборы маленькие, расчёт занимает
    миллисекунды, зато не нужно держать на сервере кэш результатов и следить за
    его сроком жизни.
    """
    if payload.procedure not in ALLOWED_PROCEDURES:
        raise HTTPException(
            status_code=403,
            detail=f"Процедура «{payload.procedure}» через API не запускается",
        )
    fmt = payload.format.lower()
    if fmt not in ("docx", "xlsx", "html"):
        raise HTTPException(status_code=422, detail="Формат: docx, xlsx или html")

    row = _owned(dataset_id, user, db)
    dataset = _configure(_load_stored(row), payload)
    try:
        result = _execute_command(dataset, payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = f"winnow-report.{fmt}"
    if fmt == "html":
        content = report_to_html([result]).encode("utf-8")
        media = "text/html; charset=utf-8"
    else:
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / filename
            if fmt == "docx":
                result_to_docx(result, target)
                media = (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                )
            else:
                result_to_xlsx(result, target)
                media = (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                )
            content = target.read_bytes()

    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -------------------------------------------------- импорт по ссылке


class ImportRequest(BaseModel):
    url: str
    #: Название набора: обычно название опроса на стороне формы.
    title: str = ""


def _check_public_url(url: str) -> None:
    """Проверяет, что ссылка ведёт наружу, а не внутрь сети.

    Без этой проверки сервер можно заставить скачать «файл» с внутреннего
    адреса (например, со служебного порта на той же машине) - это классическая
    уязвимость SSRF. Пропускаются только публичные http(s)-адреса.
    """
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=422, detail="Ссылка должна начинаться с http:// или https://"
        )
    if not parsed.hostname or not parsed.path:
        raise HTTPException(status_code=422, detail="В ссылке нет адреса или имени файла")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise HTTPException(
            status_code=422, detail=f"Не удалось найти адрес «{parsed.hostname}»"
        ) from exc
    for info in addresses:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise HTTPException(
                status_code=422,
                detail="Ссылка ведёт на внутренний адрес: такие файлы не загружаются",
            )


@router.post("/datasets/import", status_code=201)
def import_by_link(
    payload: ImportRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DatasetOut:
    """Забирает файл по ссылке и загружает как набор.

    Нужно, чтобы из результатов формы можно было одним переходом открыть
    исследование: форма отдаёт ссылку на свою выгрузку, мы её скачиваем.
    """
    url = payload.url.strip()
    _check_public_url(url)

    try:
        # Ждём долго: бесплатные хостинги «просыпаются» до минуты.
        with urllib.request.urlopen(url, timeout=90) as response:
            data = response.read(MAX_UPLOAD + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Не удалось скачать файл по ссылке: {exc}",
        ) from exc
    if len(data) > MAX_UPLOAD:
        raise HTTPException(
            status_code=413, detail=f"Файл больше {MAX_UPLOAD // (1024 * 1024)} МБ"
        )
    if not data:
        raise HTTPException(status_code=400, detail="По ссылке пустой файл")

    filename = pathlib.Path(urllib.parse.urlparse(url).path).name or "survey.csv"
    if not pathlib.Path(filename).suffix:
        filename += ".csv"
    try:
        path, dataset = storage.import_file(user.id, filename, data)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Не удалось прочитать файл: {exc}"
        ) from exc

    name = (payload.title.strip() or pathlib.Path(filename).stem)[:200]
    row = Dataset(
        user_id=user.id,
        name=name,
        original_filename=filename[:255],
        path=str(path),
        n_cases=int(len(dataset.frame)),
        n_variables=len(dataset.names()),
    )
    db.add(row)
    db.commit()
    return _dataset_out(row)


# ------------------------------------------------------------------ графики


class ChartRequest(BaseModel):
    #: Значения формы графика - те же поля, что в окне настольной версии.
    values: dict = Field(default_factory=dict)
    #: Тема оформления: график рисуется под неё, а не перекрашивается снаружи.
    theme: str = "light"


@router.get("/charts")
def list_charts(user: User = Depends(current_user)) -> list[dict]:
    return [{"key": key, "title": title} for title, key in CHART_TYPES]


@router.post("/datasets/{dataset_id}/chart")
def draw_chart(
    dataset_id: int,
    payload: ChartRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Считает данные графика движком и возвращает готовую картинку SVG.

    Рисование на сервере выбрано намеренно: формулы остаются в одном месте
    (stats/charts.py), и график одинаково выглядит в интерфейсе и в выгрузке.
    """
    spec = DIALOG_SPECS.get("graph")
    if spec is None:
        raise HTTPException(status_code=500, detail="Описание формы графика не найдено")

    # Столбиковой и круговой диаграмме нужна переменная категорий, остальным -
    # список переменных. Пусто и там, и там - значит строить нечего.
    if not payload.values.get("variables") and not payload.values.get("category"):
        raise HTTPException(
            status_code=422, detail="Отметьте переменные для графика"
        )

    kind = str(payload.values.get("kind") or "")
    # Столбиковой, круговой и линии нужна переменная категорий: без неё движок
    # падает внутренней ошибкой, и человек видит английский текст.
    if kind in ("bar", "pie", "line") and not payload.values.get("category"):
        raise HTTPException(
            status_code=422,
            detail="Для столбиковой и круговой диаграммы, а также линии "
            "выберите переменную в поле «Категории»",
        )

    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    try:
        command = spec.build(payload.values, dataset)
        data = build_chart_data(command)
        caption = chart_caption(data)
        svg = charts_svg.render(data, payload.theme)
    except (ValueError, TypeError, IndexError) as exc:
        # Тексты самого движка уже на русском и по делу; внутренние ошибки
        # Python показывать человеку нельзя.
        message = str(exc)
        if not any("а" <= ch.lower() <= "я" for ch in message):
            message = "Не удалось построить график: проверьте выбранные переменные"
        raise HTTPException(status_code=422, detail=message) from exc

    return {
        "kind": data.kind,
        "title": data.title,
        "caption": caption,
        "svg": svg,
    }


# --------------------------------------------------------------- процедуры


def _field_out(field) -> dict:
    return {
        "name": field.name,
        "label": field.label,
        "kind": field.kind.value,
        "filter": field.var_filter.value,
        "default": field.default,
        "choices": [{"label": label, "value": value} for label, value in field.choices],
        "min": field.minimum,
        "max": field.maximum,
        "step": field.step,
        "decimals": field.decimals,
        "tooltip": field.tooltip,
        "row": field.row,
        "column": field.column,
    }


@router.get("/procedures")
def list_procedures(user: User = Depends(current_user)) -> list[dict]:
    """Все процедуры с описанием окон: фронтенд строит по этому формы."""
    return [
        {
            "key": spec.key,
            "title": spec.title,
            "description": spec.description,
            "allowed": spec.key in ALLOWED_PROCEDURES,
        }
        for spec in DIALOG_SPECS.values()
    ]


@router.get("/procedures/{key}")
def get_procedure(key: str, user: User = Depends(current_user)) -> dict:
    spec = DIALOG_SPECS.get(key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Процедура не найдена")
    return {
        "key": spec.key,
        "title": spec.title,
        "description": spec.description,
        "allowed": spec.key in ALLOWED_PROCEDURES,
        "fields": [_field_out(field) for field in spec.fields],
    }


# ------------------------------------------- вопросы с несколькими ответами


@router.get("/datasets/{dataset_id}/multi-answer")
def list_multi_answer(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Какие вопросы похожи на «выберите всё подходящее»."""
    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    found = detect_multi_answer(dataset)
    return {
        "count": len(found),
        "items": [
            {
                "name": item.name,
                "summary": item.summary(),
                "options": len(getattr(item, "options", []) or []),
            }
            for item in found
        ],
    }


@router.post("/datasets/{dataset_id}/multi-answer/split")
def split_multi_answer(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Разбивает такие вопросы на переменные-отметки 1/0 и сохраняет набор.

    Анкетные сервисы пишут несколько вариантов в одну ячейку, и анализировать
    такую переменную нельзя. Разбиение превращает её в набор отметок - по одной
    на вариант, как это делают в SPSS. Исходные столбцы остаются на месте.
    """
    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    before = len(dataset.names())
    created, handled = split_all(dataset)
    if not created:
        raise HTTPException(
            status_code=422,
            detail="Вопросов с несколькими ответами не найдено: в ячейках нет "
            "нескольких вариантов через «;» или запятой с номером",
        )
    storage.save_dataset(dataset, row.path)
    db.query(Dataset).filter(Dataset.id == row.id).update(
        {Dataset.n_variables: len(dataset.names())}
    )
    db.commit()
    return {
        "created": created,
        "n_created": len(created),
        "n_questions": len(handled),
        "n_variables_before": before,
        "n_variables_after": len(dataset.names()),
        "report": format_report(handled, created),
        "variables": storage.variables_payload(dataset),
    }


# ------------------------------------------------------------- скачивание


DOWNLOAD_FORMATS = {
    "sav": ("application/octet-stream", "winnow-data.sav"),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "winnow-data.xlsx",
    ),
    "csv": ("text/csv; charset=utf-8", "winnow-data.csv"),
}


@router.get("/datasets/{dataset_id}/download")
def download_dataset(
    dataset_id: int,
    format: str = "sav",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Отдаёт набор файлом - вместе с правками, которые внесли в вебе.

    Люди просят именно файл: данные правят в браузере, а дальше работают в SPSS
    или Excel. Форматы те же, что движок умеет писать.
    """
    fmt = format.lower()
    if fmt not in DOWNLOAD_FORMATS:
        raise HTTPException(status_code=422, detail="Формат: sav, xlsx или csv")

    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    media, filename = DOWNLOAD_FORMATS[fmt]
    with tempfile.TemporaryDirectory() as folder:
        target = pathlib.Path(folder) / filename
        try:
            if fmt == "sav":
                write_sav(dataset, target)
            elif fmt == "xlsx":
                write_excel(dataset, target)
            else:
                write_csv(dataset, target)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        content = target.read_bytes()

    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["ALLOWED_PROCEDURES", "router"]
