import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  type DatasetSummary,
  type SurveySummary,
  type User,
} from "./api";
import { DatasetView } from "./DatasetView";
import { RelationshipMapView } from "./RelationshipMapView";
import { ResearchAI } from "./ResearchAI";
import { StressTestView } from "./StressTestView";
import { SurveysView } from "./SurveysView";
import { plural, surveyStatusTitle } from "./format";
import { applyTheme, initialTheme, type Theme } from "./theme";

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (user === undefined) return <div className="splash">Загружаем Winnow…</div>;
  if (user === null) return <AuthScreen onAuthenticated={setUser} />;

  return (
    <Workspace
      user={user}
      initialSection={requestedSection()}
      onLogout={() => {
        void api.logout().finally(() => setUser(null));
      }}
    />
  );
}

//: С какого раздела начинать. Ссылки с главной приходят как
//: /app?section=surveys («создать опрос»), /app?section=ai («исследование»)
//: или /app?section=data («исследовать данные»).
function requestedSection(): "data" | "surveys" | "ai" | "stress" | "relations" {
  const section = new URLSearchParams(window.location.search).get("section");
  if (section === "surveys") return "surveys";
  if (section === "ai") return "ai";
  if (section === "stress") return "stress";
  if (section === "relations") return "relations";
  return "data";
}

function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [mode, setMode] = useState<"login" | "register">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user =
        mode === "login"
          ? await api.login(email, password)
          : await api.register(email, password, invite);
      onAuthenticated(user);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Ошибка соединения");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card auth-card">
        <a className="ghost-link" href="/" style={{ display: "inline-block", marginBottom: 16 }}>
          ← На главную
        </a>
        <a className="brand" href="/">
          <span className="brand-mark">W</span>
          Winnow
        </a>
        <h1 style={{ marginTop: 16 }}>
          {mode === "register" ? "Создать аккаунт" : "Вход"}
        </h1>
        <p className="auth-lead">
          Создайте опрос или загрузите файл с данными — и получите результаты с
          объяснением простыми словами.
        </p>

        <div className="auth-tabs">
          <button
            type="button"
            className={mode === "register" ? "active" : ""}
            onClick={() => setMode("register")}
          >
            Регистрация
          </button>
          <button
            type="button"
            className={mode === "login" ? "active" : ""}
            onClick={() => setMode("login")}
          >
            Вход
          </button>
        </div>

        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="email">Адрес электронной почты</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Пароль (от 8 символов)</label>
            <input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={8}
              required
            />
          </div>
          {mode === "register" && (
            <div className="field">
              <label htmlFor="invite">Код приглашения (если нужен)</label>
              <input
                id="invite"
                value={invite}
                onChange={(event) => setInvite(event.target.value)}
                placeholder="Для первого аккаунта можно оставить пустым"
              />
            </div>
          )}
          {error && (
            <div className="error" style={{ marginBottom: 12 }}>
              {error}
            </div>
          )}
          <button type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Подождите…" : mode === "register" ? "Зарегистрироваться" : "Войти"}
          </button>
        </form>
      </div>
    </div>
  );
}

function Workspace({
  user,
  onLogout,
  initialSection,
}: {
  user: User;
  onLogout: () => void;
  initialSection: "data" | "surveys" | "ai" | "stress" | "relations";
}) {
  // Пять разделов: данные, опросы, исследование с ИИ, устойчивость и карта связей.
  const [section, setSection] = useState<"data" | "surveys" | "ai" | "stress" | "relations">(initialSection);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [surveys, setSurveys] = useState<SurveySummary[]>([]);
  const [surveyId, setSurveyId] = useState<number | null>(null);
  const [creatingSurvey, setCreatingSurvey] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [invite, setInvite] = useState("");
  // Режим запоминается в браузере: это личная настройка человека, а не данных.
  const [advanced, setAdvanced] = useState(
    () => window.localStorage.getItem("winnow.mode") === "expert",
  );
  const [theme, setTheme] = useState<Theme>(() => initialTheme());

  // Тема - свойство человека, а не данных, поэтому живёт в браузере.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  const [collapsed, setCollapsed] = useState(false);
  const [link, setLink] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function refresh() {
    try {
      const list = await api.datasets();
      setDatasets(list);
      setSelected((current) => current ?? list[0]?.id ?? null);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Ошибка соединения");
    }
  }

  async function refreshSurveys() {
    try {
      const list = await api.surveys();
      setSurveys(list);
      setSurveyId((current) => current ?? list[0]?.id ?? null);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Ошибка соединения");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  // Список опросов обновляется при входе в раздел: счётчики ответов меняются
  // снаружи, пока человек работает с данными.
  useEffect(() => {
    if (section === "surveys") void refreshSurveys();
  }, [section]);

  async function upload(file: File) {
    setUploading(true);
    setError("");
    try {
      const created = await api.upload(file);
      setSelected(created.id);
      await refresh();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось загрузить файл");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function importLink(event: React.FormEvent) {
    event.preventDefault();
    if (!link.trim()) return;
    setUploading(true);
    setError("");
    try {
      const created = await api.importLink(link.trim());
      setSelected(created.id);
      setLink("");
      await refresh();
    } catch (problem) {
      setError(
        problem instanceof ApiError ? problem.message : "Не удалось загрузить по ссылке",
      );
    } finally {
      setUploading(false);
    }
  }

  async function remove(id: number) {
    setError("");
    try {
      await api.remove(id);
      setSelected(null);
      await refresh();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось удалить набор");
    }
  }

  async function makeInvite() {
    try {
      setInvite((await api.invite()).code);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось создать приглашение");
    }
  }

  async function createSurvey() {
    setCreatingSurvey(true);
    setError("");
    try {
      // Пустой черновик создаётся сразу: конструктор открывается на нём, и
      // человек не теряет введённое при первом же сохранении.
      const created = await api.createSurvey();
      setSurveyId(created.id);
      setSection("surveys");
      await refreshSurveys();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось создать опрос");
    } finally {
      setCreatingSurvey(false);
    }
  }

  function setMode(expert: boolean) {
    setAdvanced(expert);
    // Режим — личная настройка человека, а не данных: запоминаем в браузере.
    window.localStorage.setItem("winnow.mode", expert ? "expert" : "simple");
  }

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-head">
          <div className="sidebar-top">
            <a className="brand" href="/" title="На главную">
              <span className="brand-mark">W</span>
              Winnow
            </a>
            <button
              type="button"
              className="ghost icon-button"
              title="Свернуть панель"
              aria-label="Свернуть панель"
              onClick={() => setCollapsed(true)}
            >
              ‹
            </button>
          </div>

          <div className="section-switch" role="group" aria-label="Разделы">
            <button
              type="button"
              className={section === "data" ? "active" : ""}
              aria-pressed={section === "data"}
              onClick={() => setSection("data")}
            >
              Данные
            </button>
            <button
              type="button"
              className={section === "surveys" ? "active" : ""}
              aria-pressed={section === "surveys"}
              onClick={() => setSection("surveys")}
            >
              Опросы
            </button>
            <button
              type="button"
              className={section === "ai" ? "active" : ""}
              aria-pressed={section === "ai"}
              onClick={() => setSection("ai")}
            >
              Исследование AI
            </button>
            <button
              type="button"
              className={section === "stress" ? "active" : ""}
              aria-pressed={section === "stress"}
              onClick={() => setSection("stress")}
            >
              Устойчивость
            </button>
            <button
              type="button"
              className={section === "relations" ? "active" : ""}
              aria-pressed={section === "relations"}
              onClick={() => setSection("relations")}
            >
              Карта связей
            </button>
          </div>
        </div>

        {section === "surveys" ? (
          <>
            <div className="sidebar-head">
              <button
                type="button"
                onClick={() => void createSurvey()}
                disabled={creatingSurvey}
              >
                {creatingSurvey ? "Создаём…" : "Создать опрос"}
              </button>
              <p className="muted small" style={{ margin: 0 }}>
                Ссылку на опрос можно отправить любому: вход участнику не нужен.
              </p>
            </div>

            <div className="dataset-list">
              {surveys.length === 0 && (
                <p className="muted small">Пока нет опросов. Создайте первый.</p>
              )}
              {surveys.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`dataset-item${surveyId === item.id ? " active" : ""}`}
                  onClick={() => setSurveyId(item.id)}
                >
                  <span className="name">{item.title}</span>
                  <span className="meta">
                    <span className="status" data-status={item.status}>
                      {surveyStatusTitle(item.status)}
                    </span>
                    <span className="dot">·</span>
                    {plural(item.n_responses, "ответ", "ответа", "ответов")}
                  </span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <div className="sidebar-head">
              {section === "data" ? (
                <>
                  <button
                    type="button"
                    onClick={() => fileInput.current?.click()}
                    disabled={uploading}
                  >
                    {uploading ? "Загружаем…" : "Загрузить файл"}
                  </button>
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".sav,.xlsx,.xls,.csv,.txt,.wndata,.stldata"
                    style={{ display: "none" }}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void upload(file);
                    }}
                  />
                  <form className="link-form" onSubmit={importLink}>
                    <input
                      value={link}
                      onChange={(event) => setLink(event.target.value)}
                      placeholder="Ссылка на CSV или Excel"
                      aria-label="Ссылка на файл с данными"
                      title="Ссылка на файл выгрузки: например, из результатов формы"
                    />
                    <button
                      type="submit"
                      className="ghost"
                      disabled={!link.trim() || uploading}
                    >
                      →
                    </button>
                  </form>
                  <p className="muted small hint" style={{ margin: 0 }}>
                    SPSS (.sav), Excel, CSV — файлом или по ссылке
                  </p>
                </>
              ) : (
                <p className="muted small" style={{ margin: 0 }}>
                  {section === "stress"
                    ? "Выберите набор: Stress Test работает с его переменными и не меняет данные."
                    : section === "relations"
                      ? "Выберите набор: карта покажет связи его переменных, не меняя данные."
                      : "Выберите набор: агент работает с ним и не меняет данные."}
                </p>
              )}
            </div>

            <div className="dataset-list">
              {datasets.length === 0 && (
                <p className="muted small">
                  {section === "data"
                    ? "Пока нет наборов. Загрузите первый файл."
                    : "Нет наборов. Загрузите данные в разделе «Данные»."}
                </p>
              )}
              {datasets.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`dataset-item${selected === item.id ? " active" : ""}`}
                  onClick={() => setSelected(item.id)}
                >
                  <span className="name">{item.name}</span>
                  <span className="meta">
                    {plural(item.n_cases, "случай", "случая", "случаев")} ·{" "}
                    {plural(item.n_variables, "переменная", "переменные", "переменных")}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}

        <div className="sidebar-foot">
          {invite ? (
            <p className="small" style={{ margin: 0 }}>
              Код приглашения: <strong>{invite}</strong>
            </p>
          ) : (
            <button type="button" className="ghost small-button invite" onClick={makeInvite}>
              Создать приглашение
            </button>
          )}

          {/* Звёздочка без подписи не говорила, что делает. Теперь это явный
              переключатель с названиями режимов и пояснением, что скрывается. */}
          <div className="mode-switch" role="group" aria-label="Режим интерфейса">
            <div className="mode-switch-head">
              <span className="mode-switch-title">Режим работы</span>
              <span className="mode-switch-current">
                {advanced ? "Экспертный" : "Простой"}
              </span>
            </div>
            <div className="mode-switch-options">
              <button
                type="button"
                className={advanced ? "" : "active"}
                aria-pressed={!advanced}
                onClick={() => setMode(false)}
              >
                <span className="mode-name">Простой</span>
                <span className="mode-sub">только главное</span>
              </button>
              <button
                type="button"
                className={advanced ? "active" : ""}
                aria-pressed={advanced}
                onClick={() => setMode(true)}
              >
                <span className="mode-name">Экспертный</span>
                <span className="mode-sub">все инструменты</span>
              </button>
            </div>
            <p className="mode-switch-hint">
              Простой скрывает процедуры и графики. Экспертный показывает всё.
            </p>
          </div>

          <p className="sidebar-user" title={user.email}>
            {user.email}
          </p>
          <div className="sidebar-actions">
            <button
              type="button"
              className="ghost icon-button"
              title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
              aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>
            <button type="button" className="ghost logout" onClick={onLogout}>
              Выйти
            </button>
          </div>
          <a className="ghost-link home" href="/">
            На главную
          </a>
        </div>
      </aside>

      <main
        className="main"
        onDragOver={(event) => {
          // Перетаскивание файлов относится к данным: в разделе опросов оно
          // ничего не делает и только пугает пунктирной рамкой.
          if (section !== "data") return;
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          if (section !== "data") return;
          event.preventDefault();
          setDragOver(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void upload(file);
        }}
        style={dragOver ? { outline: "2px dashed var(--accent)", outlineOffset: -8 } : undefined}
      >
        {collapsed && (
          <button
            type="button"
            className="ghost reveal-panel"
            title="Показать панель"
            onClick={() => setCollapsed(false)}
          >
            ›
          </button>
        )}
        {error && (
          <div className="error" style={{ marginBottom: 16 }}>
            {error}
          </div>
        )}
        {section === "surveys" ? (
          surveyId === null ? (
            <div className="card empty">
              <span className="empty-icon" aria-hidden="true">
                📝
              </span>
              <h2>Опросы</h2>
              <p>
                Создайте опрос, добавьте вопросы и отправьте ссылку. Ответы
                сохранятся в базе, а кнопка «Исследовать в Winnow» превратит их в
                набор для анализа — без выгрузки и повторной загрузки файла.
              </p>
              <button type="button" onClick={() => void createSurvey()}>
                Создать опрос
              </button>
            </div>
          ) : (
            <SurveysView
              key={surveyId}
              surveyId={surveyId}
              onChanged={() => void refreshSurveys()}
              onDeleted={() => {
                setSurveyId(null);
                void refreshSurveys();
              }}
              onOpenDataset={(datasetId) => {
                // Набор только что собран на сервере: переключаемся в «Данные»,
                // выбираем его и обновляем список, чтобы он был и в панели.
                setSection("data");
                setSelected(datasetId);
                void refresh();
              }}
            />
          )
        ) : section === "ai" ? (
          selected === null ? (
            <div className="card empty">
              <span className="empty-icon" aria-hidden="true">
                ◇
              </span>
              <h2>Исследование AI</h2>
              <p>
                Выберите набор в панели слева. Агент посмотрит схему и профиль
                данных, предложит метод и запустит реальный расчёт — числа
                берутся из аналитического ядра Winnow.
              </p>
            </div>
          ) : (
            <ResearchAI
              key={selected}
              datasetId={selected}
              datasets={datasets}
              onSelect={setSelected}
              onGoToData={() => setSection("data")}
            />
          )
        ) : section === "stress" ? (
          selected === null ? (
            <div className="card empty">
              <span className="empty-icon" aria-hidden="true">
                ◇
              </span>
              <h2>Устойчивость результатов</h2>
              <p>
                Выберите набор в панели слева. Stress Test пересчитает линейную
                регрессию без влиятельных наблюдений, с робастными ошибками,
                альтернативными спецификациями и Bootstrap — и покажет, где
                вывод меняется.
              </p>
            </div>
          ) : (
            <StressTestView key={selected} datasetId={selected} />
          )
        ) : section === "relations" ? (
          selected === null ? (
            <div className="card empty">
              <span className="empty-icon" aria-hidden="true">
                ◇
              </span>
              <h2>Карта взаимосвязей</h2>
              <p>
                Выберите набор в панели слева. Карта покажет переменные узлами,
                а статистические связи — линиями. Это не причинный граф.
              </p>
            </div>
          ) : (
            <RelationshipMapView key={selected} datasetId={selected} />
          )
        ) : selected === null ? (
          <div className="card empty">
            <span className="empty-icon" aria-hidden="true">
              📄
            </span>
            <h2>Начните с файла</h2>
            <p>
              Перетащите файл в эту область, выберите его кнопкой «Загрузить файл»
              или вставьте ссылку на выгрузку слева. Программа посмотрит, что в
              данных есть, и предложит готовые исследования.
            </p>
          </div>
        ) : (
          <DatasetView
            key={selected}
            datasetId={selected}
            advanced={advanced}
            theme={theme}
            onDelete={() => void remove(selected)}
          />
        )}
      </main>
    </div>
  );
}

