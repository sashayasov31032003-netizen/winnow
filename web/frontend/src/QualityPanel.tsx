import { useState } from "react";
import { api, ApiError, type QualityReport, type Variable } from "./api";

// Проверка качества данных и модели.
//
// Ничего не исправляет и не удаляет: это отчёт, по которому человек решает,
// что делать. Все предупреждения содержат числа, а не общие слова.

const SEVERITY_TITLE: Record<string, string> = {
  critical: "Критично",
  warning: "Предупреждение",
  note: "Заметка",
};

const ROLE_ORDER: Record<string, number> = { critical: 0, warning: 1, note: 2 };

export function QualityPanel({
  datasetId,
  variables,
}: {
  datasetId: number;
  variables: Variable[];
}) {
  const numeric = variables.filter((item) => item.type === "numeric");
  const [target, setTarget] = useState("");
  const [report, setReport] = useState<QualityReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"data" | "model" | null>(null);

  async function check(withModel: boolean) {
    setBusy(withModel ? "model" : "data");
    setError("");
    try {
      let predictors: string[] = [];
      if (withModel) {
        if (!target) {
          setError("Выберите зависимую переменную");
          return;
        }
        // В модель берём количественные показатели: идентификаторы и категории
        // только испортят диагностику.
        const candidates = numeric.filter(
          (item) => item.name !== target && item.measure === "scale",
        );
        predictors = (candidates.length ? candidates : numeric.filter((item) => item.name !== target))
          .map((item) => item.name)
          .slice(0, 20);
      }
      const response = await api.quality(datasetId, withModel ? target : null, predictors);
      setReport(response.report);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось проверить данные");
    } finally {
      setBusy(null);
    }
  }

  const issues = [...(report?.issues ?? [])].sort(
    (left, right) => (ROLE_ORDER[left.severity] ?? 9) - (ROLE_ORDER[right.severity] ?? 9),
  );

  return (
    <div className="quality-layout">
      <div className="card quality-head">
        <div>
          <h2>Качество данных</h2>
          <p className="muted">
            Пропуски, дубликаты, выбросы, дисбаланс групп и диагностика линейной
            модели. Инспектор ничего не меняет — только показывает, где числам
            нельзя верить без оговорки.
          </p>
        </div>
        <div className="quality-actions">
          <button type="button" onClick={() => void check(false)} disabled={busy !== null}>
            {busy === "data" ? "Проверяем…" : "Проверить данные"}
          </button>
          <div className="quality-model">
            <select
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              aria-label="Зависимая переменная"
            >
              <option value="">Модель: выберите зависимую…</option>
              {numeric.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.display}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="ghost"
              onClick={() => void check(true)}
              disabled={busy !== null || !target}
            >
              {busy === "model" ? "Считаем…" : "Проверить модель"}
            </button>
          </div>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {!report && !error && (
        <div className="card empty">
          <span className="empty-icon" aria-hidden="true">
            ◇
          </span>
          <h2>Сначала — паспорт данных</h2>
          <p>
            Нажмите «Проверить данные»: инспектор посмотрит пропуски, дубликаты,
            выбросы и группы. Для линейной модели выберите зависимую переменную
            и нажмите «Проверить модель».
          </p>
        </div>
      )}

      {report && (
        <>
          <div className="quality-stats">
            <Stat label="Случаев" value={report.n_cases.toString()} />
            <Stat label="Переменных" value={report.n_variables.toString()} />
            <Stat
              label="Пропуски"
              value={`${num(report.missing_share * 100, 1)} %`}
              tone={report.missing_share >= 0.1 ? "warning" : undefined}
            />
            <Stat
              label="Дубли строк"
              value={report.duplicate_rows.toString()}
              tone={report.duplicate_rows > 0 ? "warning" : undefined}
            />
            <Stat
              label="Критичных"
              value={report.counts.critical.toString()}
              tone={report.counts.critical > 0 ? "critical" : undefined}
            />
            <Stat
              label="Предупреждений"
              value={report.counts.warning.toString()}
              tone={report.counts.warning > 0 ? "warning" : undefined}
            />
          </div>

          <div className="card quality-block">
            <h3>Найденные проблемы</h3>
            {issues.length === 0 ? (
              <p className="quality-ok">
                Критических проблем не найдено: пропуски и дубли в допустимых
                пределах, явных выбросов и дисбаланса нет.
              </p>
            ) : (
              <div className="quality-issues">
                {issues.map((issue) => (
                  <div key={issue.code} className="quality-issue" data-severity={issue.severity}>
                    <div className="quality-issue-head">
                      <span className="quality-severity">{SEVERITY_TITLE[issue.severity]}</span>
                      <strong>{issue.title}</strong>
                    </div>
                    <p>{issue.details}</p>
                    {issue.variables.length > 0 && (
                      <p className="quality-vars">{issue.variables.join(", ")}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {report.regression && (
            <div className="card quality-block">
              <h3>Диагностика модели</h3>
              <p className="muted small">
                {report.regression.target} ← {report.regression.predictors.join(", ")} ·{" "}
                {report.regression.n} наблюдений
              </p>
              <div className="quality-metrics">
                <Metric label="R²" value={num(report.regression.r_squared, 3)} />
                <Metric label="VIF max" value={num(report.regression.max_vif)} warn={report.regression.max_vif >= 5} />
                <Metric
                  label="Бреуш-Пеган, p"
                  value={formatP(report.regression.breusch_pagan_p)}
                  warn={(report.regression.breusch_pagan_p ?? 1) < 0.05}
                />
                <Metric
                  label="Дарбин-Уотсон"
                  value={num(report.regression.durbin_watson)}
                  warn={report.regression.durbin_watson < 1.5 || report.regression.durbin_watson > 2.5}
                />
                <Metric
                  label="Кука max"
                  value={num(report.regression.cooks_max)}
                  warn={report.regression.cooks_max > 1}
                />
                <Metric
                  label="Влиятельных"
                  value={report.regression.influential_count.toString()}
                  warn={report.regression.influential_count > 0}
                />
                <Metric
                  label="Остатки, p"
                  value={formatP(report.regression.residual_normality_p)}
                  warn={(report.regression.residual_normality_p ?? 1) < 0.05}
                />
              </div>
            </div>
          )}

          <div className="card quality-block">
            <h3>Переменные</h3>
            <div className="table-wrap">
              <table className="quality-table">
                <thead>
                  <tr>
                    <th>Переменная</th>
                    <th>Роль</th>
                    <th className="num">N</th>
                    <th className="num">Пропуски</th>
                    <th className="num">Выбросы</th>
                    <th className="num">Асимметрия</th>
                  </tr>
                </thead>
                <tbody>
                  {report.variables.map((variable) => (
                    <tr key={variable.name}>
                      <td>{variable.label || variable.name}</td>
                      <td>{variable.role}</td>
                      <td className="num">{variable.n}</td>
                      <td className="num">{(variable.missing_share * 100).toFixed(1).replace(".", ",")} %</td>
                      <td className="num">{variable.n_outliers}</td>
                      <td className="num">
                        {variable.skewness === null ? "—" : num(variable.skewness)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="quality-stat" data-tone={tone}>
      <span className="quality-stat-value">{value}</span>
      <span className="quality-stat-label">{label}</span>
    </div>
  );
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="quality-metric" data-warn={warn ? "true" : undefined}>
      <span className="quality-metric-value">{value}</span>
      <span className="quality-metric-label">{label}</span>
    </div>
  );
}

function formatP(value: number | null): string {
  if (value === null) return "—";
  if (value < 0.001) return "< 0,001";
  return value.toFixed(3).replace(".", ",");
}

function num(value: number, digits = 2): string {
  return value.toFixed(digits).replace(".", ",");
}
