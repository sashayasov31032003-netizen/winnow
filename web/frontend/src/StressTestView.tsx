import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type DatasetDetail,
  type StressReport,
  type StressScenario,
} from "./api";

// Research Stress Test: проверка, насколько результат зависит от наблюдений,
// предпосылок, спецификации и случайной выборки. Все числа приходят с сервера;
// интерфейс ничего не досчитывает и не меняет данные.

type Section = "overview" | "diagnostics" | "comparison" | "sensitivity" | "methodology";

const CHECKS: { id: string; title: string; hint: string }[] = [
  {
    id: "diagnostics",
    title: "Предпосылки",
    hint: "VIF, Бреуш-Пеган, Уайт, остатки",
  },
  {
    id: "influence",
    title: "Влияние наблюдений",
    hint: "Cook's Distance, leverage, пересчёт без точек",
  },
  {
    id: "robust",
    title: "Робастные SE",
    hint: "HC0–HC3 и изменение значимости",
  },
  {
    id: "specifications",
    title: "Спецификации",
    hint: "без каждого предиктора, с контролями",
  },
  {
    id: "bootstrap",
    title: "Bootstrap",
    hint: "стабильность коэффициентов и интервалы",
  },
];

const SECTION_TITLES: Record<Section, string> = {
  overview: "Обзор",
  diagnostics: "Диагностика",
  comparison: "Сравнение",
  sensitivity: "Чувствительность",
  methodology: "Методология",
};

function fmt(value: number | null | undefined, digits = 3): string {
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
  return `${Math.round(value * 100)}%`;
}

function coefficientMap(scenario: StressScenario): Map<string, StressScenario["coefficients"][number]> {
  return new Map(scenario.coefficients.map((item) => [item.name, item]));
}

function coefficientNames(scenarios: StressScenario[]): string[] {
  const names: string[] = [];
  for (const scenario of scenarios) {
    for (const item of scenario.coefficients) {
      if (!names.includes(item.name)) names.push(item.name);
    }
  }
  return names;
}

export function StressTestView({ datasetId }: { datasetId: number }) {
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const variables = detail?.variables ?? [];
  const numeric = variables.filter((item) => item.type === "numeric");
  const scale = numeric.filter((item) => item.measure === "scale");
  const [target, setTarget] = useState("");
  const [predictors, setPredictors] = useState<string[]>([]);
  const [controls, setControls] = useState<string[]>([]);
  const [auto, setAuto] = useState(true);
  const [checks, setChecks] = useState<string[]>(CHECKS.map((item) => item.id));
  const [bootstrap, setBootstrap] = useState(500);
  const [seed, setSeed] = useState(42);
  const [confidence, setConfidence] = useState(0.95);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [report, setReport] = useState<StressReport | null>(null);
  const [section, setSection] = useState<Section>("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setLoadingDetail(true);
    setDetail(null);
    setTarget("");
    setPredictors([]);
    setControls([]);
    setReport(null);
    setError("");
    api
      .dataset(datasetId)
      .then((loaded) => {
        if (alive) setDetail(loaded);
      })
      .catch((problem) => {
        if (alive) {
          setError(problem instanceof ApiError ? problem.message : "Не удалось прочитать переменные");
        }
      })
      .finally(() => {
        if (alive) setLoadingDetail(false);
      });
    return () => {
      alive = false;
    };
  }, [datasetId]);

  const predictorsList = useMemo(
    () => (scale.length ? scale : numeric).filter((item) => item.name !== target),
    [numeric, scale, target],
  );
  const controlList = useMemo(
    () => numeric.filter((item) => item.name !== target && !predictors.includes(item.name)),
    [numeric, predictors, target],
  );

  function chooseTarget(name: string) {
    setTarget(name);
    const candidates = (scale.length ? scale : numeric).filter((item) => item.name !== name);
    setPredictors(candidates.slice(0, 4).map((item) => item.name));
    setControls([]);
    setReport(null);
  }

  function toggle(list: string[], name: string): string[] {
    return list.includes(name) ? list.filter((item) => item !== name) : [...list, name];
  }

  async function run() {
    setError("");
    if (!target) {
      setError("Выберите зависимую переменную");
      return;
    }
    if (!predictors.length) {
      setError("Выберите хотя бы один предиктор");
      return;
    }
    if (!auto && !checks.length) {
      setError("Выберите хотя бы одну проверку");
      return;
    }
    setBusy(true);
    try {
      const response = await api.stressTest(datasetId, {
        target,
        predictors,
        checks: auto ? [] : checks,
        auto,
        bootstrap: checks.includes("bootstrap") || auto ? bootstrap : 0,
        seed,
        confidence,
        alpha: 0.05,
        add_controls: controls,
      });
      setReport(response.report);
      setSection("overview");
      window.setTimeout(() => {
        document.querySelector(".stress-report-head")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 50);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Stress Test не выполнился");
    } finally {
      setBusy(false);
    }
  }

  if (loadingDetail) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">◇</span>
        <h2>Загружаем переменные…</h2>
      </div>
    );
  }

  return (
    <div className="stress-layout">
      <div className="card stress-head">
        <div>
          <div className="eyebrow">Research Stress Test</div>
          <h2>Насколько устойчив результат?</h2>
          <p className="muted">
            Проверьте, зависит ли модель от отдельных наблюдений, предпосылок,
            набора переменных и случайной выборки. Все альтернативы считаются
            заново; исходные данные не меняются.
          </p>
        </div>
        <span className="stress-badge">линейная регрессия · MVP</span>
      </div>

      <div className="card stress-form">
        <div className="stress-form-grid">
          <label>
            <span>Зависимая переменная</span>
            <select value={target} onChange={(event) => chooseTarget(event.target.value)}>
              <option value="">Выберите…</option>
              {numeric.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.display}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Повторов Bootstrap</span>
            <input
              type="number"
              min={0}
              max={2000}
              step={100}
              value={bootstrap}
              onChange={(event) => setBootstrap(Number(event.target.value))}
            />
          </label>
          <label>
            <span>Seed</span>
            <input
              type="number"
              min={0}
              max={2147483647}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
            />
          </label>
          <label>
            <span>Доверие</span>
            <select
              value={confidence}
              onChange={(event) => setConfidence(Number(event.target.value))}
            >
              <option value={0.9}>90%</option>
              <option value={0.95}>95%</option>
              <option value={0.99}>99%</option>
            </select>
          </label>
        </div>

        <div className="stress-predictors">
          <div className="stress-label">
            <strong>Предикторы</strong>
            <span className="muted small">
              числовые; по умолчанию выбраны количественные
            </span>
          </div>
          <div className="stress-chips">
            {predictorsList.map((item) => (
              <label key={item.name} className={`stress-chip${predictors.includes(item.name) ? " active" : ""}`}>
                <input
                  type="checkbox"
                  checked={predictors.includes(item.name)}
                  onChange={() => setPredictors((current) => toggle(current, item.name))}
                />
                {item.display}
              </label>
            ))}
            {!predictorsList.length && <span className="muted small">Нет числовых переменных</span>}
          </div>
        </div>

        <div className="stress-checks">
          <div className="stress-label">
            <strong>Проверки</strong>
            <label className="stress-auto">
              <input type="checkbox" checked={auto} onChange={(event) => setAuto(event.target.checked)} />
              Авто: подходящие проверки по данным
            </label>
          </div>
          <div className={`stress-check-grid${auto ? " disabled" : ""}`}>
            {CHECKS.map((item) => (
              <label key={item.id} className="stress-check">
                <input
                  type="checkbox"
                  checked={auto || checks.includes(item.id)}
                  disabled={auto}
                  onChange={() => setChecks((current) => toggle(current, item.id))}
                />
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.hint}</small>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="stress-advanced">
          <button type="button" className="ghost" onClick={() => setShowAdvanced((value) => !value)}>
            {showAdvanced ? "Скрыть контрольные переменные" : "Добавить контрольные переменные"}
          </button>
          {showAdvanced && (
            <div className="stress-chips" style={{ marginTop: 10 }}>
              {controlList.map((item) => (
                <label key={item.name} className={`stress-chip${controls.includes(item.name) ? " active" : ""}`}>
                  <input
                    type="checkbox"
                    checked={controls.includes(item.name)}
                    onChange={() => setControls((current) => toggle(current, item.name))}
                  />
                  {item.display}
                </label>
              ))}
              {!controlList.length && <span className="muted small">Нет доступных переменных</span>}
            </div>
          )}
        </div>

        <div className="stress-actions">
          <button type="button" onClick={() => void run()} disabled={busy || !target || !predictors.length}>
            {busy ? "Считаем…" : "Запустить Stress Test"}
          </button>
          <span className="muted small">
            {auto
              ? "Авто-режим выберет проверки по размеру выборки и числу предикторов."
              : "Ручной режим: отмеченные проверки."}
          </span>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {!report && !error && (
        <div className="card empty">
          <span className="empty-icon" aria-hidden="true">◇</span>
          <h2>Проверьте вывод, а не только p-value</h2>
          <p>
            Выберите зависимую переменную и предикторы. Stress Test пересчитает
            модель без влиятельных наблюдений, с робастными ошибками, без каждого
            предиктора и на Bootstrap-выборках — и покажет, где результат меняется.
          </p>
        </div>
      )}

      {report && (
        <>
          <div className="stress-report-head">
            <div>
              <span className="eyebrow">run #{report.run_id ?? "—"}</span>
              <h2>{report.target}</h2>
              <p className="muted small">
                {report.n_cases} наблюдений · предикторы: {report.predictors.join(", ")}
              </p>
            </div>
            <span className="stress-badge">{report.scenarios.length} сценариев</span>
          </div>

          <nav className="stress-sections" aria-label="Разделы Stress Test">
            {(Object.keys(SECTION_TITLES) as Section[]).map((key) => (
              <button
                key={key}
                type="button"
                className={section === key ? "active" : ""}
                aria-pressed={section === key}
                onClick={() => setSection(key)}
              >
                {SECTION_TITLES[key]}
              </button>
            ))}
          </nav>

          {section === "overview" && <Overview report={report} />}
          {section === "diagnostics" && <Diagnostics report={report} />}
          {section === "comparison" && <Comparison report={report} />}
          {section === "sensitivity" && <Sensitivity report={report} />}
          {section === "methodology" && <Methodology report={report} />}
        </>
      )}
    </div>
  );
}

function Overview({ report }: { report: StressReport }) {
  const { overview } = report;
  return (
    <div className="stress-overview">
      <div className="stress-stats">
        <Stat label="Наблюдений" value={String(overview.n)} hint="в исходной модели" />
        <Stat label="R²" value={fmt(overview.r_squared)} hint="исходная модель" />
        <Stat
          label="Знак сохранился"
          value={`${overview.same_sign} / ${overview.sign_checked}`}
          hint="во всех сценариях"
        />
        <Stat
          label="Значимость сохранилась"
          value={`${overview.same_significance} / ${overview.significance_checked}`}
          hint="p < 0,05"
        />
      </div>

      <div className="stress-two-col">
        <div className="card stress-card">
          <h3>Что показала проверка</h3>
          <ul className="stress-findings">
            {report.findings.map((item, index) => (
              <li key={`${item.text}-${index}`} className={`stress-finding ${item.kind}`}>
                <span className="stress-dot" aria-hidden="true" />
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="card stress-card">
          <h3>Сценарии</h3>
          <div className="stress-scenario-list">
            {report.scenarios.map((scenario) => (
              <div key={scenario.id} className="stress-scenario-row">
                <div>
                  <strong>{scenario.title}</strong>
                  <div className="muted small">{scenario.description}</div>
                </div>
                <span className="stress-scenario-n">N = {scenario.n}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card stress-card">
        <h3>Как читать</h3>
        <p className="muted">
          «Знак сохранился» — коэффициент не поменял направление во всех
          альтернативных моделях, где переменная осталась. «Значимость
          сохранилась» — p остался по ту же сторону от 0,05. Это проверка
          устойчивости, а не доказательство причинности.
        </p>
      </div>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="stress-stat">
      <span className="muted small">{label}</span>
      <strong>{value}</strong>
      <span className="muted small">{hint}</span>
    </div>
  );
}

function Diagnostics({ report }: { report: StressReport }) {
  const d = report.diagnostics;
  return (
    <div className="stress-diagnostics">
      <div className="stress-stats">
        <Stat label="VIF, максимум" value={fmt(d.max_vif, 2)} hint="> 10 — тревожно" />
        <Stat label="Бреуш-Пеган" value={pfmt(d.breusch_pagan_p)} hint="p; < 0,05 — гетероскедастичность" />
        <Stat label="Уайт" value={pfmt(d.white_p)} hint="p; более общий тест" />
        <Stat label="Дарбин-Уотсон" value={fmt(d.durbin_watson, 2)} hint="около 2 — норма" />
        <Stat label="Шапиро-Уилк" value={pfmt(d.shapiro_p)} hint="p остатков" />
        <Stat label="Cook, максимум" value={fmt(report.influence?.cooks_max, 3)} hint="влияние точек" />
      </div>

      <div className="stress-two-col">
        <div className="card stress-card">
          <h3>VIF по предикторам</h3>
          <table className="stress-table compact">
            <thead>
              <tr><th>Переменная</th><th>VIF</th><th>Статус</th></tr>
            </thead>
            <tbody>
              {Object.entries(d.vif).map(([name, value]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{fmt(value, 2)}</td>
                  <td>{value >= 10 ? "высокая" : value >= 5 ? "умеренная" : "норма"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card stress-card">
          <h3>Влияние наблюдений</h3>
          {report.influence ? (
            <dl className="stress-dl">
              <div><dt>Cook's Distance</dt><dd>{fmt(report.influence.cooks_max, 3)}</dd></div>
              <div><dt>Влиятельных</dt><dd>{report.influence.influential_count}</dd></div>
              <div><dt>Высокий leverage</dt><dd>{report.influence.leverage_count}</dd></div>
              <div><dt>Порог Cook</dt><dd>{report.influence.thresholds.cooks}</dd></div>
              <div><dt>Порог leverage</dt><dd>{report.influence.thresholds.leverage}</dd></div>
            </dl>
          ) : (
            <p className="muted">Проверка влияния не включена.</p>
          )}
          {report.influence?.influential_rows.length ? (
            <p className="muted small">
              Строки для просмотра: {report.influence.influential_rows.join(", ")}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Comparison({ report }: { report: StressReport }) {
  const names = coefficientNames(report.scenarios);
  const maps = new Map(report.scenarios.map((scenario) => [scenario.id, coefficientMap(scenario)]));
  return (
    <div className="stress-comparison">
      <div className="card stress-card">
        <h3>Модели и коэффициенты</h3>
        <p className="muted small">
          В ячейке — коэффициент и p-value. Красная рамка — знак или значимость
          отличаются от исходной модели.
        </p>
        <div className="stress-table-wrap">
          <table className="stress-table">
            <thead>
              <tr>
                <th>Переменная</th>
                {report.scenarios.map((scenario) => (
                  <th key={scenario.id}>
                    {scenario.title}
                    <small>N = {scenario.n}</small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {names.map((name) => (
                <tr key={name}>
                  <td>{name}</td>
                  {report.scenarios.map((scenario) => {
                    const item = maps.get(scenario.id)?.get(name);
                    if (!item) {
                      return <td key={scenario.id} className="stress-missing">—</td>;
                    }
                    const changed =
                      scenario.id !== "baseline" &&
                      (scenario.changes?.sign.includes(name) ||
                        scenario.changes?.significance.includes(name));
                    return (
                      <td key={scenario.id} className={changed ? "stress-changed" : ""}>
                        <strong>{fmt(item.b)}</strong>
                        <small>p = {pfmt(item.p)}</small>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card stress-card">
        <h3>Показатели моделей</h3>
        <table className="stress-table compact">
          <thead>
            <tr><th>Сценарий</th><th>N</th><th>R²</th><th>Скорр. R²</th><th>Сменили знак</th><th>Сменили значимость</th></tr>
          </thead>
          <tbody>
            {report.scenarios.map((scenario) => (
              <tr key={scenario.id}>
                <td>{scenario.title}</td>
                <td>{scenario.n}</td>
                <td>{fmt(scenario.r_squared)}</td>
                <td>{fmt(scenario.adj_r_squared)}</td>
                <td>{scenario.changes?.sign.length ?? 0}</td>
                <td>{scenario.changes?.significance.length ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card stress-card">
        <h3>Робастные стандартные ошибки</h3>
        <p className="muted small">HC0–HC3: те же коэффициенты, другая оценка SE.</p>
        <table className="stress-table compact">
          <thead>
            <tr><th>Тип</th><th>Переменная</th><th>b</th><th>SE</th><th>p</th><th>95% ДИ</th></tr>
          </thead>
          <tbody>
            {Object.entries(report.robust).flatMap(([kind, rows]) =>
              rows.filter((item) => item.name !== "(Константа)").map((item) => (
                <tr key={`${kind}-${item.name}`}>
                  <td>{kind}</td>
                  <td>{item.name}</td>
                  <td>{fmt(item.b)}</td>
                  <td>{fmt(item.se)}</td>
                  <td>{pfmt(item.p)}</td>
                  <td>[{fmt(item.ci_low)}; {fmt(item.ci_high)}]</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Sensitivity({ report }: { report: StressReport }) {
  return (
    <div className="stress-sensitivity">
      <div className="card stress-card">
        <h3>Сценарии выборки и спецификации</h3>
        <div className="stress-scenario-list">
          {report.scenarios.map((scenario) => (
            <div key={scenario.id} className="stress-scenario-row">
              <div>
                <strong>{scenario.title}</strong>
                <div className="muted small">{scenario.description}</div>
                {scenario.notes.map((note) => (
                  <div key={note} className="muted small">{note}</div>
                ))}
              </div>
              <div className="stress-scenario-metrics">
                <span>N = {scenario.n}</span>
                <span>R² = {fmt(scenario.r_squared)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {report.bootstrap && (
        <div className="card stress-card">
          <h3>Bootstrap: стабильность коэффициентов</h3>
          <p className="muted small">
            {report.bootstrap.valid} из {report.bootstrap.b} повторов · seed {report.bootstrap.seed}
          </p>
          <table className="stress-table compact">
            <thead>
              <tr><th>Переменная</th><th>Среднее</th><th>SD</th><th>95% ДИ</th><th>Доля знака</th><th>Доля p &lt; 0,05</th></tr>
            </thead>
            <tbody>
              {Object.entries(report.bootstrap.coefficients).map(([name, values]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{fmt(values.mean)}</td>
                  <td>{fmt(values.sd)}</td>
                  <td>[{fmt(values.ci_low)}; {fmt(values.ci_high)}]</td>
                  <td>{pct(values.sign_share)}</td>
                  <td>{pct(values.significance_share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="stress-histograms">
            {Object.entries(report.bootstrap.coefficients)
              .filter(([name]) => name !== "(Константа)")
              .map(([name, values]) => (
                <Histogram key={name} name={name} counts={values.histogram.counts} />
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Histogram({ name, counts }: { name: string; counts: number[] }) {
  const max = Math.max(1, ...counts);
  return (
    <div className="stress-hist">
      <span className="muted small">{name}</span>
      <div className="stress-hist-bars" aria-hidden="true">
        {counts.map((count, index) => (
          <span key={index} style={{ height: `${Math.max(2, (count / max) * 100)}%` }} />
        ))}
      </div>
    </div>
  );
}

function Methodology({ report }: { report: StressReport }) {
  const limitations = Array.isArray(report.methodology.limitations)
    ? (report.methodology.limitations as string[])
    : [];
  return (
    <div className="stress-methodology">
      <div className="card stress-card">
        <h3>Параметры прогона</h3>
        <dl className="stress-dl">
          <div><dt>Seed</dt><dd>{String(report.methodology.seed ?? "—")}</dd></div>
          <div><dt>Bootstrap</dt><dd>{String(report.methodology.bootstrap ?? "—")}</dd></div>
          <div><dt>Доверие</dt><dd>{pct(Number(report.methodology.confidence))}</dd></div>
          <div><dt>α</dt><dd>{String(report.methodology.alpha ?? "—")}</dd></div>
          <div><dt>Пропуски</dt><dd>{String(report.methodology.missing ?? "—")}</dd></div>
          <div><dt>Проверки</dt><dd>{(report.methodology.checks as string[] | undefined)?.join(", ") ?? "—"}</dd></div>
        </dl>
      </div>
      <div className="card stress-card">
        <h3>Метод</h3>
        <p className="muted">{String(report.methodology.method ?? "")}</p>
        <h4>Ограничения</h4>
        <ul className="stress-findings">
          {limitations.map((text) => (
            <li key={text} className="stress-finding note">
              <span className="stress-dot" aria-hidden="true" />
              <span>{text}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
