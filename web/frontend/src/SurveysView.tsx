// Экран опроса: конструктор, публикация и сохранённые ответы.
//
// Один экран на все состояния: черновик редактируется, открытый опрос можно
// закрыть и посмотреть ссылку, а опрос, который уже собрал ответы, показывается
// только для чтения - правка структуры под готовыми ответами запрещена, иначе
// старые ответы потеряли бы смысл.

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type ResponsesPage,
  type SurveyDetail,
  type SurveyInput,
  type SurveyQuestion,
  type SurveyStatus,
} from "./api";
import { formatDateTime, plural, surveyStatusTitle } from "./format";
import { SurveyFields } from "./PublicForm";
import {
  initialAnswers,
  requiredErrors,
  type QuestionValue,
} from "./surveyAnswers";

type Draft = {
  title: string;
  description: string;
  allowMultiple: boolean;
  closesAt: string;
  questions: SurveyQuestion[];
};

//: Подсказки к типам вопросов: человек выбирает не «number», а то, что хочет
//: спросить, и видит, что получится на выходе.
const KIND_OPTIONS: { kind: SurveyQuestion["kind"]; title: string; hint: string }[] = [
  { kind: "single", title: "Один вариант", hint: "Категория: пол, город, да/нет" },
  { kind: "multi", title: "Несколько вариантов", hint: "Отметки 1/0 по каждому варианту" },
  { kind: "number", title: "Число", hint: "Числовая переменная: возраст, доход" },
  { kind: "scale", title: "Шкала", hint: "Порядковая переменная: оценка от 1 до 5" },
  { kind: "text", title: "Текст", hint: "Свободный ответ: строковая переменная" },
];

function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (value: number) => String(value).padStart(2, "0");
  return [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  ].join("T");
}

function newQuestion(kind: SurveyQuestion["kind"]): SurveyQuestion {
  const question: SurveyQuestion = {
    position: 0,
    kind,
    text: "",
    required: false,
    choices: [],
    min: null,
    max: null,
    max_length: null,
  };
  if (kind === "single" || kind === "multi") {
    question.choices = [
      { id: "", label: "Вариант 1" },
      { id: "", label: "Вариант 2" },
    ];
  }
  if (kind === "scale") {
    question.min = 1;
    question.max = 5;
  }
  if (kind === "text") question.max_length = 2000;
  return question;
}

function changeKind(
  question: SurveyQuestion,
  kind: SurveyQuestion["kind"],
): SurveyQuestion {
  const fresh = newQuestion(kind);
  const keepChoice = kind === "single" || kind === "multi";
  return {
    ...question,
    kind,
    choices: keepChoice
      ? question.choices.length > 0
        ? question.choices
        : fresh.choices
      : [],
    min: kind === "scale" ? (question.min ?? 1) : kind === "number" ? question.min : null,
    max: kind === "scale" ? (question.max ?? 5) : kind === "number" ? question.max : null,
    max_length: kind === "text" ? (question.max_length ?? 2000) : null,
  };
}

function draftOf(detail: SurveyDetail): Draft {
  return {
    title: detail.title,
    description: detail.description,
    allowMultiple: detail.allow_multiple,
    closesAt: toLocalInput(detail.closes_at),
    questions: detail.questions.map((question) => ({
      ...question,
      choices: question.choices.map((choice) => ({ ...choice })),
    })),
  };
}

function payloadOf(draft: Draft): SurveyInput {
  return {
    title: draft.title,
    description: draft.description,
    allow_multiple: draft.allowMultiple,
    // Время из поля «когда закрыть» - местное: браузер переводит его в UTC сам.
    closes_at: draft.closesAt ? new Date(draft.closesAt).toISOString() : null,
    questions: draft.questions.map((question) => ({
      kind: question.kind,
      text: question.text,
      required: question.required,
      choices: question.choices.map((choice) => choice.label),
      min: question.min,
      max: question.max,
      max_length: question.max_length,
    })),
  };
}

function ShareLink({ slug }: { slug: string }) {
  const [copied, setCopied] = useState(false);
  const url = `${window.location.origin}/s/${slug}`;
  return (
    <div className="card share">
      <div>
        <h3>Ссылка для участников</h3>
        <p className="muted small" style={{ marginTop: 4 }}>
          Вход не нужен: ссылку можно отправить любому человеку. Ответы анонимны.
        </p>
      </div>
      <div className="share-row">
        <input readOnly value={url} onFocus={(event) => event.currentTarget.select()} />
        <button
          type="button"
          className="ghost"
          onClick={() => {
            void navigator.clipboard
              ?.writeText(url)
              .then(() => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 2000);
              })
              .catch(() => undefined);
          }}
        >
          {copied ? "Скопировано" : "Копировать"}
        </button>
        <a className="button-link" href={url} target="_blank" rel="noreferrer">
          Открыть
        </a>
      </div>
    </div>
  );
}

/** Предпросмотр: та же разметка, что увидит респондент, но без отправки. */
function PreviewCard({ questions }: { questions: SurveyQuestion[] }) {
  // В новых вопросах ещё нет id из базы; для показа хватает отрицательного.
  const shown = questions.map((question, index) => ({
    ...question,
    id: question.id ?? -(index + 1),
  }));
  const [answers, setAnswers] = useState<Record<number, QuestionValue>>(() =>
    initialAnswers(shown),
  );
  const [errors, setErrors] = useState<Record<number, string>>({});

  return (
    <div className="card public-card preview-card">
      <div className="preview-badge">Так увидит респондент</div>
      <h1>{questions.length > 0 ? "Предпросмотр анкеты" : "Пустая анкета"}</h1>
      <SurveyFields
        questions={shown}
        answers={answers}
        errors={errors}
        onChange={setAnswers}
      />
      <div className="public-actions">
        <button
          type="button"
          onClick={() => setErrors(requiredErrors(shown, answers))}
        >
          Проверить обязательные
        </button>
        <span className="muted small">Отправка в предпросмотре отключена</span>
      </div>
    </div>
  );
}

function ResponsesPanel({ surveyId, total }: { surveyId: number; total: number }) {
  const [page, setPage] = useState<ResponsesPage | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (total === 0) {
    return (
      <div className="card empty" style={{ padding: 24 }}>
        Ответов пока нет. Опубликуйте опрос и отправьте ссылку — ответы появятся здесь.
      </div>
    );
  }

  async function load() {
    setBusy(true);
    setError("");
    try {
      setPage(await api.surveyResponses(surveyId));
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось загрузить ответы");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card responses-card">
      <div className="responses-head">
        <h3>{plural(total, "ответ", "ответа", "ответов")}</h3>
        {!page && (
          <button type="button" className="ghost" onClick={() => void load()} disabled={busy}>
            {busy ? "Загружаем…" : "Показать ответы"}
          </button>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      {page?.responses.map((item) => (
        <article className="response" key={item.id}>
          <div className="response-head">
            <strong>Ответ №{item.id}</strong>
            <span className="muted small">{formatDateTime(item.submitted_at)}</span>
          </div>
          <dl>
            {item.answers.map((answer) => (
              <div className="response-row" key={answer.question_id}>
                <dt>{answer.question}</dt>
                <dd>{answer.value || "—"}</dd>
              </div>
            ))}
          </dl>
        </article>
      ))}
      {page && page.total > page.responses.length && (
        <p className="muted small">
          Показаны последние {page.responses.length} из {page.total}.
        </p>
      )}
    </div>
  );
}

export function SurveysView({
  surveyId,
  onChanged,
  onDeleted,
  onOpenDataset,
}: {
  surveyId: number;
  onChanged: () => void;
  onDeleted: () => void;
  onOpenDataset: (datasetId: number) => void;
}) {
  const [detail, setDetail] = useState<SurveyDetail | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState(false);
  const [analysing, setAnalysing] = useState(false);

  // Экран пересоздаётся при смене опроса (key={surveyId} в App), поэтому
  // начальное состояние уже пустое: сбрасывать его в эффекте не нужно.
  useEffect(() => {
    let alive = true;
    api
      .survey(surveyId)
      .then((loaded) => {
        if (!alive) return;
        setDetail(loaded);
        setDraft(draftOf(loaded));
      })
      .catch((problem) => {
        if (!alive) return;
        setError(problem instanceof ApiError ? problem.message : "Не удалось открыть опрос");
      });
    return () => {
      alive = false;
    };
  }, [surveyId]);

  function apply(updated: SurveyDetail) {
    setDetail(updated);
    setDraft(draftOf(updated));
  }

  function edit(patch: Partial<Draft>) {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setDirty(true);
    setNotice("");
  }

  function editQuestion(index: number, question: SurveyQuestion) {
    if (!draft) return;
    const questions = [...draft.questions];
    questions[index] = question;
    edit({ questions });
  }

  async function save(): Promise<SurveyDetail | null> {
    if (!draft) return null;
    setBusy(true);
    setError("");
    try {
      const saved = await api.saveSurvey(surveyId, payloadOf(draft));
      apply(saved);
      setDirty(false);
      setNotice("Сохранено");
      onChanged();
      return saved;
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось сохранить опрос");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(status: SurveyStatus) {
    if (!draft) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      // Публикуем то, что человек видит на экране: несохранённые правки
      // сохраняются перед сменой статуса, иначе в ссылку ушла бы старая анкета.
      if (dirty && detail?.can_edit) {
        const saved = await api.saveSurvey(surveyId, payloadOf(draft));
        apply(saved);
        setDirty(false);
      }
      const updated = await api.setSurveyStatus(surveyId, status);
      apply(updated);
      setNotice(
        status === "open"
          ? "Опрос опубликован: ссылку можно отправлять"
          : status === "closed"
            ? "Опрос закрыт: новые ответы не принимаются"
            : "Опрос возвращён в черновик",
      );
      onChanged();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось изменить статус");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!detail) return;
    const confirmed = window.confirm(
      `Удалить опрос «${detail.title}»? Восстановить его будет нельзя.`,
    );
    if (!confirmed) return;
    setBusy(true);
    setError("");
    try {
      await api.removeSurvey(surveyId);
      onDeleted();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось удалить опрос");
    } finally {
      setBusy(false);
    }
  }

  async function openInWinnow() {
    setAnalysing(true);
    setError("");
    try {
      // Набор собирается движком на сервере: вопрос = переменная, варианты =
      // метки, множественные ответы = отметки 1/0. Дальше это обычный набор.
      const built = await api.buildSurveyDataset(surveyId);
      onOpenDataset(built.id);
    } catch (problem) {
      setError(
        problem instanceof ApiError ? problem.message : "Не удалось собрать набор из ответов",
      );
    } finally {
      setAnalysing(false);
    }
  }

  if (!detail || !draft) {
    return (
      <div className="card empty">
        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : (
          <>
            <span className="empty-icon" aria-hidden="true">
              ⏳
            </span>
            <p>Загружаем опрос…</p>
          </>
        )}
      </div>
    );
  }

  const editable = detail.can_edit;
  const status = detail.status;

  return (
    <>
      <div className="main-head">
        <div>
          <h1>{draft.title || "Опрос"}</h1>
          <p className="main-meta">
            <span className="status" data-status={status}>
              {surveyStatusTitle(status)}
            </span>
            <span className="dot">·</span>
            {plural(detail.n_questions, "вопрос", "вопроса", "вопросов")}
            <span className="dot">·</span>
            {plural(detail.n_responses, "ответ", "ответа", "ответов")}
            {dirty && (
              <>
                <span className="dot">·</span>
                <span className="badge" data-tone="warning">
                  Есть несохранённые изменения
                </span>
              </>
            )}
          </p>
        </div>
        <div className="main-actions">
          {editable && (
            <button type="button" className="ghost" onClick={() => setPreview((value) => !value)}>
              {preview ? "К конструктору" : "Предпросмотр"}
            </button>
          )}
          {editable && (
            <button type="button" onClick={() => void save()} disabled={busy || !dirty}>
              {busy ? "Сохраняем…" : dirty ? "Сохранить" : "Сохранено"}
            </button>
          )}
          {status === "open" ? (
            <button type="button" className="ghost" onClick={() => void changeStatus("closed")} disabled={busy}>
              Закрыть опрос
            </button>
          ) : (
            <button type="button" onClick={() => void changeStatus("open")} disabled={busy}>
              {status === "closed" ? "Открыть заново" : "Опубликовать"}
            </button>
          )}
          {detail.n_responses === 0 && (
            <button type="button" className="danger" onClick={() => void remove()} disabled={busy}>
              Удалить
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}
      {notice && <div className="notice">{notice}</div>}

      {status === "open" && <ShareLink slug={detail.slug} />}

      {!editable && (
        <div className="notice">
          Опрос уже собрал ответы: структура зафиксирована, иначе старые ответы
          потеряли бы смысл. Менять можно только статус — открыть или закрыть.
        </div>
      )}

      {preview ? (
        <PreviewCard questions={draft.questions} />
      ) : editable ? (
        <>
          <div className="card settings-card">
            <div className="field">
              <label htmlFor="survey-title">Название опроса</label>
              <input
                id="survey-title"
                value={draft.title}
                onChange={(event) => edit({ title: event.target.value })}
                placeholder="Например: Оценка курса"
              />
            </div>
            <div className="field">
              <label htmlFor="survey-description">Описание (необязательно)</label>
              <textarea
                id="survey-description"
                rows={2}
                value={draft.description}
                onChange={(event) => edit({ description: event.target.value })}
                placeholder="Зачем этот опрос и сколько времени займёт"
              />
            </div>
            <div className="settings-row">
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.allowMultiple}
                  onChange={(event) => edit({ allowMultiple: event.target.checked })}
                />
                Разрешить отвечать несколько раз
              </label>
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor="survey-closes">Закрыть автоматически</label>
                <input
                  id="survey-closes"
                  type="datetime-local"
                  value={draft.closesAt}
                  onChange={(event) => edit({ closesAt: event.target.value })}
                />
              </div>
            </div>
            <p className="muted small" style={{ margin: 0 }}>
              Ответы анонимны: не сохраняются адрес, IP и аккаунт. По умолчанию
              один браузер — один ответ, повторы включаются этой настройкой.
            </p>
          </div>

          <div className="questions">
            {draft.questions.map((question, index) => (
              <div className="card question-card" key={index}>
                <div className="question-card-head">
                  <span className="question-number">{index + 1}</span>
                  <select
                    value={question.kind}
                    onChange={(event) =>
                      editQuestion(
                        index,
                        changeKind(question, event.target.value as SurveyQuestion["kind"]),
                      )
                    }
                  >
                    {KIND_OPTIONS.map((option) => (
                      <option key={option.kind} value={option.kind}>
                        {option.title}
                      </option>
                    ))}
                  </select>
                  <div className="row-actions">
                    <button
                      type="button"
                      className="ghost icon-button"
                      title="Выше"
                      disabled={index === 0}
                      onClick={() => {
                        const questions = [...draft.questions];
                        [questions[index - 1], questions[index]] = [
                          questions[index],
                          questions[index - 1],
                        ];
                        edit({ questions });
                      }}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="ghost icon-button"
                      title="Ниже"
                      disabled={index === draft.questions.length - 1}
                      onClick={() => {
                        const questions = [...draft.questions];
                        [questions[index + 1], questions[index]] = [
                          questions[index],
                          questions[index + 1],
                        ];
                        edit({ questions });
                      }}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="danger"
                      onClick={() =>
                        edit({ questions: draft.questions.filter((_, i) => i !== index) })
                      }
                    >
                      Удалить
                    </button>
                  </div>
                </div>

                <input
                  className="question-input"
                  value={question.text}
                  placeholder="Текст вопроса"
                  onChange={(event) =>
                    editQuestion(index, { ...question, text: event.target.value })
                  }
                />

                <p className="muted small" style={{ margin: 0 }}>
                  {KIND_OPTIONS.find((option) => option.kind === question.kind)?.hint}
                </p>

                {question.kind === "single" || question.kind === "multi" ? (
                  <div className="choices-editor">
                    {question.choices.map((choice, choiceIndex) => (
                      <div className="choice-row" key={choiceIndex}>
                        <span className="muted small">{choiceIndex + 1}</span>
                        <input
                          value={choice.label}
                          placeholder="Вариант ответа"
                          onChange={(event) => {
                            const choices = [...question.choices];
                            choices[choiceIndex] = {
                              ...choice,
                              label: event.target.value,
                            };
                            editQuestion(index, { ...question, choices });
                          }}
                        />
                        <button
                          type="button"
                          className="ghost icon-button"
                          title="Убрать вариант"
                          disabled={question.choices.length <= 1}
                          onClick={() =>
                            editQuestion(index, {
                              ...question,
                              choices: question.choices.filter((_, i) => i !== choiceIndex),
                            })
                          }
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="ghost"
                      onClick={() =>
                        editQuestion(index, {
                          ...question,
                          choices: [
                            ...question.choices,
                            { id: "", label: `Вариант ${question.choices.length + 1}` },
                          ],
                        })
                      }
                    >
                      Добавить вариант
                    </button>
                  </div>
                ) : null}

                {question.kind === "number" ? (
                  <div className="settings-row">
                    <div className="field" style={{ margin: 0 }}>
                      <label>Наименьшее значение (необязательно)</label>
                      <input
                        type="number"
                        value={question.min ?? ""}
                        onChange={(event) =>
                          editQuestion(index, {
                            ...question,
                            min: event.target.value === "" ? null : Number(event.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="field" style={{ margin: 0 }}>
                      <label>Наибольшее значение (необязательно)</label>
                      <input
                        type="number"
                        value={question.max ?? ""}
                        onChange={(event) =>
                          editQuestion(index, {
                            ...question,
                            max: event.target.value === "" ? null : Number(event.target.value),
                          })
                        }
                      />
                    </div>
                  </div>
                ) : null}

                {question.kind === "scale" ? (
                  <div className="settings-row">
                    <div className="field" style={{ margin: 0 }}>
                      <label>От</label>
                      <input
                        type="number"
                        min={1}
                        max={9}
                        value={question.min ?? 1}
                        onChange={(event) =>
                          editQuestion(index, {
                            ...question,
                            min: Number(event.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="field" style={{ margin: 0 }}>
                      <label>До</label>
                      <input
                        type="number"
                        min={2}
                        max={10}
                        value={question.max ?? 5}
                        onChange={(event) =>
                          editQuestion(index, {
                            ...question,
                            max: Number(event.target.value),
                          })
                        }
                      />
                    </div>
                  </div>
                ) : null}

                {question.kind === "text" ? (
                  <div className="field" style={{ margin: 0, maxWidth: 260 }}>
                    <label>Предел длины ответа</label>
                    <input
                      type="number"
                      min={1}
                      max={5000}
                      value={question.max_length ?? 2000}
                      onChange={(event) =>
                        editQuestion(index, {
                          ...question,
                          max_length: Number(event.target.value),
                        })
                      }
                    />
                  </div>
                ) : null}

                <label className="check">
                  <input
                    type="checkbox"
                    checked={question.required}
                    onChange={(event) =>
                      editQuestion(index, { ...question, required: event.target.checked })
                    }
                  />
                  Обязательный вопрос
                </label>
              </div>
            ))}
          </div>

          <div className="card add-question">
            <p className="muted small" style={{ margin: 0 }}>
              Добавить вопрос:
            </p>
            <div className="row-actions">
              {KIND_OPTIONS.map((option) => (
                <button
                  key={option.kind}
                  type="button"
                  className="ghost"
                  onClick={() =>
                    edit({ questions: [...draft.questions, newQuestion(option.kind)] })
                  }
                >
                  + {option.title}
                </button>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="card settings-card">
          <h3>Вопросы</h3>
          <ol className="readonly-questions">
            {detail.questions.map((question) => (
              <li key={question.id}>
                <strong>{question.text}</strong>
                <span className="muted small">
                  {question.kind_title}
                  {question.required ? ", обязательный" : ""}
                </span>
                {question.choices.length > 0 && (
                  <div className="muted small">
                    {question.choices.map((choice) => choice.label).join(" · ")}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {detail.n_responses > 0 && (
        <div className="card analyse-card">
          <div>
            <h3>Перенести ответы в «Данные»</h3>
            <p className="muted small">
              Ответы станут набором данных: вопрос — переменная, варианты — метки
              значений, множественные ответы — отметки 1/0. Уровни измерения уже
              известны, поэтому советчику не придётся их угадывать.
            </p>
            <p className="muted small">
              Набор соберётся из{" "}
              {plural(detail.n_responses, "ответа", "ответов", "ответов")}. Появятся
              новые — нажмите снова, набор пересоберётся.
            </p>
          </div>
          <button type="button" onClick={() => void openInWinnow()} disabled={analysing}>
            {analysing ? "Собираем…" : "Исследовать в Winnow"}
          </button>
        </div>
      )}

      <ResponsesPanel surveyId={surveyId} total={detail.n_responses} />
    </>
  );
}
