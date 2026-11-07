import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type FieldSpecOut,
  type ProcedureInfo,
  type ProcedureSchema,
  type RunResult,
  type Variable,
} from "./api";

// Экран «Процедуры»: список всех процедур и форма, собранная по описанию окна.
//
// Описания окон живут на сервере (procedure_specs.py) и те же самые, что в
// настольной версии. Поэтому правила проверки и разбор полей совпадают: новая
// процедура появляется в вебе без правки фронтенда.

export function ProcedureForm({
  datasetId,
  variables,
  theme,
  onReport,
}: {
  datasetId: number;
  variables: Variable[];
  theme: "dark" | "light";
  onReport: (report: RunResult, request: Record<string, unknown>) => void;
}) {
  const [list, setList] = useState<ProcedureInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [schema, setSchema] = useState<ProcedureSchema | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [splitBy, setSplitBy] = useState("");
  const [weight, setWeight] = useState("");

  useEffect(() => {
    api
      .procedures()
      .then(setList)
      .catch((problem) =>
        setError(problem instanceof ApiError ? problem.message : "Ошибка соединения"),
      );
  }, []);

  useEffect(() => {
    if (!selected) {
      setSchema(null);
      return;
    }
    setError("");
    api
      .procedure(selected)
      .then((loaded) => {
        setSchema(loaded);
        const initial: Record<string, unknown> = {};
        for (const field of loaded.fields) {
          initial[field.name] =
            field.default ?? (field.kind === "variable_list" ? [] : "");
        }
        setValues(initial);
      })
      .catch((problem) =>
        setError(problem instanceof ApiError ? problem.message : "Ошибка соединения"),
      );
  }, [selected]);

  // eslint-disable-next-line react-hooks/rules-of-hooks
  const byFilter = useMemo(() => {
    const numeric = variables.filter((item) => item.type === "numeric");
    // Категории в анкетах часто закодированы числами (пол 1/2, образование 1..5),
    // поэтому в полях «категориальная» показываются все переменные: непригодную
    // отклонит движок с понятным текстом, а спрятанная выглядит как поломка.
    const categorical = variables;
    return { any: variables, numeric, categorical };
  }, [variables]);

  function candidates(field: FieldSpecOut): Variable[] {
    if (field.filter === "numeric") return byFilter.numeric;
    if (field.filter === "categorical") return byFilter.categorical;
    return byFilter.any;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!schema) return;
    setRunning(true);
    setError("");
    try {
      // Разбиение и веса действуют на этот расчёт и не сохраняются в набор:
      // иначе включённое однажды разбиение меняло бы все следующие отчёты.
      const options: Record<string, unknown> = { theme };
      if (splitBy) options.split_by = splitBy;
      if (weight) options.weight = weight;
      const report = await api.run(datasetId, schema.key, values, options);
      onReport(report, { procedure: schema.key, values, ...options });
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось выполнить расчёт");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 880 }}>
      <div className="card" style={{ padding: 16 }}>
        <label htmlFor="procedure" style={{ fontWeight: 600, fontSize: 13 }}>
          Процедура
        </label>
        <select
          id="procedure"
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          style={{
            width: "100%",
            marginTop: 6,
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid var(--border)",
            font: "inherit",
            background: "var(--field-bg)",
          }}
        >
          <option value="">— выберите процедуру —</option>
          {list.map((item) => (
            <option key={item.key} value={item.key} disabled={!item.allowed}>
              {item.title}
              {item.allowed ? "" : " (недоступно в вебе)"}
            </option>
          ))}
        </select>
        {schema?.description && (
          <p className="muted small" style={{ marginBottom: 0 }}>
            {schema.description}
          </p>
        )}
      </div>

      {schema && (
        <form className="card" style={{ padding: 16 }} onSubmit={submit}>
          {schema.fields.map((field) => (
            <Field
              key={field.name}
              field={field}
              value={values[field.name]}
              candidates={candidates(field)}
              onChange={(next) => setValues((current) => ({ ...current, [field.name]: next }))}
            />
          ))}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
              margin: "4px 0 12px",
              borderTop: "1px solid var(--border)",
              paddingTop: 12,
            }}
          >
            <div>
              <label
                htmlFor="split-by"
                style={{ fontWeight: 600, fontSize: 13, display: "block", marginBottom: 4 }}
              >
                Считать по группам
              </label>
              <select
                id="split-by"
                value={splitBy}
                onChange={(event) => setSplitBy(event.target.value)}
                style={{
                  width: "100%",
                  padding: "9px 11px",
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  font: "inherit",
                  background: "var(--field-bg)",
                }}
              >
                <option value="">— все случаи вместе —</option>
                {byFilter.categorical.map((variable) => (
                  <option key={variable.name} value={variable.name}>
                    {variable.display}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="weight-var"
                style={{ fontWeight: 600, fontSize: 13, display: "block", marginBottom: 4 }}
              >
                Веса случаев
              </label>
              <select
                id="weight-var"
                value={weight}
                onChange={(event) => setWeight(event.target.value)}
                style={{
                  width: "100%",
                  padding: "9px 11px",
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  font: "inherit",
                  background: "var(--field-bg)",
                }}
              >
                <option value="">— без весов —</option>
                {byFilter.numeric.map((variable) => (
                  <option key={variable.name} value={variable.name}>
                    {variable.display}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {error && (
            <div className="error" style={{ marginBottom: 12 }}>
              {error}
            </div>
          )}
          <button type="submit" disabled={running}>
            {running ? "Считаем…" : "Выполнить"}
          </button>
        </form>
      )}

      {!schema && error && <div className="error">{error}</div>}
    </div>
  );
}


//: Какие переменные показывать в поле: тем же правилом, что в настольной версии.
export function candidatesFor(field: FieldSpecOut, variables: Variable[]): Variable[] {
  if (field.filter === "numeric") {
    return variables.filter((item) => item.type === "numeric");
  }
  if (field.filter === "categorical") {
    // Показываются все переменные: в анкетах категории часто закодированы
    // числами (пол 1/2, образование 1..5), и отбор «только nominal» скрывал бы
    // их почти целиком. Непригодную переменную отклонит сам движок с понятным
    // текстом, а спрятанная переменная выглядит как поломка интерфейса.
    return variables;
  }
  return variables;
}

export function Field({
  field,
  value,
  candidates,
  onChange,
}: {
  field: FieldSpecOut;
  value: unknown;
  candidates: Variable[];
  onChange: (next: unknown) => void;
}) {
  if (field.kind === "variable_list") {
    const chosen = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="field">
        <label>{field.label}</label>
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: 10,
            maxHeight: 180,
            overflowY: "auto",
            padding: "6px 8px",
          }}
        >
          {candidates.length === 0 && <span className="muted small">Нет подходящих переменных</span>}
          {candidates.map((variable) => (
            <label
              key={variable.name}
              style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 0" }}
            >
              <input
                type="checkbox"
                checked={chosen.includes(variable.name)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...chosen, variable.name]
                    : chosen.filter((name) => name !== variable.name);
                  onChange(next);
                }}
                style={{ width: "auto" }}
              />
              <span className="small">{variable.display}</span>
            </label>
          ))}
        </div>
      </div>
    );
  }

  if (field.kind === "single") {
    return (
      <div className="field">
        <label>{field.label}</label>
        <select
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value || null)}
          style={{
            width: "100%",
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid var(--border)",
            font: "inherit",
            background: "var(--field-bg)",
          }}
        >
          <option value="">(не выбрано)</option>
          {candidates.map((variable) => (
            <option key={variable.name} value={variable.name}>
              {variable.display}
            </option>
          ))}
        </select>
      </div>
    );
  }

  if (field.kind === "choice") {
    return (
      <div className="field">
        <label>{field.label}</label>
        <select
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
          style={{
            width: "100%",
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid var(--border)",
            font: "inherit",
            background: "var(--field-bg)",
          }}
        >
          {field.choices.map((choice) => (
            <option key={String(choice.value)} value={String(choice.value)}>
              {choice.label}
            </option>
          ))}
        </select>
      </div>
    );
  }

  if (field.kind === "checkbox") {
    return (
      <div className="field">
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(event.target.checked)}
            style={{ width: "auto" }}
          />
          {field.label}
        </label>
      </div>
    );
  }

  if (field.kind === "option") {
    const chosen = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="field">
        <label>{field.label}</label>
        {field.choices.map((choice) => (
          <label
            key={String(choice.value)}
            style={{ display: "flex", gap: 8, alignItems: "center", padding: "2px 0" }}
          >
            <input
              type="checkbox"
              checked={chosen.includes(String(choice.value))}
              onChange={(event) => {
                const next = event.target.checked
                  ? [...chosen, String(choice.value)]
                  : chosen.filter((item) => item !== String(choice.value));
                onChange(next);
              }}
              style={{ width: "auto" }}
            />
            <span className="small">{choice.label}</span>
          </label>
        ))}
      </div>
    );
  }

  if (field.kind === "number") {
    return (
      <div className="field">
        <label>{field.label}</label>
        <input
          type="number"
          value={Number(value ?? 0)}
          min={field.min}
          max={field.max}
          step={field.step}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      </div>
    );
  }

  return (
    <div className="field">
      <label>{field.label}</label>
      <input
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        placeholder={field.tooltip}
      />
    </div>
  );
}
