import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type ProcedureSchema,
  type Variable,
} from "./api";
import { Field, candidatesFor } from "./ProcedureForm";

// Экран «Графики»: форма собирается по описанию окна графика, картинку рисует
// сервер и отдаёт готовым SVG - так формулы остаются в одном месте (движке), и
// график выглядит одинаково в браузере и в выгрузке.

export function ChartView({
  datasetId,
  variables,
  theme,
}: {
  datasetId: number;
  variables: Variable[];
  theme: "dark" | "light";
}) {
  const [schema, setSchema] = useState<ProcedureSchema | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [svg, setSvg] = useState("");
  const [caption, setCaption] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [built, setBuilt] = useState(false);

  useEffect(() => {
    api
      .procedure("graph")
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
  }, []);

  async function build(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const chart = await api.chart(datasetId, values, theme);
      setSvg(chart.svg);
      setCaption(chart.caption);
      setBuilt(true);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось построить график");
      setSvg("");
    } finally {
      setBusy(false);
    }
  }

  // Тема входит в сам рисунок, поэтому при переключении темы график
  // перестраивается: иначе на тёмном экране оставался бы белый рисунок.
  useEffect(() => {
    if (!built) return;
    let alive = true;
    api
      .chart(datasetId, values, theme)
      .then((chart) => {
        if (!alive) return;
        setSvg(chart.svg);
        setCaption(chart.caption);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  if (!schema) {
    return (
      <div className="card empty">
        {error || "Готовим форму графика…"}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 880 }}>
      <form className="card" style={{ padding: 16 }} onSubmit={build}>
        {schema.fields.map((field) => (
          <Field
            key={field.name}
            field={field}
            value={values[field.name]}
            candidates={candidatesFor(field, variables)}
            onChange={(next) => setValues((current) => ({ ...current, [field.name]: next }))}
          />
        ))}
        {error && (
          <div className="error" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Рисуем…" : "Построить график"}
        </button>
      </form>

      {svg && (
        <div className="card" style={{ padding: 12, overflow: "hidden" }}>
          <div dangerouslySetInnerHTML={{ __html: svg }} />
          {caption && (
            <p className="muted small" style={{ margin: "6px 4px 0" }}>
              {caption}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
