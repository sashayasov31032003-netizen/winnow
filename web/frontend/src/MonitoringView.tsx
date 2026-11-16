import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type DatasetSummary,
  type MonitoringReport,
  type MonitoringVariable,
} from "./api";

// Мониторинг: две волны независимых исследований. Сравниваем общие переменные,
// показываем изменения и тесты. Это не панель одних и тех же людей и не
// причинный эффект.

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(digits).replace(".", ",");
}

function pfmt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value < 0.001) return "< 0,001";
  return value.toFixed(3).replace(".", ",");
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1).replace(".", ",")} %`;
}

function shareText(shares: Record<string, number> | undefined): string {
  if (!shares) return "—";
  return Object.entries(shares)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 2)
    .map(([label, value]) => `${label} ${pct(value)}`)
    .join(" · ");
}

function changeText(row: MonitoringVariable): string {
  if (row.kind === "numeric") {
    const diff = row.change.mean_diff;
    const percent = row.change.percent;
    return `${diff !== null && diff !== undefined && diff > 0 ? "+" : ""}${fmt(diff)}${percent !== null && percent !== undefined ? ` (${percent > 0 ? "+" : ""}${fmt(percent, 1)} %)` : ""}`;
  }
  const points = row.change.share_points;
  if (!points) return row.change.summary;
  const strongest = Object.entries(points).sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]))[0];
  return strongest ? `${strongest[0]}: ${strongest[1] > 0 ? "+" : ""}${fmt(strongest[1], 1)} п.п.` : "—";
}

export function MonitoringView({ datasets }: { datasets: DatasetSummary[] }) {
  const [baselineId, setBaselineId] = useState<number | null>(null);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [report, setReport] = useState<MonitoringReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (datasets.length < 2) return;
    // Список наборов приходит новыми сверху; для мониторинга база — старая
    // волна, текущая — новая.
    const ordered = [...datasets].sort((left, right) =>
      left.created_at.localeCompare(right.created_at),
    );
    const baseline = ordered[0]?.id ?? null;
    const current = ordered[ordered.length - 1]?.id ?? null;
    setBaselineId(baseline);
    setCurrentId(current);
    if (baseline !== null && current !== null) {
      void compare(baseline, current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasets]);

  async function compare(base = baselineId, current = currentId) {
    if (base === null || current === null) return;
    if (base === current) {
      setError("Выберите два разных набора");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await api.monitoringCompare(base, current);
      setReport(response.report);
      setExpanded(new Set());
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось сравнить волны");
    } finally {
      setLoading(false);
    }
  }

  function swap() {
    const base = baselineId;
    setBaselineId(currentId);
    setCurrentId(base);
    setReport(null);
  }

  const visible = useMemo(() => {
    if (!report) return [];
    const normalized = query.trim().toLowerCase();
    return report.variables.filter((row) => {
      if (onlyChanged && !row.significant) return false;
      if (normalized && !row.display.toLowerCase().includes(normalized) && !row.name.toLowerCase().includes(normalized)) return false;
      return true;
    });
  }, [onlyChanged, query, report]);

  if (datasets.length < 2) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">◇</span>
        <h2>Для мониторинга нужны две волны</h2>
        <p>
          Загрузите два набора — например, исследование 2024 и 2025 года.
          Названия наборов станут подписями волн; общие переменные сопоставятся
          автоматически.
        </p>
      </div>
    );
  }

  return (
    <div className="monitoring-layout">
      <div className="card monitoring-head">
        <div>
          <div className="eyebrow">Longitudinal Monitoring</div>
          <h1>Мониторинг исследований</h1>
          <p className="muted">
            Сравните две волны по общим переменным: средние и доли, изменения,
            p-value и поправку на множественные сравнения. Это независимые
            выборки, а не одни и те же респонденты.
          </p>
        </div>
      </div>

      <div className="card monitoring-controls">
        <label>
          <span>Базовая волна</span>
          <select
            value={baselineId ?? ""}
            onChange={(event) => {
              setBaselineId(Number(event.target.value));
              setReport(null);
            }}
          >
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name} · {dataset.n_cases} случаев
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="ghost monitoring-swap" onClick={swap} title="Поменять волны местами">⇄</button>
        <label>
          <span>Текущая волна</span>
          <select
            value={currentId ?? ""}
            onChange={(event) => {
              setCurrentId(Number(event.target.value));
              setReport(null);
            }}
          >
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name} · {dataset.n_cases} случаев
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void compare()} disabled={loading || baselineId === null || currentId === null}>
          {loading ? "Сравниваем…" : "Сравнить волны"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {!report && !error && (
        <div className="card empty">
          <span className="empty-icon" aria-hidden="true">◇</span>
          <h2>Выберите волны</h2>
          <p>Сравнение покажет общие переменные, изменения средних и долей, а также статистическую значимость.</p>
        </div>
      )}

      {report && (
        <>
          <div className="monitoring-stats">
            <div className="monitoring-stat"><span>Общих переменных</span><strong>{report.summary.common_variables}</strong></div>
            <div className="monitoring-stat"><span>Сравнено</span><strong>{report.summary.compared_variables}</strong></div>
            <div className="monitoring-stat"><span>Изменилось значимо</span><strong>{report.summary.changed}</strong></div>
            <div className="monitoring-stat"><span>Без изменений</span><strong>{report.summary.stable}</strong></div>
          </div>

          <div className="monitoring-waves">
            <span><strong>{report.baseline.name}</strong> · N = {report.baseline.n_cases}</span>
            <span className="monitoring-arrow">→</span>
            <span><strong>{report.current.name}</strong> · N = {report.current.n_cases}</span>
          </div>

          {report.summary.top_changes.length > 0 && (
            <div className="card monitoring-findings">
              <strong>Что изменилось сильнее всего</strong>
              <ul>
                {report.summary.top_changes.map((item) => (
                  <li key={item.name}>
                    <span>{item.display}</span>
                    <span>{item.change} · q = {pfmt(item.q)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="card monitoring-table-card">
            <div className="monitoring-table-head">
              <div>
                <h2>Сравнение показателей</h2>
                <p className="muted small">Показаны общие переменные двух наборов.</p>
              </div>
              <div className="monitoring-filters">
                <label className="relations-search">
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Найти переменную"
                  />
                </label>
                <label className="relations-check">
                  <input type="checkbox" checked={onlyChanged} onChange={(event) => setOnlyChanged(event.target.checked)} />
                  Только значимые изменения
                </label>
              </div>
            </div>

            <div className="monitoring-table-wrap">
              <table className="monitoring-table">
                <thead>
                  <tr>
                    <th>Переменная</th>
                    <th>{report.baseline.name}</th>
                    <th>{report.current.name}</th>
                    <th>Изменение</th>
                    <th>p</th>
                    <th>q (FDR)</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => {
                    const isExpanded = expanded.has(row.name);
                    const isNumeric = row.kind === "numeric";
                    return (
                      <tr key={row.name} className={row.significant ? "changed" : ""}>
                        <td>
                          <strong>{row.display}</strong>
                          <small>{row.kind === "numeric" ? "количественная" : "категориальная"} · N {row.baseline.n} → {row.current.n}</small>
                          {row.warning && <small className="monitoring-warning">{row.warning}</small>}
                        </td>
                        <td>
                          {isNumeric ? (
                            <>
                              <strong>{fmt(row.baseline.mean)}</strong>
                              <small>σ {fmt(row.baseline.sd)} · медиана {fmt(row.baseline.median)}</small>
                            </>
                          ) : (
                            <>
                              <strong>{shareText(row.baseline.shares)}</strong>
                              <small>{row.baseline.n} ответов</small>
                            </>
                          )}
                        </td>
                        <td>
                          {isNumeric ? (
                            <>
                              <strong>{fmt(row.current.mean)}</strong>
                              <small>σ {fmt(row.current.sd)} · медиана {fmt(row.current.median)}</small>
                            </>
                          ) : (
                            <>
                              <strong>{shareText(row.current.shares)}</strong>
                              <small>{row.current.n} ответов</small>
                            </>
                          )}
                        </td>
                        <td>
                          <strong>{changeText(row)}</strong>
                          {isNumeric && row.change.cohen_d !== null && row.change.cohen_d !== undefined && (
                            <small>d = {fmt(row.change.cohen_d)}</small>
                          )}
                          {!isNumeric && row.change.share_points && (
                            <button
                              type="button"
                              className="ghost small-button"
                              onClick={() => {
                                const next = new Set(expanded);
                                if (isExpanded) next.delete(row.name);
                                else next.add(row.name);
                                setExpanded(next);
                              }}
                            >
                              {isExpanded ? "Скрыть доли" : "Все доли"}
                            </button>
                          )}
                        </td>
                        <td>{pfmt(row.p)}</td>
                        <td>{pfmt(row.q)}</td>
                        <td>
                          <span className={`monitoring-status ${row.significant ? "changed" : "stable"}`}>
                            {row.significant ? "изменилось" : "стабильно"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!visible.length && <p className="muted small monitoring-empty">По этому фильтру переменных нет.</p>}
            </div>

            {[...expanded].map((name) => {
              const row = report.variables.find((item) => item.name === name);
              if (!row || !row.change.share_points) return null;
              return (
                <div key={name} className="monitoring-shares">
                  <strong>{row.display}: доли по категориям</strong>
                  <div className="monitoring-share-grid">
                    {Object.entries(row.change.share_points).map(([category, points]) => (
                      <div key={category} className="monitoring-share">
                        <span>{category}</span>
                        <span>{pct(row.baseline.shares?.[category] ?? 0)} → {pct(row.current.shares?.[category] ?? 0)}</span>
                        <strong>{points > 0 ? "+" : ""}{fmt(points, 1)} п.п.</strong>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="card monitoring-methodology">
            <strong>Методология</strong>
            <ul>
              <li>{String(report.methodology.numeric ?? "")}</li>
              <li>{String(report.methodology.categorical ?? "")}</li>
              <li>Множественные сравнения: {String(report.methodology.multiple_testing ?? "")}.</li>
              <li>{String(report.methodology.design === "independent waves" ? "Это независимые выборки; сравнение не доказывает причинный эффект." : "")}</li>
            </ul>
            {report.summary.skipped.length > 0 && (
              <p className="muted small">Пропущено: {report.summary.skipped.join("; ")}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
