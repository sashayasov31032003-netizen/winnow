// Публичная форма опроса: /s/<slug>.
//
// Это единственная страница, которую видит человек, не заходящий в Winnow.
// Входа здесь нет: ссылку отправляют кому угодно. Поэтому страница работает и
// без аккаунта, и без панели, а тема оформления по умолчанию светлая - анкету
// читает человек, а не статистик.
//
// Разметку полей экспортирует SurveyFields: её же использует предпросмотр в
// конструкторе. Так «как увидит респондент» не расходится с настоящей формой.

import { useEffect, useState } from "react";
import { api, ApiError, type PublicSurvey, type SurveyQuestion } from "./api";
import { applyTheme, initialTheme } from "./theme";
import {
  emptyValue,
  initialAnswers,
  requiredErrors,
  toAnswerInputs,
  type Answers,
  type QuestionValue,
} from "./surveyAnswers";

function ChoiceList({
  question,
  value,
  disabled,
  onChange,
}: {
  question: SurveyQuestion;
  value: QuestionValue;
  disabled: boolean;
  onChange: (value: QuestionValue) => void;
}) {
  const multiple = question.kind === "multi";
  return (
    <div className="choices">
      {question.choices.map((choice) => {
        const checked = value.option_ids.includes(choice.id);
        return (
          <label key={choice.id} className={`choice${checked ? " checked" : ""}`}>
            <input
              type={multiple ? "checkbox" : "radio"}
              name={`question-${question.id}`}
              checked={checked}
              disabled={disabled}
              onChange={() => {
                const next = multiple
                  ? checked
                    ? value.option_ids.filter((id) => id !== choice.id)
                    : [...value.option_ids, choice.id]
                  : [choice.id];
                onChange({ ...value, option_ids: next });
              }}
            />
            <span>{choice.label}</span>
          </label>
        );
      })}
    </div>
  );
}

function ScaleInput({
  question,
  value,
  disabled,
  onChange,
}: {
  question: SurveyQuestion;
  value: QuestionValue;
  disabled: boolean;
  onChange: (value: QuestionValue) => void;
}) {
  const first = question.min ?? 1;
  const last = question.max ?? 5;
  const points: number[] = [];
  for (let point = first; point <= last; point += 1) points.push(point);

  return (
    <div className="scale" role="radiogroup">
      {points.map((point) => {
        const checked = value.value_number === String(point);
        return (
          <label key={point} className={`scale-point${checked ? " checked" : ""}`}>
            <input
              type="radio"
              name={`question-${question.id}`}
              checked={checked}
              disabled={disabled}
              onChange={() => onChange({ ...value, value_number: String(point) })}
            />
            {point}
          </label>
        );
      })}
    </div>
  );
}

/** Поля одного вопроса: ими пользуются и форма, и предпросмотр. */
export function SurveyFields({
  questions,
  answers,
  errors,
  disabled = false,
  onChange,
}: {
  questions: SurveyQuestion[];
  answers: Answers;
  errors: Record<number, string>;
  disabled?: boolean;
  onChange: (answers: Answers) => void;
}) {
  return (
    <div className="questions">
      {questions.map((question, index) => {
        const key = question.id ?? -(index + 1);
        const value = answers[key] ?? emptyValue();
        const error = errors[key];
        return (
          <section className={`question${error ? " invalid" : ""}`} key={key}>
            <div className="question-head">
              <span className="question-number">{index + 1}</span>
              <div>
                <h3 className="question-text">
                  {question.text}
                  {question.required && <span className="required"> *</span>}
                </h3>
                {question.kind === "multi" && (
                  <p className="muted small">Можно выбрать несколько вариантов</p>
                )}
                {question.kind === "scale" && (
                  <p className="muted small">
                    {question.min ?? 1} — минимум, {question.max ?? 5} — максимум
                  </p>
                )}
                {question.kind === "text" && question.max_length && (
                  <p className="muted small">До {question.max_length} символов</p>
                )}
              </div>
            </div>

            {question.kind === "single" || question.kind === "multi" ? (
              <ChoiceList
                question={question}
                value={value}
                disabled={disabled}
                onChange={(next) => onChange({ ...answers, [key]: next })}
              />
            ) : question.kind === "scale" ? (
              <ScaleInput
                question={question}
                value={value}
                disabled={disabled}
                onChange={(next) => onChange({ ...answers, [key]: next })}
              />
            ) : question.kind === "text" ? (
              <textarea
                rows={3}
                value={value.value_text}
                maxLength={question.max_length ?? undefined}
                disabled={disabled}
                placeholder="Ваш ответ"
                onChange={(event) =>
                  onChange({
                    ...answers,
                    [key]: { ...value, value_text: event.target.value },
                  })
                }
              />
            ) : (
              <input
                type="number"
                inputMode="decimal"
                value={value.value_number}
                min={question.min ?? undefined}
                max={question.max ?? undefined}
                disabled={disabled}
                placeholder={
                  question.min !== null && question.max !== null
                    ? `от ${question.min} до ${question.max}`
                    : "Число"
                }
                onChange={(event) =>
                  onChange({
                    ...answers,
                    [key]: { ...value, value_number: event.target.value },
                  })
                }
              />
            )}

            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </section>
        );
      })}
    </div>
  );
}

function PublicShell({
  theme,
  onToggleTheme,
  children,
}: {
  theme: "dark" | "light";
  onToggleTheme: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="public">
      <div className="public-column">
        <header className="public-head">
          <div className="brand">
            <span className="brand-mark">W</span>
            Winnow
          </div>
          <button
            type="button"
            className="ghost icon-button"
            title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            onClick={onToggleTheme}
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </header>
        {children}
        <p className="muted small public-foot">Ответы сохраняются в Winnow</p>
      </div>
    </div>
  );
}

function Message({
  title,
  text,
  children,
}: {
  title: string;
  text?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="card public-card">
      <h1>{title}</h1>
      {text && <p className="muted">{text}</p>}
      {children}
    </div>
  );
}

export function PublicForm({ slug }: { slug: string }) {
  const [survey, setSurvey] = useState<PublicSurvey | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<{ title: string; text: string } | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [theme, setTheme] = useState(() => initialTheme());

  // Тема - личная настройка читателя, а не опроса: живёт в браузере.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Анкета загружается один раз на адрес: slug у страницы не меняется, а
  // повторный опрос после ответа начинается с нового открытия ссылки.
  useEffect(() => {
    let alive = true;
    api
      .publicSurvey(slug)
      .then((payload) => {
        if (!alive) return;
        setSurvey(payload);
        setAnswers(initialAnswers(payload.questions));
        setErrors({});
        document.title = payload.title ? `${payload.title} — опрос` : "Опрос";
      })
      .catch((problem) => {
        if (!alive) return;
        if (problem instanceof ApiError && problem.status === 404) {
          setFailure({
            title: "Опрос не найден",
            text: "Ссылка неверная или опрос удалён. Проверьте адрес — возможно, он скопирован не целиком.",
          });
        } else {
          setFailure({
            title: "Не удалось открыть опрос",
            text:
              problem instanceof ApiError
                ? problem.message
                : "Сервер не отвечает. Проверьте соединение и обновите страницу.",
          });
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [slug]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!survey) return;
    const found = requiredErrors(survey.questions, answers);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      // Вопрос может быть ниже экрана: без прокрутки человек не поймёт, почему
      // кнопка «не сработала».
      document
        .querySelector(".question.invalid")
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    setSending(true);
    setFailure(null);
    try {
      await api.submitResponse(slug, toAnswerInputs(survey.questions, answers));
      setDone(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (problem) {
      if (problem instanceof ApiError && problem.status === 409) {
        setSurvey({ ...survey, already_answered: true });
      } else {
        setFailure({
          title: "Ответ не сохранён",
          text:
            problem instanceof ApiError
              ? problem.message
              : "Сервер не отвечает. Проверьте соединение и отправьте ещё раз.",
        });
      }
    } finally {
      setSending(false);
    }
  }

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  if (loading) {
    return (
      <PublicShell theme={theme} onToggleTheme={toggleTheme}>
        <div className="card public-card muted">Загружаем опрос…</div>
      </PublicShell>
    );
  }

  if (!survey) {
    return (
      <PublicShell theme={theme} onToggleTheme={toggleTheme}>
        <Message title={failure?.title ?? "Опрос не найден"} text={failure?.text} />
      </PublicShell>
    );
  }

  if (survey.already_answered) {
    return (
      <PublicShell theme={theme} onToggleTheme={toggleTheme}>
        <Message
          title="Вы уже отвечали"
          text={`Ответ на опрос «${survey.title}» уже записан. Спасибо!`}
        />
      </PublicShell>
    );
  }

  if (survey.status === "closed") {
    return (
      <PublicShell theme={theme} onToggleTheme={toggleTheme}>
        <Message
          title="Опрос закрыт"
          text={`«${survey.title}» больше не принимает ответы. Спасибо всем, кто успел ответить.`}
        />
      </PublicShell>
    );
  }

  if (done) {
    return (
      <PublicShell theme={theme} onToggleTheme={toggleTheme}>
        <Message title="Спасибо!" text="Ответ сохранён. Окно можно закрыть.">
          <p className="muted small">
            Если понадобится пройти опрос ещё раз, понадобится другой браузер или
            режим инкогнито: один браузер — один ответ.
          </p>
        </Message>
      </PublicShell>
    );
  }

  return (
    <PublicShell theme={theme} onToggleTheme={toggleTheme}>
      <form className="card public-card" onSubmit={submit}>
        <h1>{survey.title}</h1>
        {survey.description && <p className="public-description">{survey.description}</p>}
        <p className="public-intro">
          {survey.questions.length > 0
            ? "Заполните анкету и нажмите «Отправить». Ответы анонимны."
            : "В опросе пока нет вопросов."}
        </p>

        <SurveyFields
          questions={survey.questions}
          answers={answers}
          errors={errors}
          onChange={(next) => {
            setAnswers(next);
            setErrors({});
          }}
        />

        {failure && (
          <div className="error" style={{ marginTop: 16 }} role="alert">
            <strong>{failure.title}.</strong> {failure.text}
          </div>
        )}

        <div className="public-actions">
          <button type="submit" disabled={sending || survey.questions.length === 0}>
            {sending ? "Отправляем…" : "Отправить"}
          </button>
          <span className="muted small">Поля со звёздочкой обязательны</span>
        </div>
      </form>
    </PublicShell>
  );
}
