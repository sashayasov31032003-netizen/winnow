import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, streamAI } from "./api";
import type {
  AIConfig,
  AIEvent,
  AIToolEvent,
  AnalysisDetail,
  DatasetSummary,
} from "./api";

// Экран «Исследование AI».
//
// Здесь нет собственной статистики: агент вызывает серверные инструменты, а
// экран показывает то, что вернул сервер. Числа в карточке расчёта берутся из
// сохранённого результата, а не из текста модели — поэтому их можно проверить.

const TOOL_TITLES: Record<string, string> = {
  list_datasets: "Наборы",
  get_dataset_schema: "Схема данных",
  get_profile: "Профиль данных",
  check_quality: "Проверка качества",
  get_preview: "Строки данных",
  list_procedures: "Процедуры",
  run_procedure: "Расчёт",
  suggest_research: "Сценарии исследования",
  get_run: "Сохранённый расчёт",
};

//: Провайдер показываем коротким именем, а не длинным ID модели: у Yandex
//: модель выглядит как gpt://<каталог>/... и в бейдж не помещается.
const PROVIDER_TITLES: Record<string, string> = {
  fake: "демо без модели",
  yandex: "Yandex AI Studio",
  vsegpt: "VseGPT",
  ollama: "Ollama",
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
  custom: "свой API",
};

const EXAMPLES = [
  "Опиши данные и предложи, с чего начать",
  "Сравни тревожность у мужчин и женщин",
  "Проверь связь дохода и удовлетворённости жизнью",
  "Какие закономерности есть в этих данных?",
];

type ChatTool = AIToolEvent;

type ChatRun = {
  run_id: number;
  procedure: string;
  title: string;
  n_tables: number;
};

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  tools: ChatTool[];
  runs: ChatRun[];
  warnings: string[];
  streaming: boolean;
};

export function ResearchAI({
  datasetId,
  datasets,
  onSelect,
  onGoToData,
}: {
  datasetId: number | null;
  datasets: DatasetSummary[];
  onSelect: (id: number) => void;
  onGoToData: () => void;
}) {
  const dataset = useMemo(
    () => datasets.find((item) => item.id === datasetId) ?? null,
    [datasets, datasetId],
  );

  const [config, setConfig] = useState<AIConfig | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [model, setModel] = useState("");
  // Компонент пересоздаётся при смене набора (key в App), поэтому начальное
  // значение флага можно взять из списка без синхронизации в эффекте.
  const [access, setAccess] = useState<boolean>(
    () => dataset?.ai_full_access ?? false,
  );
  const [accessBusy, setAccessBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const transcript = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .aiConfig()
      .then((loaded) => {
        setConfig(loaded);
        setModel(loaded.model);
      })
      .catch((problem) =>
        setError(problem instanceof ApiError ? problem.message : "Ошибка соединения"),
      );
  }, []);

  // Новые сообщения появляются снизу: без прокрутки человек не видит ответ.
  useEffect(() => {
    const element = transcript.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages]);

  function patch(id: number, change: (message: ChatMessage) => ChatMessage) {
    setMessages((current) =>
      current.map((message) => (message.id === id ? change(message) : message)),
    );
  }

  function handleEvent(id: number, event: AIEvent) {
    if (event.type === "start") {
      setConversationId(event.conversation_id);
      setModel(event.model);
      return;
    }
    if (event.type === "tool_call") {
      patch(id, (message) => ({
        ...message,
        tools: [
          ...message.tools,
          { id: event.id, name: event.name, arguments: event.arguments },
        ],
      }));
      return;
    }
    if (event.type === "tool_result") {
      patch(id, (message) => ({
        ...message,
        tools: message.tools.map((tool) =>
          tool.id === event.id
            ? {
                ...tool,
                ok: event.ok,
                run_id: event.run_id,
                error: event.error,
                duration_ms: event.duration_ms,
              }
            : tool,
        ),
      }));
      return;
    }
    if (event.type === "run") {
      patch(id, (message) => ({
        ...message,
        runs: message.runs.some((run) => run.run_id === event.run_id)
          ? message.runs
          : [
              ...message.runs,
              {
                run_id: event.run_id,
                procedure: event.procedure,
                title: event.title,
                n_tables: event.n_tables,
              },
            ],
      }));
      return;
    }
    if (event.type === "warning") {
      patch(id, (message) => ({
        ...message,
        warnings: [...message.warnings, event.message],
      }));
      return;
    }
    if (event.type === "text") {
      patch(id, (message) => ({ ...message, text: event.text }));
      return;
    }
    if (event.type === "done") {
      patch(id, (message) => ({ ...message, streaming: false }));
      setConfig((current) =>
        current
          ? {
              ...current,
              used_today: current.used_today + 1,
              remaining: Math.max(0, current.remaining - 1),
            }
          : current,
      );
      return;
    }
    if (event.type === "error") {
      patch(id, (message) => ({ ...message, streaming: false }));
      setError(event.message);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || !datasetId || streaming) return;
    setInput("");
    setError("");

    const userMessage: ChatMessage = {
      id: nextId.current++,
      role: "user",
      text,
      tools: [],
      runs: [],
      warnings: [],
      streaming: false,
    };
    const assistantMessage: ChatMessage = {
      id: nextId.current++,
      role: "assistant",
      text: "",
      tools: [],
      runs: [],
      warnings: [],
      streaming: true,
    };
    setMessages((current) => [...current, userMessage, assistantMessage]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamAI(
        { dataset_id: datasetId, message: text, conversation_id: conversationId },
        (event) => handleEvent(assistantMessage.id, event),
        controller.signal,
      );
    } catch (problem) {
      if (problem instanceof DOMException && problem.name === "AbortError") {
        patch(assistantMessage.id, (message) => ({
          ...message,
          streaming: false,
          text: message.text || "Остановлено.",
        }));
      } else {
        const message_ =
          problem instanceof ApiError ? problem.message : "Ошибка соединения";
        setError(message_);
        patch(assistantMessage.id, (message) => ({
          ...message,
          streaming: false,
        }));
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
      patch(assistantMessage.id, (message) => ({ ...message, streaming: false }));
    }
  }

  async function toggleAccess(allow: boolean) {
    if (!datasetId) return;
    setAccessBusy(true);
    setError("");
    try {
      const result = await api.aiSetAccess(datasetId, allow);
      setAccess(result.ai_full_access);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось изменить доступ");
    } finally {
      setAccessBusy(false);
    }
  }

  if (datasets.length === 0) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">
          ◇
        </span>
        <h2>Исследование AI</h2>
        <p>
          Сначала загрузите данные: агент работает с конкретным набором, а не с
          абстрактными числами. Он посмотрит схему, профиль и запустит реальные
          расчёты, а не придумает статистику.
        </p>
        <button type="button" onClick={onGoToData}>
          Перейти к данным
        </button>
      </div>
    );
  }

  const disabled = !config?.enabled || config.remaining <= 0;

  return (
    <div className="ai-layout">
      <header className="ai-head">
        <div>
          <h1>Исследование AI</h1>
          <p className="muted">
            Агент подбирает метод, запускает расчёт и объясняет результат. Числа
            берутся из аналитического ядра Winnow.
          </p>
        </div>
        <div className="ai-badges">
          <span className="badge" title={config?.model ?? ""}>
            {config ? PROVIDER_TITLES[config.provider] ?? config.provider : model || "модель"}
          </span>
          {config && (
            <span
              className="badge"
              data-tone={config.remaining > 0 ? "scale" : "warning"}
              title="Сколько сообщений осталось на сегодня"
            >
              осталось {config.remaining} из {config.daily_limit}
            </span>
          )}
        </div>
      </header>

      <div className="card ai-controls">
        <div className="ai-dataset-row">
          <label htmlFor="ai-dataset">Набор данных</label>
          <select
            id="ai-dataset"
            value={datasetId ?? ""}
            onChange={(event) => onSelect(Number(event.target.value))}
          >
            {datasets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.n_cases} случаев
              </option>
            ))}
          </select>
        </div>
        <label className="ai-toggle">
          <input
            type="checkbox"
            checked={access}
            disabled={accessBusy}
            onChange={(event) => void toggleAccess(event.target.checked)}
          />
          <span>
            Разрешить ИИ видеть строки данных
            <small>
              По умолчанию доступны только схема, профиль и агрегаты. Строки могут
              содержать персональные данные — включайте осознанно.
            </small>
          </span>
        </label>
        {config?.note && <p className="muted small ai-note">{config.note}</p>}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="card ai-chat">
        <div className="ai-transcript" ref={transcript}>
          {messages.length === 0 && (
            <div className="ai-empty">
              <p>
                Задайте вопрос словами — например, «сравни тревожность у мужчин и
                женщин». Агент сначала посмотрит данные, потом выберет метод.
              </p>
              <div className="ai-examples">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="ghost"
                    onClick={() => setInput(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message) => (
            <div key={message.id} className={`ai-msg ${message.role}`}>
              {message.role === "user" ? (
                <p className="ai-user-text">{message.text}</p>
              ) : (
                <>
                  {message.text && <p className="ai-assistant-text">{message.text}</p>}
                  {!message.text && message.streaming && (
                    <p className="muted ai-thinking">Думаю…</p>
                  )}
                  {message.tools.length > 0 && (
                    <div className="ai-tools">
                      {message.tools.map((tool) => (
                        <ToolCard key={tool.id} tool={tool} />
                      ))}
                    </div>
                  )}
                  {message.runs.length > 0 && (
                    <div className="ai-runs">
                      {message.runs.map((run) => (
                        <RunCard key={run.run_id} run={run} />
                      ))}
                    </div>
                  )}
                  {message.warnings.length > 0 && (
                    <ul className="ai-warnings">
                      {message.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          ))}
        </div>

        <form
          className="ai-composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder="Спросите о данных: связи, различия, распределения…"
            rows={2}
            aria-label="Сообщение агенту"
          />
          {streaming ? (
            <button
              type="button"
              className="ghost"
              onClick={() => abortRef.current?.abort()}
            >
              Остановить
            </button>
          ) : (
            <button type="submit" disabled={disabled || !input.trim() || !datasetId}>
              Отправить
            </button>
          )}
        </form>
        {config && !config.enabled && (
          <p className="muted small ai-note">
            Агент выключен: на сервере не задан ключ модели. Демо-режим показывает
            только это сообщение.
          </p>
        )}
      </div>
    </div>
  );
}

function ToolCard({ tool }: { tool: ChatTool }) {
  const title = TOOL_TITLES[tool.name] ?? tool.name;
  const procedure =
    typeof tool.arguments.procedure === "string" ? tool.arguments.procedure : "";
  const status = tool.ok === undefined ? "идёт" : tool.ok ? "готово" : "ошибка";
  return (
    <div className="ai-tool" data-status={tool.ok === false ? "error" : undefined}>
      <div className="ai-tool-head">
        <span className="ai-tool-name">{title}</span>
        {procedure && <span className="muted small">{procedure}</span>}
        <span className="ai-tool-status">{status}</span>
      </div>
      {tool.error && <p className="ai-tool-error">{tool.error}</p>}
      {tool.run_id && <p className="muted small">расчёт #{tool.run_id}</p>}
    </div>
  );
}

function RunCard({ run }: { run: ChatRun }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<AnalysisDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || detail) return;
    let alive = true;
    api
      .aiAnalysis(run.run_id)
      .then((loaded) => {
        if (alive) setDetail(loaded);
      })
      .catch((problem) => {
        if (alive) {
          setError(problem instanceof ApiError ? problem.message : "Не удалось открыть расчёт");
        }
      });
    return () => {
      alive = false;
    };
  }, [open, detail, run.run_id]);

  const table = detail?.payload.tables?.[0];
  const findings = detail?.payload.findings ?? [];

  return (
    <details
      className="ai-run"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span className="ai-run-title">{run.title}</span>
        <span className="muted small">
          #{run.run_id} · таблиц: {run.n_tables}
        </span>
      </summary>
      {error && <p className="error small">{error}</p>}
      {!detail && !error && <p className="muted small">Открываю расчёт…</p>}
      {detail && (
        <>
          {table && (
            <div className="ai-table-wrap">
              <table className="ai-table">
                <thead>
                  <tr>
                    {table.columns.map((column) => (
                      <th key={column.label}>{column.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, index) => (
                    <tr key={index}>
                      {row.map((value, cell) => (
                        <td key={cell}>
                          {value === null || value === undefined
                            ? "—"
                            : typeof value === "number"
                              ? value.toLocaleString("ru-RU", {
                                  maximumFractionDigits:
                                    table.columns[cell]?.decimals ?? 3,
                                })
                              : String(value)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {findings.length > 0 && (
            <ul className="ai-findings">
              {findings.map((finding, index) => (
                <li key={index} data-kind={finding.kind}>
                  {finding.text}
                </li>
              ))}
            </ul>
          )}
          {detail.payload.warnings.length > 0 && (
            <ul className="ai-warnings">
              {detail.payload.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </details>
  );
}
