import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type DatasetSummary,
  type StudyDetail,
  type StudySummary,
  type StudyWave,
  type TrendReport,
  type TrendVariable,
} from "./api";

// Исследование = несколько волн + тренды. Это следующий уровень после
// разового сравнения двух наборов.

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(digits).replace(".", ",");
}

function pfmt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value < 0.001) return "< 0,001";
  return value.toFixed(3).replace(".", ",");
}

function trendText(row: TrendVariable): string {
  if (row.kind === "numeric") {
    const slope = row.trend.slope;
    const unit = row.trend.slope_unit ?? "волна";
    return `${slope !== undefined && slope !== null && slope > 0 ? "+" : ""}${fmt(slope)} за ${unit}`;
  }
  const shift = row.trend.max_shift;
  return shift !== null && shift !== undefined
    ? `макс. сдвиг ${shift > 0 ? "+" : ""}${fmt(shift, 1)} п.п.`
    : row.trend.summary;
}

function seriesFor(row: TrendVariable): number[] {
  if (row.kind === "numeric") {
    return row.waves.map((wave) => wave.mean ?? 0);
  }
  const points = row.trend.share_points ?? {};
  const category = Object.entries(points).sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]))[0]?.[0];
  return row.waves.map((wave) => (category ? (wave.shares?.[category] ?? 0) * 100 : 0));
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="muted small">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = 4 + (index / (values.length - 1)) * 172;
      const y = 38 - ((value - min) / span) * 30;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="study-spark" viewBox="0 0 180 44" aria-hidden="true">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
      {values.map((value, index) => (
        <circle
          key={index}
          cx={4 + (index / (values.length - 1)) * 172}
          cy={38 - ((value - min) / span) * 30}
          r="2.4"
          fill="currentColor"
        />
      ))}
    </svg>
  );
}

export function StudyView({ datasets }: { datasets: DatasetSummary[] }) {
  const [studies, setStudies] = useState<StudySummary[]>([]);
  const [studyId, setStudyId] = useState<number | null>(null);
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [trends, setTrends] = useState<TrendReport | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [label, setLabel] = useState("");
  const [year, setYear] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadStudies(select?: number) {
    try {
      const response = await api.studies();
      setStudies(response.studies);
      const next = select ?? studyId ?? response.studies[0]?.id ?? null;
      setStudyId(next);
      if (next !== null) await loadStudy(next);
      else {
        setDetail(null);
        setTrends(null);
      }
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось прочитать исследования");
    }
  }

  async function loadStudy(id: number) {
    setLoading(true);
    setError("");
    try {
      const loaded = await api.study(id);
      setDetail(loaded);
      setDatasetId(datasets.find((item) => !loaded.waves.some((wave) => wave.dataset_id === item.id))?.id ?? null);
      if (loaded.waves.length >= 2) {
        const response = await api.studyTrends(id);
        setTrends(response.report);
      } else {
        setTrends(null);
      }
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось прочитать исследование");
      setDetail(null);
      setTrends(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStudies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createStudy() {
    if (!name.trim()) {
      setError("Введите название исследования");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const created = await api.createStudy(name.trim(), description.trim());
      setName("");
      setDescription("");
      setCreating(false);
      await loadStudies(created.id);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось создать исследование");
    } finally {
      setLoading(false);
    }
  }

  async function addWave() {
    if (studyId === null || datasetId === null) return;
    setLoading(true);
    setError("");
    try {
      const selected = datasets.find((item) => item.id === datasetId);
      await api.addStudyWave(
        studyId,
        datasetId,
        label.trim() || selected?.name || `Волна ${(detail?.waves.length ?? 0) + 1}`,
        year.trim() ? Number(year) : null,
      );
      setLabel("");
      setYear("");
      await loadStudy(studyId);
      await loadStudies(studyId);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось добавить волну");
    } finally {
      setLoading(false);
    }
  }

  async function removeWave(wave: StudyWave) {
    if (studyId === null) return;
    setError("");
    try {
      await api.removeStudyWave(studyId, wave.id);
      await loadStudy(studyId);
      await loadStudies(studyId);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось удалить волну");
    }
  }

  async function removeStudy() {
    if (studyId === null) return;
    setError("");
    try {
      await api.deleteStudy(studyId);
      setStudyId(null);
      setDetail(null);
      setTrends(null);
      await loadStudies();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось удалить исследование");
    }
  }

  const unused = datasets.filter((item) => !detail?.waves.some((wave) => wave.dataset_id === item.id));
  const visible = (trends?.variables ?? []).filter((row) => {
    const normalized = query.trim().toLowerCase();
    return !normalized || row.display.toLowerCase().includes(normalized) || row.name.toLowerCase().includes(normalized);
  });

  return (
    <div className="study-layout">
      <div className="card study-head">
        <div>
          <div className="eyebrow">Longitudinal Study</div>
          <h1>Исследования и тренды</h1>
          <p className="muted">
            Объедините наборы в одно исследование по волнам — 2022, 2023, 2024 —
            и посмотрите, как меняются средние и доли. Волны — независимые
            выборки; это динамика, а не причинный эффект.
          </p>
        </div>
      </div>

      <div className="card study-manager">
        <div className="study-row">
          <label>
            <span>Исследование</span>
            <select
              value={studyId ?? ""}
              onChange={(event) => {
                const id = Number(event.target.value);
                setStudyId(id);
                void loadStudy(id);
              }}
            >
              {!studies.length && <option value="">Пока нет исследований</option>}
              {studies.map((item) => (
                <option key={item.id} value={item.id}>{item.name} · {item.waves} волн</option>
              ))}
            </select>
          </label>
          <button type="button" className="ghost" onClick={() => void loadStudies(studyId ?? undefined)} disabled={loading}>
            Обновить
          </button>
          <button type="button" className="ghost" onClick={() => setCreating(true)} disabled={loading || creating}>
            Новое
          </button>
          {studyId !== null && (
            <button type="button" className="danger small-button" onClick={() => void removeStudy()} disabled={loading}>
              Удалить исследование
            </button>
          )}
        </div>

        {(!studies.length || creating) && (
          <div className="study-create">
            <label>
              <span>Название</span>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Например: Мониторинг удовлетворённости 2022–2025" />
            </label>
            <label>
              <span>Описание</span>
              <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Что и зачем измеряем" />
            </label>
            <button type="button" onClick={() => void createStudy()} disabled={loading || !name.trim()}>
              Создать исследование
            </button>
            {studies.length > 0 && (
              <button type="button" className="ghost" onClick={() => setCreating(false)}>Отмена</button>
            )}
          </div>
        )}

        {studyId !== null && detail && (
          <>
            <div className="study-wave-head">
              <div>
                <h2>{detail.name}</h2>
                {detail.description && <p className="muted small">{detail.description}</p>}
              </div>
              <span className="study-badge">{detail.waves.length} волн</span>
            </div>

            <div className="study-waves">
              {detail.waves.map((wave) => (
                <div key={wave.id} className="study-wave">
                  <div>
                    <strong>{wave.label}</strong>
                    <span>{wave.year ?? "год не указан"} · {wave.n_cases} случаев</span>
                  </div>
                  <button type="button" className="ghost small-button" onClick={() => void removeWave(wave)}>Убрать</button>
                </div>
              ))}
              {!detail.waves.length && <p className="muted small">Добавьте первую волну из загруженных наборов.</p>}
            </div>

            <div className="study-add-wave">
              <label>
                <span>Набор</span>
                <select value={datasetId ?? ""} onChange={(event) => setDatasetId(Number(event.target.value))}>
                  {!unused.length && <option value="">Все наборы уже добавлены</option>}
                  {unused.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.n_cases}</option>)}
                </select>
              </label>
              <label>
                <span>Подпись волны</span>
                <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="2026 или «после запуска»" />
              </label>
              <label>
                <span>Год (для тренда)</span>
                <input type="number" min={1900} max={2200} value={year} onChange={(event) => setYear(event.target.value)} placeholder="2026" />
              </label>
              <button type="button" onClick={() => void addWave()} disabled={loading || datasetId === null}>
                Добавить волну
              </button>
            </div>
          </>
        )}

        {!studies.length && (
          <button type="button" className="ghost" onClick={() => void loadStudies()} disabled={loading}>Уже есть исследование? Обновить</button>
        )}
        {error && <div className="error">{error}</div>}
      </div>

      {detail && detail.waves.length < 2 && (
        <div className="card empty">
          <span className="empty-icon" aria-hidden="true">◇</span>
          <h2>Добавьте минимум две волны</h2>
          <p>Для тренда нужны два набора с общими переменными.</p>
        </div>
      )}

      {trends && (
        <>
          <div className="study-stats">
            <div className="study-stat"><span>Волн</span><strong>{trends.summary.n_waves}</strong></div>
            <div className="study-stat"><span>Общих переменных</span><strong>{trends.summary.common_variables}</strong></div>
            <div className="study-stat"><span>С трендом</span><strong>{trends.summary.compared_variables}</strong></div>
            <div className="study-stat"><span>Значимых трендов</span><strong>{trends.summary.changed}</strong></div>
          </div>

          <div className="study-timeline">
            {trends.waves.map((wave, index) => (
              <div key={`${wave.label}-${index}`} className="study-timeline-wave">
                <span>{wave.label}</span>
                <strong>{wave.n_cases}</strong>
                <small>{wave.year ?? "—"}</small>
              </div>
            ))}
          </div>

          {trends.summary.top_trends.length > 0 && (
            <div className="card study-findings">
              <strong>Сильнее всего меняется</strong>
              <ul>
                {trends.summary.top_trends.map((item) => (
                  <li key={item.name}>
                    <span>{item.display}</span>
                    <span>{item.summary} · q = {pfmt(item.q)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="card study-table-card">
            <div className="study-table-head">
              <div>
                <h2>Тренды по переменным</h2>
                <p className="muted small">Общие переменные всех волн; p и q — по линейному тренду/χ².</p>
              </div>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти переменную" />
            </div>
            <div className="study-table-wrap">
              <table className="study-table">
                <thead>
                  <tr><th>Переменная</th><th>Динамика</th><th>Тренд</th><th>p</th><th>q (FDR)</th><th></th></tr>
                </thead>
                <tbody>
                  {visible.map((row) => (
                    <tr key={row.name} className={row.significant ? "changed" : ""}>
                      <td>
                        <strong>{row.display}</strong>
                        <small>{row.kind === "numeric" ? "количественная" : "категориальная"}{row.warning ? ` · ${row.warning}` : ""}</small>
                      </td>
                      <td><Sparkline values={seriesFor(row)} /></td>
                      <td>
                        <strong>{trendText(row)}</strong>
                        <small>{row.trend.summary}</small>
                      </td>
                      <td>{pfmt(row.p)}</td>
                      <td>{pfmt(row.q)}</td>
                      <td>
                        <span className={`monitoring-status ${row.significant ? "changed" : "stable"}`}>
                          {row.significant ? "тренд" : "стабильно"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!visible.length && <p className="muted small study-empty">Нет переменных по фильтру.</p>}
            </div>
          </div>

          <div className="card study-methodology">
            <strong>Методология</strong>
            <ul>
              <li>{String(trends.methodology.numeric ?? "")}</li>
              <li>{String(trends.methodology.categorical ?? "")}</li>
              <li>Множественные сравнения: {String(trends.methodology.multiple_testing ?? "")}.</li>
              <li>Волны независимы; тренд не доказывает причинность.</li>
            </ul>
          </div>
        </>
      )}

      {!detail && !error && (
        <div className="card empty">
          <span className="empty-icon" aria-hidden="true">◇</span>
          <h2>Соберите исследование из волн</h2>
          <p>Создайте исследование и добавьте наборы 2022, 2023, 2024 — тренды появятся автоматически.</p>
        </div>
      )}
    </div>
  );
}
