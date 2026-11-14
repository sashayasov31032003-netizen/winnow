import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type RelationshipEdge,
  type RelationshipGroup,
  type RelationshipMap,
  type RelationshipNode,
} from "./api";

// Карта взаимосвязей переменных.
//
// Узлы — переменные, линии — статистические связи. Толщина линии отражает
// силу, цвет — направление для количественных пар. Это не причинный граф:
// подпись об этом остаётся на экране всегда.

const GROUPS: { id: RelationshipGroup; title: string }[] = [
  { id: "scale", title: "Количественные" },
  { id: "ordinal", title: "Порядковые" },
  { id: "nominal", title: "Категориальные" },
  { id: "other", title: "Другие" },
];

const METHOD_OPTIONS = [
  { id: "auto", title: "Авто" },
  { id: "pearson", title: "Пирсон" },
  { id: "spearman", title: "Спирмен" },
  { id: "kendall", title: "Кендалл" },
];

const WIDTH = 1000;
const HEIGHT = 680;

type Point = { x: number; y: number };
type Layout = Record<string, Point>;

function formatP(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (value < 0.001) return "< 0,001";
  return value.toFixed(3).replace(".", ",");
}

function formatStat(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(3).replace(".", ",");
}

function viewBoxFor(positions: Layout): string {
  const points = Object.values(positions);
  if (!points.length) return `0 0 ${WIDTH} ${HEIGHT}`;
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const padding = 80;
  const minX = Math.max(0, Math.min(...xs) - padding);
  const minY = Math.max(0, Math.min(...ys) - padding);
  const maxX = Math.min(WIDTH, Math.max(...xs) + padding);
  const maxY = Math.min(HEIGHT, Math.max(...ys) + padding);
  const width = Math.max(320, maxX - minX);
  const height = Math.max(260, maxY - minY);
  return `${minX} ${minY} ${width} ${height}`;
}

function directionTitle(direction: string): string {
  if (direction === "positive") return "положительная";
  if (direction === "negative") return "отрицательная";
  return "без направления";
}

function edgeClass(edge: RelationshipEdge): string {
  if (edge.direction === "positive") return "positive";
  if (edge.direction === "negative") return "negative";
  return "neutral";
}

function layoutGraph(nodes: RelationshipNode[], edges: RelationshipEdge[]): Layout {
  if (!nodes.length) return {};
  const positions: Record<string, Point> = {};
  const groupIndex: Record<string, number> = {};
  const groupCount: Record<string, number> = {};
  for (const node of nodes) {
    groupCount[node.group] = (groupCount[node.group] ?? 0) + 1;
  }
  for (const [index, node] of nodes.entries()) {
    const position = groupIndex[node.group] ?? 0;
    groupIndex[node.group] = position + 1;
    const groupPosition = GROUPS.findIndex((item) => item.id === node.group);
    const baseAngle = ((groupPosition < 0 ? 3 : groupPosition) / GROUPS.length) * Math.PI * 2;
    const spread = ((position + 0.5) / Math.max(1, groupCount[node.group])) * 0.9;
    const radius = 220 + (index % 4) * 55;
    positions[node.name] = {
      x: WIDTH / 2 + Math.cos(baseAngle + spread) * radius,
      y: HEIGHT / 2 + Math.sin(baseAngle + spread) * radius * 0.72,
    };
  }

  const springs = edges.map((edge) => ({
    a: edge.source,
    b: edge.target,
    strength: edge.strength,
  }));
  const index = new Map(nodes.map((node, position) => [node.name, position]));
  const speed: Record<string, Point> = Object.fromEntries(
    nodes.map((node) => [node.name, { x: 0, y: 0 }]),
  );

  for (let iteration = 0; iteration < 190; iteration += 1) {
    for (let first = 0; first < nodes.length; first += 1) {
      const a = nodes[first];
      for (let second = first + 1; second < nodes.length; second += 1) {
        const b = nodes[second];
        const pa = positions[a.name];
        const pb = positions[b.name];
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let distance = Math.hypot(dx, dy);
        if (distance < 0.01) {
          dx = 0.01;
          dy = 0.01;
          distance = 0.014;
        }
        const force = Math.min(28, 44000 / (distance * distance));
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        speed[a.name].x += fx;
        speed[a.name].y += fy;
        speed[b.name].x -= fx;
        speed[b.name].y -= fy;
      }
    }
    for (const spring of springs) {
      const pa = positions[spring.a];
      const pb = positions[spring.b];
      if (!pa || !pb) continue;
      const dx = pb.x - pa.x;
      const dy = pb.y - pa.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = 155 - spring.strength * 40;
      const force = (distance - desired) * 0.016;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      speed[spring.a].x += fx;
      speed[spring.a].y += fy;
      speed[spring.b].x -= fx;
      speed[spring.b].y -= fy;
    }
    for (const node of nodes) {
      const point = positions[node.name];
      speed[node.name].x += (WIDTH / 2 - point.x) * 0.0007;
      speed[node.name].y += (HEIGHT / 2 - point.y) * 0.0007;
      point.x = Math.max(55, Math.min(WIDTH - 55, point.x + speed[node.name].x));
      point.y = Math.max(55, Math.min(HEIGHT - 55, point.y + speed[node.name].y));
      speed[node.name].x *= 0.78;
      speed[node.name].y *= 0.78;
    }
    if (iteration === 0 && index.size !== nodes.length) break;
  }
  return positions;
}

export function RelationshipMapView({ datasetId }: { datasetId: number }) {
  const [map, setMap] = useState<RelationshipMap | null>(null);
  const [method, setMethod] = useState("auto");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [minStrength, setMinStrength] = useState(0.3);
  const [significantOnly, setSignificantOnly] = useState(true);
  const [direction, setDirection] = useState<"all" | "positive" | "negative">("all");
  const [query, setQuery] = useState("");
  const [hiddenGroups, setHiddenGroups] = useState<Set<RelationshipGroup>>(new Set());
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const loaded = await api.relationships(datasetId, method, 60);
      setMap(loaded);
      setSelectedNode(null);
      setSelectedEdge(null);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "Не удалось построить карту связей");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, method]);

  const positions = useMemo(
    () => (map ? layoutGraph(map.nodes, map.edges) : {}),
    [map],
  );
  const viewBox = useMemo(() => viewBoxFor(positions), [positions]);
  const byName = useMemo(
    () => new Map((map?.nodes ?? []).map((node) => [node.name, node])),
    [map],
  );
  const visibleNodes = useMemo(
    () => (map?.nodes ?? []).filter((node) => !hiddenGroups.has(node.group)),
    [hiddenGroups, map],
  );
  const visibleName = useMemo(() => new Set(visibleNodes.map((node) => node.name)), [visibleNodes]);
  const normalizedQuery = query.trim().toLowerCase();
  const matching = useMemo(() => {
    if (!normalizedQuery) return new Set<string>();
    return new Set(
      visibleNodes
        .filter(
          (node) =>
            node.name.toLowerCase().includes(normalizedQuery) ||
            node.label.toLowerCase().includes(normalizedQuery) ||
            node.display.toLowerCase().includes(normalizedQuery),
        )
        .map((node) => node.name),
    );
  }, [normalizedQuery, visibleNodes]);

  const visibleEdges = useMemo(() => {
    if (!map) return [];
    return map.edges.filter((edge) => {
      if (!visibleName.has(edge.source) || !visibleName.has(edge.target)) return false;
      if (edge.strength < minStrength) return false;
      if (significantOnly && !edge.significant) return false;
      if (direction !== "all" && edge.direction !== direction) return false;
      return true;
    });
  }, [direction, map, minStrength, significantOnly, visibleName]);

  const selectedNodeData = selectedNode ? byName.get(selectedNode) ?? null : null;
  const selectedEdgeData = selectedEdge
    ? map?.edges.find((edge) => edge.id === selectedEdge) ?? null
    : null;
  const nodeEdges = useMemo(() => {
    if (!map || !selectedNode) return [];
    return map.edges
      .filter((edge) => edge.source === selectedNode || edge.target === selectedNode)
      .sort((left, right) => right.strength - left.strength);
  }, [map, selectedNode]);

  if (loading) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">◇</span>
        <h2>Строим карту связей…</h2>
        <p>Считаем корреляции, V Крамера и η² для пар переменных.</p>
      </div>
    );
  }

  if (error || !map) {
    return (
      <div className="card empty">
        <span className="empty-icon" aria-hidden="true">◇</span>
        <h2>Карта не построилась</h2>
        <p>{error || "Нет данных для отображения."}</p>
        <button type="button" onClick={() => void load()}>Повторить</button>
      </div>
    );
  }

  function clearSelection() {
    setSelectedNode(null);
    setSelectedEdge(null);
  }

  return (
    <div className="relations-layout">
      <div className="card relations-head">
        <div>
          <div className="eyebrow">Variable Relationship Map</div>
          <h1>Карта взаимосвязей</h1>
          <p className="muted">
            Узлы — переменные, линии — статистические связи. Толщина линии
            показывает силу, цвет — направление для количественных пар.
            Это не причинный граф.
          </p>
        </div>
        <div className="relations-head-actions">
          <span className="relations-revision" title="Версия набора на момент расчёта">
            {map.dataset_revision.slice(0, 8)}
          </span>
          <button type="button" onClick={() => void load()}>Обновить</button>
        </div>
      </div>

      <div className="relations-stats">
        <div className="relations-stat"><span>Переменные</span><strong>{map.summary.n_nodes}</strong></div>
        <div className="relations-stat"><span>Связи</span><strong>{map.summary.n_edges}</strong></div>
        <div className="relations-stat"><span>Значимые</span><strong>{map.summary.n_significant}</strong></div>
        <div className="relations-stat"><span>Сильные</span><strong>{map.summary.n_strong}</strong></div>
        <div className="relations-stat"><span>Коллинеарность</span><strong>{map.summary.n_potential_collinearity}</strong></div>
      </div>

      <div className="card relations-controls">
        <div className="relations-control-row">
          <label>
            <span>Метод для количественных пар</span>
            <select value={method} onChange={(event) => setMethod(event.target.value)}>
              {METHOD_OPTIONS.map((item) => (
                <option key={item.id} value={item.id}>{item.title}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Сила связи ≥ {minStrength.toFixed(2).replace(".", ",")}</span>
            <input
              type="range"
              min={0}
              max={0.95}
              step={0.05}
              value={minStrength}
              onChange={(event) => setMinStrength(Number(event.target.value))}
            />
          </label>
          <label>
            <span>Направление</span>
            <select
              value={direction}
              onChange={(event) => setDirection(event.target.value as typeof direction)}
            >
              <option value="all">Все</option>
              <option value="positive">Положительные</option>
              <option value="negative">Отрицательные</option>
            </select>
          </label>
          <label className="relations-check">
            <input
              type="checkbox"
              checked={significantOnly}
              onChange={(event) => setSignificantOnly(event.target.checked)}
            />
            Только значимые (FDR &lt; 0,05)
          </label>
          <label className="relations-search">
            <span>Поиск переменной</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="имя или метка"
            />
          </label>
        </div>
        <div className="relations-groups">
          {GROUPS.map((group) => {
            const hidden = hiddenGroups.has(group.id);
            const count = map.nodes.filter((node) => node.group === group.id).length;
            return (
              <button
                key={group.id}
                type="button"
                className={`relations-group-chip${hidden ? " hidden" : ""} ${group.id}`}
                disabled={count === 0}
                onClick={() => {
                  const next = new Set(hiddenGroups);
                  if (hidden) next.delete(group.id);
                  else next.add(group.id);
                  setHiddenGroups(next);
                }}
              >
                {group.title} <span>{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      {map.summary.recommendations.length > 0 && (
        <div className="card relations-recommendations">
          <strong>Что стоит проверить</strong>
          <ul>
            {map.summary.recommendations.map((text) => <li key={text}>{text}</li>)}
          </ul>
        </div>
      )}

      <div className="relations-main">
        <div className="card relations-canvas-card">
          <svg
            className="relations-canvas"
            viewBox={viewBox}
            role="img"
            aria-label="Сеть статистических связей переменных"
            onClick={clearSelection}
          >
            <g className="relations-edges">
              {visibleEdges.map((edge) => {
                const from = positions[edge.source];
                const to = positions[edge.target];
                if (!from || !to) return null;
                const selected = selectedEdge === edge.id;
                const dim =
                  normalizedQuery.length > 0 &&
                  !matching.has(edge.source) &&
                  !matching.has(edge.target);
                return (
                  <g key={edge.id} className={dim ? "dim" : ""}>
                    <line
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      className="relations-edge-hit"
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedEdge(edge.id);
                        setSelectedNode(null);
                      }}
                    />
                    <line
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      className={`relations-edge ${edgeClass(edge)}${selected ? " selected" : ""}`}
                      style={{ strokeWidth: 1 + edge.strength * 5 }}
                    />
                  </g>
                );
              })}
            </g>
            <g className="relations-nodes">
              {visibleNodes.map((node) => {
                const point = positions[node.name];
                if (!point) return null;
                const selected = selectedNode === node.name;
                const dim =
                  normalizedQuery.length > 0 &&
                  !matching.has(node.name) &&
                  node.name !== selectedNode;
                const radius = 10 + Math.min(9, Math.sqrt(node.significant_degree) * 3.5);
                return (
                  <g
                    key={node.name}
                    transform={`translate(${point.x} ${point.y})`}
                    className={`relations-node ${node.group}${selected ? " selected" : ""}${dim ? " dim" : ""}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedNode(node.name);
                      setSelectedEdge(null);
                    }}
                  >
                    <circle r={selected ? radius + 4 : radius} />
                    <text y={radius + 13}>{node.label || node.name}</text>
                    <title>{node.display}</title>
                  </g>
                );
              })}
            </g>
          </svg>
          <div className="relations-legend">
            <span><i className="positive" /> положительная</span>
            <span><i className="negative" /> отрицательная</span>
            <span><i className="neutral" /> без направления</span>
            <span className="muted">Нажмите на узел или линию</span>
          </div>
        </div>

        <aside className="relations-panel card">
          {selectedEdgeData ? (
            <EdgePanel
              edge={selectedEdgeData}
              source={byName.get(selectedEdgeData.source)}
              target={byName.get(selectedEdgeData.target)}
              onClose={clearSelection}
            />
          ) : selectedNodeData ? (
            <NodePanel
              node={selectedNodeData}
              edges={nodeEdges}
              byName={byName}
              onEdge={(edge) => {
                setSelectedEdge(edge.id);
                setSelectedNode(null);
              }}
              onClose={clearSelection}
            />
          ) : (
            <SummaryPanel map={map} onEdge={(edge) => setSelectedEdge(edge.id)} />
          )}
        </aside>
      </div>
    </div>
  );
}

function SummaryPanel({ map, onEdge }: { map: RelationshipMap; onEdge: (edge: RelationshipEdge) => void }) {
  return (
    <div className="relations-panel-inner">
      <span className="eyebrow">Сводка</span>
      <h2>С чего начать</h2>
      <p className="muted small">
        Связей: {map.summary.n_edges}, значимых после поправки на множественные
        сравнения: {map.summary.n_significant}.
      </p>
      {map.summary.strongest.length > 0 && (
        <>
          <h3>Самые сильные</h3>
          <div className="relations-edge-list">
            {map.summary.strongest.slice(0, 5).map((edge) => (
              <button key={edge.id} type="button" onClick={() => onEdge(edge)}>
                <span>{edge.source} ↔ {edge.target}</span>
                <span>{edge.method_label} · {formatStat(edge.statistic)}</span>
              </button>
            ))}
          </div>
        </>
      )}
      <h3>Ограничения</h3>
      <ul className="relations-notes">
        <li>Связь не означает причинность.</li>
        <li>Пропуски исключаются попарно.</li>
        <li>V Крамера и η² не имеют направления.</li>
        <li>Сильные корреляции — повод проверить VIF, а не доказательство.</li>
      </ul>
    </div>
  );
}

function NodePanel({
  node,
  edges,
  byName,
  onEdge,
  onClose,
}: {
  node: RelationshipNode;
  edges: RelationshipEdge[];
  byName: Map<string, RelationshipNode>;
  onEdge: (edge: RelationshipEdge) => void;
  onClose: () => void;
}) {
  return (
    <div className="relations-panel-inner">
      <div className="relations-panel-head">
        <span className="eyebrow">Переменная</span>
        <button type="button" className="ghost small-button" onClick={onClose}>Закрыть</button>
      </div>
      <h2>{node.label || node.name}</h2>
      <p className="muted small">{node.display}</p>
      <dl className="relations-dl">
        <div><dt>Тип</dt><dd>{node.type}</dd></div>
        <div><dt>Уровень</dt><dd>{node.measure}</dd></div>
        <div><dt>Группа</dt><dd>{node.group_label}</dd></div>
        <div><dt>Наблюдений</dt><dd>{node.n}</dd></div>
        <div><dt>Пропущено</dt><dd>{node.n_missing}</dd></div>
        <div><dt>Уникальных</dt><dd>{node.n_unique}</dd></div>
        <div><dt>Связей</dt><dd>{node.degree} (значимых {node.significant_degree})</dd></div>
      </dl>
      {!node.available && <p className="error">{node.reason}</p>}
      <h3>Рекомендации</h3>
      <ul className="relations-notes">
        {node.recommendations.map((text) => <li key={text}>{text}</li>)}
      </ul>
      <h3>Связи</h3>
      <div className="relations-edge-list">
        {edges.slice(0, 20).map((edge) => {
          const other = edge.source === node.name ? edge.target : edge.source;
          return (
            <button key={edge.id} type="button" onClick={() => onEdge(edge)}>
              <span>{byName.get(other)?.label ?? other}</span>
              <span>{edge.method_label} · {formatStat(edge.statistic)} · p {formatP(edge.p)}</span>
            </button>
          );
        })}
        {!edges.length && <p className="muted small">Связей нет.</p>}
      </div>
    </div>
  );
}

function EdgePanel({
  edge,
  source,
  target,
  onClose,
}: {
  edge: RelationshipEdge;
  source?: RelationshipNode;
  target?: RelationshipNode;
  onClose: () => void;
}) {
  return (
    <div className="relations-panel-inner">
      <div className="relations-panel-head">
        <span className="eyebrow">Связь</span>
        <button type="button" className="ghost small-button" onClick={onClose}>Закрыть</button>
      </div>
      <h2>{source?.label ?? edge.source} ↔ {target?.label ?? edge.target}</h2>
      <p className="muted small">{edge.method_label} · {edge.kind}</p>
      <dl className="relations-dl">
        <div><dt>Статистика</dt><dd>{formatStat(edge.statistic)}</dd></div>
        <div><dt>Сила</dt><dd>{formatStat(edge.strength)}</dd></div>
        <div><dt>Направление</dt><dd>{directionTitle(edge.direction)}</dd></div>
        <div><dt>p-value</dt><dd>{formatP(edge.p)}</dd></div>
        <div><dt>q (FDR)</dt><dd>{formatP(edge.q)}</dd></div>
        <div><dt>N</dt><dd>{edge.n}</dd></div>
        <div><dt>Значима</dt><dd>{edge.significant ? "да" : "нет"}</dd></div>
      </dl>
      {edge.warning && <p className="notice">{edge.warning}</p>}
      <p className="muted small">
        Это статистическая связь, а не причинное влияние. Направление для
        V Крамера и η² не определено.
      </p>
      <h3>Переменные</h3>
      <div className="relations-edge-list">
        {[source, target].filter(Boolean).map((node) => (
          <div key={node!.name} className="relations-variable-line">
            <strong>{node!.label || node!.name}</strong>
            <span>{node!.group_label} · N = {node!.n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
