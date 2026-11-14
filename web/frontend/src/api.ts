// Клиент API Winnow.
//
// Запросы идут с credentials: "include" - сессия живёт в httpOnly-cookie, и без
// этого флага браузер не приложит её к запросу. Токены в localStorage не
// используются намеренно: их можно украсть скриптом со страницы.

export type User = { id: number; email: string };

export type DatasetSummary = {
  id: number;
  name: string;
  original_filename: string;
  n_cases: number;
  n_variables: number;
  ai_full_access: boolean;
  created_at: string;
};

export type Variable = {
  name: string;
  label: string;
  display: string;
  type: string;
  measure: string;
  measure_ru: string;
  n_unique: number;
  n_missing: number;
};

export type DatasetDetail = DatasetSummary & { variables: Variable[] };

export type Preview = {
  columns: string[];
  rows: Record<string, unknown>[];
  limit: number;
  offset: number;
  total: number;
};

export type CellEdit = { row: number; column: string; value: string };

export type EditResult = Preview & { changed: number };

export type Scenario = {
  key: string;
  title: string;
  question: string;
  why: string;
  procedure: string;
  params: Record<string, unknown>;
  roles: Record<string, string>;
  confidence: string;
  caveats: string[];
};

export type Scenarios = {
  cases: number;
  variables: number;
  notes: string[];
  scenarios: Scenario[];
};

export type RunResult = {
  procedure: string;
  title: string;
  html: string;
  conclusions: { kind: string; text: string }[];
  n_tables: number;
  warnings: string[];
};

export type ProcedureInfo = {
  key: string;
  title: string;
  description: string;
  allowed: boolean;
};

export type FieldSpecOut = {
  name: string;
  label: string;
  kind: string;
  filter: string;
  default: unknown;
  choices: { label: string; value: unknown }[];
  min: number;
  max: number;
  step: number;
  decimals: number;
  tooltip: string;
  row: number;
  column: number;
};

export type ProcedureSchema = ProcedureInfo & { fields: FieldSpecOut[] };

// ------------------------------------------------------- исследование AI

export type AIConfig = {
  enabled: boolean;
  provider: string;
  model: string;
  models: string[];
  daily_limit: number;
  used_today: number;
  remaining: number;
  data_policy: string;
  note: string;
};

export type AITableColumn = {
  label: string;
  key?: string;
  decimals?: number | null;
  suffix?: string;
  align?: string;
};

export type AITable = {
  title: string;
  number?: number | null;
  columns: AITableColumn[];
  rows: (string | number | null)[][];
  footnotes?: string[];
};

export type AIFinding = { kind: string; text: string; source?: string; group?: string };

export type AnalysisPayload = {
  run_id: number | null;
  procedure: string;
  title: string;
  dataset: { name: string; revision: string; n_cases: number };
  tables: AITable[];
  findings: AIFinding[];
  warnings: string[];
  notes: string[];
  syntax: string;
};

export type AnalysisDetail = {
  run_id: number;
  dataset_id: number;
  dataset_revision: string;
  procedure: string;
  title: string;
  created_at: string;
  payload: AnalysisPayload;
};

export type AnalysisSummary = {
  run_id: number;
  dataset_id: number;
  procedure: string;
  title: string;
  dataset_revision: string;
  created_at: string;
};

// ---------------------------------------------------- качество данных

export type QualitySeverity = "critical" | "warning" | "note";

export type QualityIssue = {
  code: string;
  severity: QualitySeverity;
  title: string;
  details: string;
  variables: string[];
  values: Record<string, unknown>;
};

export type QualityVariable = {
  name: string;
  label: string;
  role: string;
  type: string;
  measure: string;
  n: number;
  n_missing: number;
  missing_share: number;
  n_unique: number;
  n_outliers: number;
  outlier_share: number;
  skewness: number | null;
  is_normal: boolean | null;
  is_identifier: boolean;
  is_constant: boolean;
  is_binary: boolean;
};

export type QualityRegression = {
  target: string;
  predictors: string[];
  n: number;
  n_predictors: number;
  r_squared: number;
  adj_r_squared: number;
  max_vif: number;
  vif: Record<string, number>;
  breusch_pagan_p: number | null;
  breusch_pagan_lm: number | null;
  durbin_watson: number;
  cooks_max: number;
  influential_count: number;
  leverage_count: number;
  residual_normality_p: number | null;
  condition_index: number;
  n_per_predictor: number;
};

export type QualityReport = {
  n_cases: number;
  n_variables: number;
  complete_rows: number;
  missing_cells: number;
  missing_share: number;
  duplicate_rows: number;
  duplicate_share: number;
  counts: Record<QualitySeverity, number>;
  variables: QualityVariable[];
  issues: QualityIssue[];
  correlated: { a: string; b: string; r: number }[];
  regression: QualityRegression | null;
  target: string | null;
  predictors: string[];
};

// ---------------------------------------------------- устойчивость

export type StressCoefficient = {
  name: string;
  b: number;
  se: number;
  t: number;
  p: number;
  ci_low: number;
  ci_high: number;
  significant: boolean;
  direction: "positive" | "negative" | "zero";
};

export type StressScenario = {
  id: string;
  title: string;
  description: string;
  kind: string;
  n: number;
  coefficients: StressCoefficient[];
  r_squared: number | null;
  adj_r_squared: number | null;
  f_p_value: number | null;
  notes: string[];
  changes?: {
    sign: string[];
    significance: string[];
    missing: string[];
  };
};

export type StressDiagnostics = {
  vif: Record<string, number>;
  max_vif: number;
  breusch_pagan_p: number | null;
  breusch_pagan_lm: number | null;
  white_p: number | null;
  white_lm: number | null;
  durbin_watson: number | null;
  shapiro_p: number | null;
  condition_index: number | null;
  n: number;
};

export type StressInfluence = {
  cooks_max: number;
  influential_count: number;
  leverage_count: number;
  influential_rows: number[];
  leverage_rows: number[];
  thresholds: { cooks: string; leverage: string };
};

export type StressBootstrapValue = {
  mean: number | null;
  sd: number | null;
  ci_low: number | null;
  ci_high: number | null;
  sign_share: number | null;
  significance_share: number | null;
  histogram: { counts: number[]; edges: number[] };
  n: number;
};

export type StressBootstrap = {
  b: number;
  valid: number;
  seed: number;
  coefficients: Record<string, StressBootstrapValue>;
  notes: string[];
};

export type StressOverview = {
  n: number;
  r_squared: number;
  scenarios: number;
  sign_checked: number;
  same_sign: number;
  significance_checked: number;
  same_significance: number;
  robust_checked: number;
  robust_changes: number;
  bootstrap_unstable: string[];
};

export type StressFinding = {
  kind: string;
  text: string;
  source: string;
};

export type StressChallengeCheck = {
  id: string;
  title: string;
  status: "supported" | "weakens" | "contradicts" | "not_tested";
  b: number | null;
  p: number | null;
  ci_low: number | null;
  ci_high: number | null;
  significant: boolean | null;
  note: string;
  details: Record<string, unknown>[];
};

export type StressChallenge = {
  hypothesis: string;
  focal: string;
  direction: "positive" | "negative";
  controls: string[];
  status: "supported" | "fragile" | "contradicted" | "insufficient";
  summary: string;
  checks: StressChallengeCheck[];
  findings: StressFinding[];
};

export type StressReport = {
  run_id: number | null;
  target: string;
  predictors: string[];
  config: Record<string, unknown>;
  n_cases: number;
  overview: StressOverview;
  baseline: StressScenario;
  diagnostics: StressDiagnostics;
  influence: StressInfluence | null;
  robust: Record<string, StressCoefficient[]>;
  scenarios: StressScenario[];
  bootstrap: StressBootstrap | null;
  challenge: StressChallenge | null;
  findings: StressFinding[];
  methodology: Record<string, unknown>;
};

export type StressRequest = {
  target: string;
  predictors: string[];
  checks: string[];
  auto: boolean;
  bootstrap: number;
  seed: number;
  confidence: number;
  alpha: number;
  add_controls: string[];
  exclude_rows: number[];
  challenge: {
    hypothesis: string;
    focal: string;
    direction: "positive" | "negative";
    controls: string[];
  } | null;
};

// ---------------------------------------------------- карта взаимосвязей

export type RelationshipGroup = "scale" | "ordinal" | "nominal" | "other";

export type RelationshipNode = {
  id: string;
  name: string;
  label: string;
  display: string;
  type: string;
  measure: string;
  group: RelationshipGroup;
  group_label: string;
  n: number;
  n_missing: number;
  n_unique: number;
  available: boolean;
  reason: string;
  degree: number;
  significant_degree: number;
  recommendations: string[];
};

export type RelationshipEdge = {
  id: string;
  source: string;
  target: string;
  method: string;
  method_label: string;
  kind: "numeric" | "categorical" | "mixed";
  statistic: number;
  strength: number;
  p: number | null;
  q: number | null;
  n: number;
  direction: "positive" | "negative" | "none";
  significant: boolean;
  warning: string;
  rows?: number;
  columns?: number;
  groups?: number;
  eta_squared?: number;
};

export type RelationshipMap = {
  dataset_revision: string;
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
  summary: {
    n_nodes: number;
    n_available: number;
    n_edges: number;
    n_significant: number;
    n_strong: number;
    n_potential_collinearity: number;
    method: string;
    strongest: RelationshipEdge[];
    most_connected: {
      name: string;
      display: string;
      degree: number;
      significant_degree: number;
    }[];
    recommendations: string[];
    truncated: boolean;
    total_variables: number;
  };
  methodology: Record<string, unknown>;
};

export type AIRunSummary = {
  run_id: number | null;
  procedure: string;
  title: string;
  n_tables: number;
  warnings: string[];
};

export type AIToolEvent = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  ok?: boolean;
  run_id?: number | null;
  error?: string;
  duration_ms?: number;
};

export type AIEvent =
  | { type: "start"; conversation_id: number; model: string; provider: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      type: "tool_result";
      id: string;
      name: string;
      ok: boolean;
      run_id?: number | null;
      error?: string;
      duration_ms?: number;
    }
  | {
      type: "run";
      run_id: number;
      procedure: string;
      title: string;
      n_tables: number;
      warnings: string[];
    }
  | { type: "warning"; message: string }
  | { type: "text"; text: string }
  | {
      type: "done";
      conversation_id: number;
      model: string;
      steps: number;
      runs: AIRunSummary[];
      warnings: string[];
    }
  | { type: "error"; message: string };

// ------------------------------------------------------------------ опросы
//
// Типы повторяют ответы /api/surveys и /api/public/surveys: один и тот же
// вопрос описывается одинаково в конструкторе и в публичной форме, поэтому
// предпросмотр - это тот же компонент, что видит респондент.

export type SurveyStatus = "draft" | "open" | "closed";

export type SurveyChoice = { id: string; label: string };

export type SurveyQuestion = {
  id?: number;
  position: number;
  kind: "single" | "multi" | "number" | "scale" | "text";
  kind_title?: string;
  text: string;
  required: boolean;
  choices: SurveyChoice[];
  min: number | null;
  max: number | null;
  unit?: string;
  max_length: number | null;
};

export type SurveySummary = {
  id: number;
  title: string;
  status: SurveyStatus;
  stored_status: SurveyStatus;
  slug: string;
  allow_multiple: boolean;
  n_questions: number;
  n_responses: number;
  created_at: string;
  closes_at: string | null;
};

export type SurveyDetail = SurveySummary & {
  description: string;
  questions: SurveyQuestion[];
  can_edit: boolean;
};

export type SurveyInput = {
  title: string;
  description: string;
  allow_multiple: boolean;
  closes_at: string | null;
  questions: Record<string, unknown>[];
};

export type PublicSurvey = {
  title: string;
  description: string;
  slug: string;
  status: SurveyStatus;
  allow_multiple: boolean;
  questions: SurveyQuestion[];
  already_answered: boolean;
};

export type AnswerInput = {
  question_id: number;
  option_ids?: string[];
  value_number?: number;
  value_text?: string;
};

export type SavedResponse = {
  id: number;
  submitted_at: string;
  answers: { question_id: number; question: string; kind: string; value: string }[];
};

export type ResponsesPage = {
  total: number;
  offset: number;
  limit: number;
  responses: SavedResponse[];
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  // Ответ об ошибке может быть не JSON (например, 500 от сервера): разбор
  // не должен превращать понятную ошибку в «Ошибка соединения».
  let payload: { detail?: unknown } | null = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : response.status >= 500
          ? "Сервер не смог обработать запрос"
          : "Не удалось выполнить запрос";
    throw new ApiError(response.status, detail);
  }
  return payload as T;
}

function jsonInit(body: unknown): RequestInit {
  return jsonRequest("POST", body);
}

function jsonRequest(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  me: () => request<User>("/api/auth/me"),

  login: (email: string, password: string) =>
    request<User>("/api/auth/login", jsonInit({ email, password })),

  register: (email: string, password: string, invite: string) =>
    request<User>("/api/auth/register", jsonInit({ email, password, invite })),

  logout: () => request<{ status: string }>("/api/auth/logout", { method: "POST" }),

  invite: () => request<{ code: string }>("/api/invites", { method: "POST" }),

  datasets: () => request<DatasetSummary[]>("/api/datasets"),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DatasetSummary>("/api/datasets", { method: "POST", body: form });
  },

  importLink: (url: string, title = "") =>
    request<DatasetSummary>("/api/datasets/import", jsonInit({ url, title })),

  dataset: (id: number) => request<DatasetDetail>(`/api/datasets/${id}`),
  preview: (id: number, offset = 0, limit = 50) =>
    request<Preview>(`/api/datasets/${id}/preview?offset=${offset}&limit=${limit}`),

  updateCells: (id: number, edits: CellEdit[], offset: number, limit: number) =>
    request<EditResult>(`/api/datasets/${id}/cells`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edits, offset, limit }),
    }),
  scenarios: (id: number) => request<Scenarios>(`/api/datasets/${id}/scenarios`),
  run: (
    id: number,
    procedure: string,
    params: Record<string, unknown>,
    options: Record<string, unknown> = {},
  ) =>
    request<RunResult>(
      `/api/datasets/${id}/run`,
      jsonInit({ procedure, params, ...options }),
    ),

  exportReport: async (
    id: number,
    request_: Record<string, unknown>,
    format: string,
  ): Promise<Blob> => {
    const response = await fetch(`/api/datasets/${id}/export`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...request_, format }),
    });
    if (!response.ok) {
      const text = await response.text();
      const detail = text ? JSON.parse(text)?.detail : "";
      throw new ApiError(response.status, detail || "Не удалось выгрузить отчёт");
    }
    return response.blob();
  },

  downloadDataset: async (id: number, format: string): Promise<Blob> => {
    const response = await fetch(`/api/datasets/${id}/download?format=${format}`, {
      credentials: "include",
    });
    if (!response.ok) {
      throw new ApiError(response.status, "Не удалось скачать набор");
    }
    return response.blob();
  },

  multiAnswer: (id: number) =>
    request<{ count: number; items: { name: string; summary: string; options: number }[] }>(
      `/api/datasets/${id}/multi-answer`,
    ),

  splitMultiAnswer: (id: number) =>
    request<{
      created: string[];
      n_created: number;
      n_questions: number;
      report: string;
    }>(`/api/datasets/${id}/multi-answer/split`, { method: "POST" }),

  charts: () => request<{ key: string; title: string }[]>("/api/charts"),

  chart: (id: number, values: Record<string, unknown>, theme: string) =>
    request<{ kind: string; title: string; caption: string; svg: string }>(
      `/api/datasets/${id}/chart`,
      jsonInit({ values, theme }),
    ),

  procedures: () => request<ProcedureInfo[]>("/api/procedures"),

  procedure: (key: string) => request<ProcedureSchema>(`/api/procedures/${key}`),

  remove: (id: number) => request<void>(`/api/datasets/${id}`, { method: "DELETE" }),

  // ---------------------------------------------------------------- опросы

  surveys: () => request<SurveySummary[]>("/api/surveys"),

  survey: (id: number) => request<SurveyDetail>(`/api/surveys/${id}`),

  createSurvey: (title = "Новый опрос") =>
    request<SurveyDetail>("/api/surveys", jsonInit({ title })),

  saveSurvey: (id: number, payload: SurveyInput) =>
    request<SurveyDetail>(`/api/surveys/${id}`, jsonRequest("PUT", payload)),

  setSurveyStatus: (id: number, status: SurveyStatus) =>
    request<SurveyDetail>(`/api/surveys/${id}/status`, jsonInit({ status })),

  removeSurvey: (id: number) =>
    request<void>(`/api/surveys/${id}`, { method: "DELETE" }),

  surveyResponses: (id: number, offset = 0, limit = 50) =>
    request<ResponsesPage>(
      `/api/surveys/${id}/responses?offset=${offset}&limit=${limit}`,
    ),

  // Опрос -> набор: кнопка «Исследовать в Winnow». Набор пересобирается из
  // ответов при каждом нажатии и открывается во вкладке «Данные».
  buildSurveyDataset: (id: number) =>
    request<DatasetSummary & { survey_id: number }>(`/api/surveys/${id}/dataset`, {
      method: "POST",
    }),

  publicSurvey: (slug: string) =>
    request<PublicSurvey>(`/api/public/surveys/${encodeURIComponent(slug)}`),

  submitResponse: (slug: string, answers: AnswerInput[]) =>
    request<{ id: number; submitted_at: string; status: string }>(
      `/api/public/surveys/${encodeURIComponent(slug)}/responses`,
      jsonInit({ answers }),
    ),

  // ------------------------------------------------------------ исследование AI

  aiConfig: () => request<AIConfig>("/api/ai/config"),

  // Разрешение ИИ видеть строки — отдельное действие человека, поэтому PATCH,
  // а не часть загрузки набора.
  aiSetAccess: (datasetId: number, allow: boolean) =>
    request<{ dataset_id: number; ai_full_access: boolean }>(
      `/api/datasets/${datasetId}/ai-access`,
      jsonRequest("PATCH", { allow }),
    ),

  aiAnalyses: (datasetId: number) =>
    request<{ runs: AnalysisSummary[] }>(`/api/datasets/${datasetId}/analyses`),

  aiAnalysis: (runId: number) => request<AnalysisDetail>(`/api/analyses/${runId}`),

  // Проверка качества данных и модели: ничего не меняет, только отчёт.
  quality: (datasetId: number, target: string | null = null, predictors: string[] = []) =>
    request<{ report: QualityReport }>(
      `/api/datasets/${datasetId}/quality`,
      jsonInit({ target, predictors }),
    ),

  // Research Stress Test: сохраняет прогон и возвращает полный отчёт.
  stressTest: (datasetId: number, payload: StressRequest) =>
    request<{ run_id: number; report: StressReport; duration_ms: number }>(
      `/api/datasets/${datasetId}/stress-test`,
      jsonInit(payload),
    ),

  stressTestRun: (runId: number) =>
    request<{ run: { payload: StressReport; params: Record<string, unknown> } }>(
      `/api/stress-tests/${runId}`,
    ),

  stressRuns: (datasetId: number) =>
    request<{ runs: AnalysisSummary[] }>(`/api/datasets/${datasetId}/stress-tests`),

  stressExport: async (runId: number, format: "html" | "docx" | "xlsx") => {
    const response = await fetch(`/api/stress-tests/${runId}/export?format=${format}`, {
      credentials: "include",
    });
    if (!response.ok) {
      const text = await response.text();
      let detail = "Не удалось выгрузить отчёт";
      try {
        const parsed = JSON.parse(text) as { detail?: string };
        detail = parsed.detail ?? detail;
      } catch {
        // оставляем понятное сообщение по умолчанию
      }
      throw new ApiError(response.status, detail);
    }
    return response.blob();
  },

  relationships: (datasetId: number, method = "auto", maxVariables = 60) =>
    request<RelationshipMap>(`/api/datasets/${datasetId}/relationships`, {
      ...jsonInit({ method, max_variables: maxVariables }),
    }),

  datasetRevision: (datasetId: number) =>
    request<{ revision: string }>(`/api/datasets/${datasetId}/revision`),
};

/**
 * Поток одного хода агента. fetch + ReadableStream, а не EventSource: запрос
 * POST, и EventSource не умеет ни тело, ни cookie-учёт в нашем виде.
 */
export async function streamAI(
  body: { dataset_id: number; message: string; conversation_id: number | null },
  onEvent: (event: AIEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/ai/chat", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let detail = "Не удалось получить ответ агента";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // ответ не JSON — оставляем общий текст
    }
    throw new ApiError(response.status, detail);
  }
  if (!response.body) {
    throw new ApiError(0, "Браузер не поддерживает потоковый ответ");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = chunk
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (data) {
        try {
          onEvent(JSON.parse(data) as AIEvent);
        } catch {
          // один битый пакет не должен ронять весь диалог
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}
