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
