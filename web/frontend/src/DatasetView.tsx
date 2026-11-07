import { useEffect, useState } from "react";
import { plural } from "./format";
import { ProcedureForm } from "./ProcedureForm";
import { ChartView } from "./ChartView";
import { QualityPanel } from "./QualityPanel";
import {
  api,
  ApiError,
  type DatasetDetail,
  type CellEdit,
  type Preview,
  type RunResult,
  type Scenarios,
} from "./api";

type Tab = "variables" | "data" | "quality" | "scenarios" | "procedures" | "charts";

export function DatasetView({
  datasetId,
  onDelete,
  advanced,
  theme,
}: {
  datasetId: number;
  onDelete: () => void;
  advanced: boolean;
  theme: "dark" | "light";
}) {
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [scenarios, setScenarios] = useState<Scenarios | null>(null);
  const [tab, setTab] = useState<Tab>("variables");
  const [error, setError] = useState("");
  const [report, setReport] = useState<RunResult | null>(null);
  const [lastRun, setLastRun] = useState<Record<string, unknown> | null>(null);
  const [multiCount, setMultiCount] = useState(0);
  const [splitReport, setSplitReport] = useState("");
  const [version, setVersion] = useState(0);

  // Отчёт собирается под тему в момент расчёта. При смене темы повторяем
  // последний запрос, чтобы человек не нажимал «Выполнить» заново.
  useEffect(() => {
    if (!lastRun) return;
    let alive = true;
    const procedure = String(lastRun.procedure ?? "");
    const request = (("values" in lastRun ? lastRun.values : lastRun.params) ??
      {}) as Record<string, unknown>;
    const options: Record<string, unknown> = { theme };
    if (lastRun.split_by) options.split_by = lastRun.split_by;
    if (lastRun.weight) options.weight = lastRun.weight;
    api
      .run(datasetId, procedure, request, options)
      .then((loaded) => {
        if (alive) setReport(loaded);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  // Отчёт появляется выше формы, а кнопка «Выполнить» - внизу формы.
  // Без прокрутки человек не увидит, что расчёт готов.
  useEffect(() => {
    if (report) {
      document.getElementById("report-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [report]);

  // В простом режиме продвинутые вкладки скрыты: новичку они только мешают.
  useEffect(() => {
    if (!advanced && (tab === "procedures" || tab === "charts")) {
      setTab("scenarios");
    }
  }, [advanced, tab]);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setPreview(null);
    setScenarios(null);

    async function load() {
      try {
        const [head, rows, hints] = await Promise.all([
          api.dataset(datasetId),
          api.preview(datasetId),
          api.scenarios(datasetId),
        ]);
        if (!alive) return;
        setDetail(head);
        setPreview(rows);
        setScenarios(hints);
      } catch (problem) {
        if (!alive) return;
        setError(problem instanceof ApiError ? problem.message : "Ошибка соединения");
      }
    }

    void load();
    api
      .multiAnswer(datasetId)
      .then((found) => alive && setMultiCount(found.count))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [datasetId, version]);

  async function runScenario(procedure: string, params: Record<string, unknown>) {
    setRunning(true);
    setError("");
    try {
      setReport(await api.run(datasetId, procedure, params, { theme }));
      setLastRun({ procedure, params });
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось выполнить расчёт");
    } finally {
      setRunning(false);
    }
  }

  async function downloadDataset(format: string) {
    setError("");
    try {
      const blob = await api.downloadDataset(datasetId, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `winnow-data.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось скачать набор");
    }
  }

  async function download(format: string) {
    if (!lastRun) return;
    setError("");
    try {
      const blob = await api.exportReport(datasetId, lastRun, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `winnow-report.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось выгрузить отчёт");
    }
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!detail) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">
          ⏳
        </span>
        <p>Читаем набор…</p>
      </div>
    );
  }

  return (
    <>
      <div className="main-head">
        <div>
          <h1>{detail.name}</h1>
          <p className="main-meta">
            {plural(detail.n_cases, "случай", "случая", "случаев")}
            <span className="dot">·</span>
            {plural(detail.n_variables, "переменная", "переменные", "переменных")}
            <span className="dot">·</span>
            <span className="muted">{detail.original_filename}</span>
          </p>
        </div>
        <div className="main-actions">
          <span className="muted small">Скачать:</span>
          {(["sav", "xlsx", "csv"] as const).map((fmt) => (
            <button
              key={fmt}
              type="button"
              className="ghost"
              onClick={() => void downloadDataset(fmt)}
              title={`Скачать набор в формате ${fmt.toUpperCase()}`}
            >
              {fmt.toUpperCase()}
            </button>
          ))}
          {multiCount > 0 && (
            <button
              type="button"
              onClick={async () => {
                setError("");
                try {
                  const result = await api.splitMultiAnswer(datasetId);
                  setSplitReport(result.report);
                  setVersion((current) => current + 1);
                } catch (problem) {
                  setError(
                    problem instanceof ApiError
                      ? problem.message
                      : "Не удалось разбить вопросы",
                  );
                }
              }}
            >
              Разбить вопросы с ответами ({multiCount})
            </button>
          )}
          <button type="button" className="danger" onClick={onDelete}>
            Удалить набор
          </button>
        </div>
      </div>

      {splitReport && (
        <div
          className="card"
          style={{ padding: "12px 16px", marginBottom: 16, whiteSpace: "pre-line" }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <strong>Вопросы разбиты на отметки</strong>
            <button type="button" className="ghost" onClick={() => setSplitReport("")}>
              Скрыть
            </button>
          </div>
          <p className="small" style={{ margin: "8px 0 0" }}>
            {splitReport}
          </p>
        </div>
      )}

      <div className="tabs">
        <button
          type="button"
          className={tab === "variables" ? "active" : ""}
          onClick={() => setTab("variables")}
        >
          Переменные
        </button>
        <button
          type="button"
          className={tab === "data" ? "active" : ""}
          onClick={() => setTab("data")}
        >
          Данные
        </button>
        <button
          type="button"
          className={tab === "quality" ? "active" : ""}
          onClick={() => setTab("quality")}
        >
          Качество
        </button>
        <button
          type="button"
          className={tab === "scenarios" ? "active" : ""}
          onClick={() => setTab("scenarios")}
        >
          Что можно сделать
        </button>
        {advanced && (
          <button
            type="button"
            className={tab === "procedures" ? "active" : ""}
            onClick={() => setTab("procedures")}
          >
            Процедуры
          </button>
        )}
        {advanced && (
          <button
            type="button"
            className={tab === "charts" ? "active" : ""}
            onClick={() => setTab("charts")}
          >
            Графики
          </button>
        )}
      </div>

      {advanced && tab === "charts" && (
        <ChartView datasetId={datasetId} variables={detail.variables} theme={theme} />
      )}
      {advanced && tab === "procedures" && (
        <ProcedureForm
          datasetId={datasetId}
          variables={detail.variables}
          theme={theme}
          onReport={(loaded, request) => {
            setReport(loaded);
            setLastRun(request);
          }}
        />
      )}
      {tab === "variables" && <VariablesTable detail={detail} />}
      {tab === "data" && <DataTable preview={preview} datasetId={datasetId} />}
      {tab === "quality" && (
        <QualityPanel datasetId={datasetId} variables={detail.variables} />
      )}
      {tab === "scenarios" && (
        <ScenariosPanel payload={scenarios} running={running} onRun={runScenario} />
      )}

      {report && (
        <div id="report-card" className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="report-head">
            <strong>{report.title}</strong>
            <div className="report-actions">
              {(["docx", "xlsx", "html"] as const).map((format) => (
                <button
                  key={format}
                  type="button"
                  className="ghost"
                  onClick={() => void download(format)}
                  title={`Скачать отчёт в формате ${format.toUpperCase()}`}
                >
                  {format === "docx" ? "Word" : format === "xlsx" ? "Excel" : "HTML"}
                </button>
              ))}
              <button type="button" className="ghost" onClick={() => setReport(null)}>
                Закрыть
              </button>
            </div>
          </div>
          {/* Отчёт готовит наш же сервер из данных движка, поэтому разметка
              вставляется как есть. Если когда-нибудь в отчёт попадёт текст
              пользователя, его нужно будет экранировать. */}
          {/*
            Отчёт приходит готовым HTML со своими стилями («белая бумага»).
            Если вставить его прямо в страницу, эти стили начинают действовать
            на всё приложение - экран становится белым. Поэтому отчёт живёт в
            отдельном фрейме: полная изоляция, а высота подгоняется по содержимому.
          */}
          <iframe
            title={report.title}
            srcDoc={report.html}
            className="report-frame"
            onLoad={(event) => {
              const frame = event.currentTarget;
              const document_ = frame.contentDocument;
              if (document_) {
                frame.style.height = `${document_.documentElement.scrollHeight + 32}px`;
              }
            }}
          />
        </div>
      )}
    </>
  );
}

function measureBadge(measure: string, label: string) {
  return (
    <span className="badge" data-tone={measure}>
      {label || measure}
    </span>
  );
}

//: Уверенность советчика — тоже состояние, а не украшение: зелёный и жёлтый
//: подсказывают, стоит ли доверять предложению.
function confidenceTone(value: string): string | undefined {
  if (value.includes("подходит")) return "scale";
  if (value.includes("возможн")) return "warning";
  return undefined;
}

function VariablesTable({ detail }: { detail: DatasetDetail }) {
  // У набора из опроса имя переменной и есть текст вопроса: колонка меток в
  // этом случае была бы целиком из прочерков.
  const hasLabels = detail.variables.some(
    (variable) => variable.label && variable.label !== variable.name,
  );

  return (
    <div className="card table-wrap variables-table">
      <table>
        <thead>
          <tr>
            <th>Переменная</th>
            {hasLabels && <th>Метка</th>}
            <th>Уровень измерения</th>
            <th className="num">Различных</th>
            <th className="num">Пропусков</th>
          </tr>
        </thead>
        <tbody>
          {detail.variables.map((variable) => (
            <tr key={variable.name}>
              <td>{variable.name}</td>
              {hasLabels && (
                <td>
                  {variable.label && variable.label !== variable.name ? (
                    variable.label
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              )}
              <td>{measureBadge(variable.measure, variable.measure_ru)}</td>
              <td className="num">{variable.n_unique}</td>
              <td className="num">{variable.n_missing}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DataTable({
  preview,
  datasetId,
}: {
  preview: Preview | null;
  datasetId: number;
}) {
  const limit = 50;
  const [rows, setRows] = useState<Preview["rows"]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [dirty, setDirty] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!preview) return;
    setRows(preview.rows);
    setColumns(preview.columns);
    setOffset(preview.offset);
    setTotal(preview.total);
    setDirty({});
  }, [preview]);

  async function load(nextOffset: number) {
    setError("");
    try {
      const page = await api.preview(datasetId, nextOffset, limit);
      setRows(page.rows);
      setColumns(page.columns);
      setOffset(page.offset);
      setTotal(page.total);
      setDirty({});
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось прочитать строки");
    }
  }

  async function save() {
    const edits: CellEdit[] = Object.entries(dirty).map(([key, value]) => {
      const [rowIndex, ...rest] = key.split("|");
      return { row: offset + Number(rowIndex), column: rest.join("|"), value };
    });
    if (edits.length === 0) return;
    setSaving(true);
    setError("");
    try {
      const page = await api.updateCells(datasetId, edits, offset, limit);
      setRows(page.rows);
      setColumns(page.columns);
      setOffset(page.offset);
      setDirty({});
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }

  if (!preview) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">
          ⏳
        </span>
        <p>Читаем строки…</p>
      </div>
    );
  }

  const dirtyCount = Object.keys(dirty).length;

  return (
    <>
      <div className="data-toolbar">
        <span className="muted small">
          Строки {offset + 1}–{Math.min(offset + rows.length, total)} из {total}
        </span>
        <button type="button" className="ghost small-button" disabled={offset === 0} onClick={() => void load(Math.max(0, offset - limit))}>
          ← Назад
        </button>
        <button
          type="button"
          className="ghost small-button"
          disabled={offset + limit >= total}
          onClick={() => void load(offset + limit)}
        >
          Вперёд →
        </button>
        <span className="spacer" />
        {dirtyCount > 0 && (
          <span className="badge" data-tone="warning">
            Изменено ячеек: {dirtyCount}
          </span>
        )}
        <button
          type="button"
          className="small-button"
          disabled={saving || dirtyCount === 0}
          onClick={() => void save()}
        >
          {saving ? "Сохраняем…" : "Сохранить изменения"}
        </button>
        <button
          type="button"
          className="ghost small-button"
          disabled={saving || dirtyCount === 0}
          onClick={() => setDirty({})}
        >
          Отменить
        </button>
      </div>

      {error && (
        <div className="error" style={{ marginBottom: 10 }}>
          {error}
        </div>
      )}

      <p className="data-hint">
        Ячейки можно править: щёлкните по значению и введите новое. Пропуск
        оставляется пустым полем.
      </p>

      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 44 }}>№</th>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={offset + index}>
                <td className="muted small">{offset + index + 1}</td>
                {columns.map((column) => {
                  const key = `${index}|${column}`;
                  const value = dirty[key] ?? row[column];
                  const changed = key in dirty;
                  return (
                    <td key={column} style={{ padding: 2 }}>
                      <input
                        className="cell-input"
                        data-dirty={changed ? "true" : undefined}
                        value={value === null || value === undefined ? "" : String(value)}
                        onChange={(event) =>
                          setDirty((current) => ({ ...current, [key]: event.target.value }))
                        }
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ScenariosPanel({
  payload,
  running,
  onRun,
}: {
  payload: Scenarios | null;
  running: boolean;
  onRun: (procedure: string, params: Record<string, unknown>) => void;
}) {
  if (!payload) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">
          ⏳
        </span>
        <p>Подбираем исследования…</p>
      </div>
    );
  }
  return (
    <div className="scenarios">
      {payload.notes.length > 0 && (
        <div className="card notes">
          <strong className="small">Что важно знать об этих данных</strong>
          {payload.notes.map((note) => (
            <span key={note} className="muted small">
              • {note}
            </span>
          ))}
        </div>
      )}

      {payload.scenarios.length === 0 && (
        <div className="card empty">
          <span className="empty-icon" aria-hidden="true">
            💡
          </span>
          <p>Подсказать нечего: в наборе нет переменных, пригодных для анализа.</p>
        </div>
      )}

      {payload.scenarios.map((scenario) => (
        <div key={scenario.key} className="card scenario">
          <div className="scenario-head">
            <h3>{scenario.title}</h3>
            <span className="badge" data-tone={confidenceTone(scenario.confidence)}>
              {scenario.confidence}
            </span>
          </div>
          <p className="question" style={{ margin: 0 }}>
            {scenario.question}
          </p>
          <p className="muted small" style={{ margin: 0 }}>
            Почему: {scenario.why}
          </p>
          {Object.keys(scenario.roles).length > 0 && (
            <p className="muted small" style={{ margin: 0 }}>
              Переменные —{" "}
              {Object.entries(scenario.roles)
                .map(([role, name]) => `${role}: ${name}`)
                .join(", ")}
            </p>
          )}
          {scenario.caveats.slice(0, 1).map((caveat) => (
            <p key={caveat} className="small" style={{ margin: 0, color: "var(--warning)" }}>
              Учтите: {caveat}
            </p>
          ))}
          <div>
            <button
              type="button"
              disabled={running}
              onClick={() => onRun(scenario.procedure, scenario.params)}
            >
              {running ? "Считаем…" : "Выполнить"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
