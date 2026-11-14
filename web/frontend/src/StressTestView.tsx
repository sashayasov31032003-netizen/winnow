import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type AnalysisSummary,
  type DatasetDetail,
  type StressChallenge,
  type StressReport,
  type StressScenario,
} from "./api";

// Research Stress Test: проверка, насколько результат зависит от наблюдений,
// предпосылок, спецификации и случайной выборки. Все числа приходят с сервера;
// интерфейс ничего не досчитывает и не меняет данные.

type Section = "overview" | "diagnostics" | "comparison" | "sensitivity" | "challenge" | "methodology";

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
  challenge: "Challenge",
  methodology: "Методология",
};

const CHALLENGE_STATUS: Record<string, string> = {
  supported: "сохраняется",
  fragile: "частично",
  contradicted: "противоречит",
  insufficient: "недостаточно данных",
};

const CHALLENGE_CHECK_STATUS: Record<string, string> = {
  supported: "сохраняется",
  weakens: "ослабевает",
  contradicts: "противоречит",
  not_tested: "не проверено",
};

const CHECK_TITLES: Record<string, string> = {
  diagnostics: "предпосылки",
  influence: "влияние наблюдений",
  robust: "робастные SE",
  specifications: "спецификации",
  sensitivity: "чувствительность",
  bootstrap: "Bootstrap",
};

const MISSING_TITLES: Record<string, string> = {
  complete_case: "строки с пропусками исключены",
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

function parseRowNumbers(value: string): number[] {
  const numbers = new Set<number>();
  const parts = value.split(/[\s,;]+/).filter(Boolean);
  for (const part of parts) {
    const match = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!match) throw new Error(`Не понял номер строки: «${part}»`);
    const first = Number(match[1]);
    const last = match[2] ? Number(match[2]) : first;
    if (first < 1 || last < first) {
      throw new Error(`Неверный диапазон строк: «${part}»`);
    }
    if (last - first > 5000) throw new Error("Слишком большой диапазон строк");
    for (let row = first; row <= last; row += 1) numbers.add(row);
  }
  return [...numbers].sort((left, right) => left - right);
}

function dateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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
  const [challengeOn, setChallengeOn] = useState(false);
  const [hypothesis, setHypothesis] = useState("");
  const [focal, setFocal] = useState("");
  const [direction, setDirection] = useState<"positive" | "negative">("positive");
  const [challengeControls, setChallengeControls] = useState<string[]>([]);
  const [excludeRows, setExcludeRows] = useState("");
  const [runs, setRuns] = useState<AnalysisSummary[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
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
    setChallengeOn(false);
    setHypothesis("");
    setFocal("");
    setChallengeControls([]);
    setExcludeRows("");
    setReport(null);
    setError("");
    void refreshRuns();
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId]);

  async function refreshRuns() {
    setLoadingRuns(true);
    try {
      const response = await api.stressRuns(datasetId);
      setRuns(response.runs);
    } catch {
      // История не должна мешать основному отчёту.
    } finally {
      setLoadingRuns(false);
    }
  }

  const predictorsList = useMemo(
    () => (scale.length ? scale : numeric).filter((item) => item.name !== target),
    [numeric, scale, target],
  );
  const controlList = useMemo(
    () => numeric.filter((item) => item.name !== target && !predictors.includes(item.name)),
    [numeric, predictors, target],
  );
  const challengeFocal = predictors.includes(focal) ? focal : predictors[0] ?? "";
  const challengeControlList = useMemo(
    () =>
      numeric.filter(
        (item) =>
          item.name !== target &&
          item.name !== challengeFocal &&
          !predictors.includes(item.name),
      ),
    [challengeFocal, numeric, predictors, target],
  );
  const excludedCount = useMemo(() => {
    try {
      return parseRowNumbers(excludeRows).length;
    } catch {
      return null;
    }
  }, [excludeRows]);

  function chooseTarget(name: string) {
    setTarget(name);
    const candidates = (scale.length ? scale : numeric).filter((item) => item.name !== name);
    const names = candidates.slice(0, 4).map((item) => item.name);
    setPredictors(names);
    setFocal(names[0] ?? "");
    setControls([]);
    setChallengeControls([]);
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
    if (challengeOn) {
      if (!hypothesis.trim()) {
        setError("Сформулируйте гипотезу для Research Challenge");
        return;
      }
      if (!challengeFocal) {
        setError("Выберите фокус-предиктор гипотезы");
        return;
      }
    }
    let excluded: number[] = [];
    try {
      excluded = parseRowNumbers(excludeRows);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Неверные номера строк");
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
        exclude_rows: excluded,
        challenge: challengeOn
          ? {
              hypothesis: hypothesis.trim(),
              focal: challengeFocal,
              direction,
              controls: challengeControls.filter(
                (name) => name !== challengeFocal && !predictors.includes(name),
              ),
            }
          : null,
      });
      setReport(response.report);
      setSection("overview");
      void refreshRuns();
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

  async function loadRun(runId: number) {
    setError("");
    try {
      const response = await api.stressTestRun(runId);
      setReport(response.run.payload);
      setSection("overview");
      window.setTimeout(() => {
        document.querySelector(".stress-report-head")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 50);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось открыть прогон");
    }
  }

  async function download(format: "html" | "docx" | "xlsx") {
    if (!report?.run_id) return;
    setError("");
    try {
      const blob = await api.stressExport(report.run_id, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `winnow-stress-test-${report.run_id}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось выгрузить отчёт");
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

        <div className="stress-exclude">
          <label>
            <span>Исключить конкретные строки</span>
            <input
              value={excludeRows}
              onChange={(event) => setExcludeRows(event.target.value)}
              placeholder="Например: 3, 17, 20-25"
            />
          </label>
          <span className="muted small">
            Номера как в таблице «Данные» (1-based).{" "}
            {excludedCount === null
              ? "Проверьте формат."
              : excludedCount
                ? `Будет исключено: ${excludedCount}.`
                : "Пока ничего не исключено."}
          </span>
        </div>

        <div className="stress-challenge-form">
          <label className="stress-auto">
            <input
              type="checkbox"
              checked={challengeOn}
              onChange={(event) => setChallengeOn(event.target.checked)}
            />
            Research Challenge: проверить гипотезу
          </label>
          {challengeOn && (
            <div className="stress-challenge-fields">
              <label>
                <span>Гипотеза</span>
                <textarea
                  rows={2}
                  value={hypothesis}
                  onChange={(event) => setHypothesis(event.target.value)}
                  placeholder="Например: уровень образования положительно связан с доходом"
                />
              </label>
              <div className="stress-form-grid challenge-grid">
                <label>
                  <span>Фокус-предиктор</span>
                  <select value={challengeFocal} onChange={(event) => setFocal(event.target.value)}>
                    {predictors.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Ожидаемое направление</span>
                  <select
                    value={direction}
                    onChange={(event) => setDirection(event.target.value as "positive" | "negative")}
                  >
                    <option value="positive">положительное (+)</option>
                    <option value="negative">отрицательное (−)</option>
                  </select>
                </label>
              </div>
              <div>
                <span className="muted small">Контрольные переменные для гипотезы</span>
                <div className="stress-chips" style={{ marginTop: 6 }}>
                  {challengeControlList.map((item) => (
                    <label key={item.name} className={`stress-chip${challengeControls.includes(item.name) ? " active" : ""}`}>
                      <input
                        type="checkbox"
                        checked={challengeControls.includes(item.name)}
                        onChange={() => setChallengeControls((current) => toggle(current, item.name))}
                      />
                      {item.display}
                    </label>
                  ))}
                  {!challengeControlList.length && (
                    <span className="muted small">Нет свободных числовых переменных</span>
                  )}
                </div>
              </div>
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

      {runs.length > 0 && (
        <div className="card stress-history">
          <div className="stress-history-head">
            <strong>Сохранённые прогоны</strong>
            <span className="muted small">
              {loadingRuns ? "Обновляем…" : `${runs.length} на этом наборе`}
            </span>
          </div>
          <div className="stress-history-list">
            {runs.slice(0, 10).map((item) => (
              <button
                key={item.run_id}
                type="button"
                className="stress-history-item"
                onClick={() => void loadRun(item.run_id)}
              >
                <span>
                  <strong>#{item.run_id}</strong> · {item.title}
                </span>
                <span className="muted small">{dateLabel(item.created_at)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

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
            <div className="stress-report-actions">
              <span className="stress-badge">{report.scenarios.length} сценариев</span>
              {report.run_id && (
                <div className="stress-export">
                  {(["html", "docx", "xlsx"] as const).map((format) => (
                    <button
                      key={format}
                      type="button"
                      className="ghost small-button"
                      onClick={() => void download(format)}
                    >
                      {format === "docx" ? "Word" : format === "xlsx" ? "Excel" : "HTML"}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <nav className="stress-sections" aria-label="Разделы Stress Test">
            {(Object.keys(SECTION_TITLES) as Section[])
              .filter((key) => key !== "challenge" || report.challenge)
              .map((key) => (
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
          {section === "challenge" && report.challenge && <Challenge report={report.challenge} />}
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

      {report.challenge && (
        <div className="card stress-card challenge-banner">
          <div>
            <span className="muted small">Research Challenge</span>
            <strong>{report.challenge.hypothesis}</strong>
          </div>
          <span className={`challenge-status ${report.challenge.status}`}>
            {CHALLENGE_STATUS[report.challenge.status] ?? report.challenge.status}
          </span>
        </div>
      )}
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
  const ciLabel = `${Math.round(Number(report.config.confidence) * 100)}% ДИ`;
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
            <tr><th>Тип</th><th>Переменная</th><th>b</th><th>SE</th><th>p</th><th>{ciLabel}</th></tr>
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
  const ciLabel = `${Math.round(Number(report.config.confidence) * 100)}% ДИ`;
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
              <tr><th>Переменная</th><th>Среднее</th><th>SD</th><th>{ciLabel}</th><th>Доля знака</th><th>Доля p &lt; 0,05</th></tr>
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

function Challenge({ report }: { report: StressChallenge }) {
  return (
    <div className="stress-challenge">
      <div className="card stress-card challenge-head">
        <div>
          <span className="eyebrow">Research Challenge</span>
          <h3>{report.hypothesis}</h3>
          <p className="muted small">
            {report.focal} · ожидаемое направление:{" "}
            {report.direction === "positive" ? "положительное" : "отрицательное"}
            {report.controls.length ? ` · контроль: ${report.controls.join(", ")}` : " · без контроля"}
          </p>
        </div>
        <span className={`challenge-status ${report.status}`}>
          {CHALLENGE_STATUS[report.status] ?? report.status}
        </span>
      </div>

      <div className="card stress-card">
        <h3>Вывод</h3>
        <p className="muted">{report.summary}</p>
      </div>

      <div className="card stress-card">
        <h3>Проверки гипотезы</h3>
        <table className="stress-table compact">
          <thead>
            <tr><th>Проверка</th><th>Статус</th><th>b</th><th>p</th><th>Комментарий</th></tr>
          </thead>
          <tbody>
            {report.checks.map((item) => (
              <tr key={item.id}>
                <td>{item.title}</td>
                <td>
                  <span className={`challenge-check-status ${item.status}`}>
                    {CHALLENGE_CHECK_STATUS[item.status] ?? item.status}
                  </span>
                </td>
                <td>{fmt(item.b)}</td>
                <td>{pfmt(item.p)}</td>
                <td className="challenge-note">{item.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted small">
        Research Challenge проверяет, сохраняется ли направление связи в
        альтернативных расчётах. Он не доказывает причинность и не заменяет
        пререгистрацию гипотезы.
      </p>
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
          <div><dt>Пропуски</dt><dd>{MISSING_TITLES[String(report.methodology.missing)] ?? String(report.methodology.missing ?? "—")}</dd></div>
          <div>
            <dt>Проверки</dt>
            <dd>
              {(report.methodology.checks as string[] | undefined)
                ?.map((item) => CHECK_TITLES[item] ?? item)
                .join(", ") ?? "—"}
            </dd>
          </div>
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
