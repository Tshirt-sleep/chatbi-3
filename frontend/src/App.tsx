import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { createResultCsv, sortResultRows } from "./resultTable.mjs";
import type { ResultTableSort } from "./resultTable.mjs";

type HealthState = "checking" | "ready" | "unavailable";
type SemanticGuide = {
  dataset_id: string;
  version: string;
  timezone: string;
  date_window: { start_inclusive: string; end_exclusive: string; as_of_date: string };
  metrics: { id: string; label: string; definition: string; unit: string; aliases: string[]; dimensions: string[] }[];
  ambiguous_terms: { text: string; note: string }[];
};
type MetricValue = {
  metric_id: string;
  label: string;
  value: string | number | null;
  unit: string;
  definition: string;
};
type ResultRow = {
  key: string;
  label: string;
  values: Record<string, string | number | null>;
};
type TurnResponse = {
  request_id: string;
  turn_id: string;
  status: "completed" | "clarification_required" | "unsupported" | "unknown_term" | "failed";
  answer_text: string;
  clarification_id: string | null;
  clarification_prompt: string | null;
  suggested_terms: string[];
  values: MetricValue[];
  interpretation: {
    metric_ids: string[];
    dimension_ids: string[];
    time_range: { timezone: string; start_inclusive: string; end_exclusive: string } | null;
    filters: string[];
    sort: string[];
  };
  visualization: { type: "kpi" | "line" | "bar" | "table" | "none"; data: ResultRow[] };
  evidence: {
    dataset_id: string;
    dataset_version: string;
    semantic_catalog_id: string;
    semantic_catalog_version: string;
    mock_data: true;
    metric_definitions: string[];
  };
  debug_ref: string | null;
};
type DebugInfo = {
    query_id: string;
    template_id: string;
    sql: string;
    parameters: Record<string, string | number>;
    query_executed: boolean;
    duration_ms: number | null;
    result_row_count: number;
};
type Message = { question: string; requestQuestion?: string; dateContext?: string; queryPerspective?: "management" | "operations" | "analyst"; response?: TurnResponse; error?: string };
type FeedbackSummary = { total: number; counts: { rating: string; category: string; count: number }[] };
type SavedSession = {
  id: string;
  sequence: number;
  title: string;
  datasetId: "ecommerce_mock_v1" | "saas_subscription_mock_v1";
  queryPerspective: QueryPerspective;
  createdAt: string;
  updatedAt: string;
  messages: Message[];
};

const API_BASE = (import.meta.env.VITE_CHATBI_API_BASE_URL || "http://127.0.0.1:8000")
  .replace(/\/$/, "");
const API = `${API_BASE}/api/v1`;
const PUBLIC_DEMO = import.meta.env.VITE_CHATBI_PUBLIC_DEMO === "true";
const PRODUCT_INTRO_URL = "/product-intro/";
const DEMO_API_IDENTITY = "analyst";
const DEMO_ADMIN_API_IDENTITY = "admin";
type QueryPerspective = "management" | "operations" | "analyst";
const QUERY_PERSPECTIVES: Record<QueryPerspective, { label: string; focus: string; answerFocus: string; ecommerce: string[] }> = {
  management: {
    label: "管理者",
    focus: "先看整体规模、关键变化和经营趋势。",
    answerFocus: "先看整体销售额、订单量和变化方向，再结合趋势图判断经营状态。",
    ecommerce: ["昨日流水和订单量分别是多少？", "最近完整月销售额比前一个月高多少？", "最近 7 天每天销售额趋势如何？"],
  },
  operations: {
    label: "运营/产品经理",
    focus: "优先看商品、类目和渠道排行，定位可以继续跟进的分组。",
    answerFocus: "优先查看商品、类目和渠道的排行与分组结果，定位值得跟进的环节。",
    ecommerce: ["近 30 天 GMV 排名前十的 SKU 有哪些？", "过去 30 天按品类拆分销售额和订单数", "近 30 天哪些 SKU 的退款订单率最高？"],
  },
  analyst: {
    label: "数据分析师",
    focus: "重点核对指标口径、统计周期、分组条件和明细表。",
    answerFocus: "重点核对指标口径、时间范围与过滤条件，并结合表格明细复核。",
    ecommerce: ["近一周每天的 GMV 走势怎么样？", "近 30 天各渠道平均订单金额分别多少？", "本周相较上周哪些类目的销售额下滑最多？"],
  },
};
const SAAS_EXAMPLES = ["当前有多少活跃订阅？", "当前 MRR 是多少？", "最近 7 天新增订阅数"];
const SESSION_STORAGE_KEY = "chatbi.demo.sessions.v1";
const ACTIVE_SESSION_STORAGE_KEY = "chatbi.demo.active-session.v1";
const NEXT_SESSION_NUMBER_KEY = "chatbi.demo.next-session-number.v1";
const ECOMMERCE_DATA_START = "2025-08-01";
const ECOMMERCE_DATA_END_EXCLUSIVE = "2026-08-01";

function readSavedSessions(): SavedSession[] {
  try {
    const value = localStorage.getItem(SESSION_STORAGE_KEY);
    if (!value) return [];
    const decoded = JSON.parse(value) as SavedSession[];
    if (!Array.isArray(decoded)) return [];
    const valid = decoded.filter((item) =>
      item && typeof item.id === "string"
      && (item.datasetId === "ecommerce_mock_v1" || item.datasetId === "saas_subscription_mock_v1")
      && ["management", "operations", "analyst"].includes(item.queryPerspective)
      && Array.isArray(item.messages),
    );
    const used = new Set<number>();
    let fallback = 1;
    return valid.map((item) => {
      const numberInTitle = /^会话\s*(\d+)/.exec(item.title)?.[1];
      let sequence = Number.isSafeInteger(item.sequence) && item.sequence > 0
        ? item.sequence
        : Number(numberInTitle) || fallback;
      if (used.has(sequence)) {
        while (used.has(fallback)) fallback += 1;
        sequence = fallback;
      }
      used.add(sequence);
      fallback = Math.max(fallback, sequence + 1);
      const parts = item.title.split("·").map((part) => part.trim());
      const roleLabel = QUERY_PERSPECTIVES[item.queryPerspective].label;
      const question = parts.slice(parts[1] === roleLabel ? 2 : 1).join(" · ");
      return {
        ...item,
        sequence,
        title: `会话 ${sequence} · ${roleLabel}${question ? ` · ${question}` : ""}`,
      };
    });
  } catch {
    return [];
  }
}

function createSessionId() {
  return globalThis.crypto?.randomUUID?.() ?? `session-${Date.now()}`;
}

function allocateSessionNumber(sessions: SavedSession[]) {
  const nextExisting = sessions.reduce((next, session) => Math.max(next, session.sequence + 1), 1);
  let storedNext = 1;
  try {
    storedNext = Number(localStorage.getItem(NEXT_SESSION_NUMBER_KEY)) || 1;
  } catch {
    // The current session can still be numbered from the in-memory archive.
  }
  const sequence = Math.max(nextExisting, storedNext);
  try {
    localStorage.setItem(NEXT_SESSION_NUMBER_KEY, String(sequence + 1));
  } catch {
    // Keep the numbering usable in memory if browser storage is unavailable.
  }
  return sequence;
}

function sessionTitle(sequence: number, perspective: QueryPerspective, question?: string) {
  const prefix = `会话 ${sequence} · ${QUERY_PERSPECTIVES[perspective].label}`;
  return question ? `${prefix} · ${question.slice(0, 26)}` : prefix;
}

function formatSessionDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function shiftDate(date: string, days: number) {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

function latestCompleteWeek() {
  const lastDataDay = shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1);
  const daysSinceSunday = new Date(`${lastDataDay}T00:00:00Z`).getUTCDay();
  const sunday = shiftDate(lastDataDay, -daysSinceSunday);
  return { start: shiftDate(sunday, -6), end: sunday };
}

function latestCompleteMonth() {
  const currentMonthStart = `${ECOMMERCE_DATA_END_EXCLUSIVE.slice(0, 7)}-01`;
  const end = shiftDate(currentMonthStart, -1);
  return { start: `${end.slice(0, 7)}-01`, end };
}

function roleReading(response: TurnResponse, role: QueryPerspective) {
  const dimensions = response.interpretation.dimension_ids.map((dimension) => DIMENSION_LABELS[dimension] ?? dimension);
  if (role === "management") {
    return "先看整体规模和变化方向；这组数据只描述经营表现，不会单凭结果推断变化原因。";
  }
  if (role === "operations") {
    return dimensions.length
      ? `优先比较${dimensions.join("、")}分组结果，找到值得继续跟进的对象；结果本身不代表原因。`
      : "当前是整体汇总。可以继续按商品、类目或渠道拆分，定位运营表现差异。";
  }
  return "先核对下方的指标定义、统计时间和过滤条件，再用表格明细复核结果。";
}

function TrendChart({ rows }: { rows: ResultRow[] }) {
  const points = useMemo(() => {
    const metric = Object.keys(rows[0]?.values ?? {})[0] ?? "sales_amount";
    const values = rows.map((row) => Number(row.values[metric] ?? 0));
    const max = Math.max(...values, 1);
    return values.map((value, index) => ({
      x: 30 + (index * 540) / Math.max(values.length - 1, 1),
      y: 145 - (value / max) * 115,
      value,
      label: rows[index].label.slice(5),
      metric,
    }));
  }, [rows]);
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  return (
    <div className="chart-wrap" role="img" aria-label="最近 7 天销售额折线图">
      <svg viewBox="0 0 600 190" className="trend-chart">
        <line x1="30" y1="150" x2="570" y2="150" className="axis-line" />
        <polyline points={line} className="trend-line" />
        {points.map((point) => (
          <g key={point.label}>
            <circle cx={point.x} cy={point.y} r="4" className="trend-dot" />
            <text x={point.x} y="174" textAnchor="middle" className="chart-label">{point.label}</text>
          </g>
        ))}
      </svg>
      <div className="chart-values">
        {points.map((point) => <span key={point.label}>{formatCell(point.metric, point.value)}</span>)}
      </div>
    </div>
  );
}

const COLUMN_LABELS: Record<string, string> = {
  product_id: "商品编号", sales_amount: "销售额", order_count: "订单数",
  refund_order_count: "退款订单数", refund_rate: "退款订单率",
  average_order_value: "客单价", current_sales: "本期销售额",
  previous_sales: "对比期销售额", change: "变化额",
  order_count_previous: "对比期订单数", order_count_current: "当前期订单数",
  average_order_value_previous: "对比期客单价", average_order_value_current: "当前期客单价",
  sales_amount_delta: "销售额变化", order_count_contribution: "订单数变化贡献",
  aov_contribution: "客单价变化贡献",
  sales_amount_change_rate: "变化率",
  sales_amount_current: "本月销售额", sales_amount_previous: "上月销售额",
  active_subscriptions: "活跃订阅数", mrr: "月度经常性收入（MRR）",
  new_subscriptions: "新增订阅数",
};
const DIMENSION_LABELS: Record<string, string> = {
  order_date: "日期", product: "商品", category: "类目", channel: "渠道",
  plan: "套餐", subscription_date: "订阅开始日期",
};

function presentFilters(filters: string[]) {
  return filters.map((filter) => {
    if (filter.includes("order_status IN") && filter.includes("paid_at IS NOT NULL")) {
      return "仅统计已支付且状态为支付成功或已完成的订单";
    }
    if (filter === "销售额大于 0") return "仅展示销售额大于 0 的商品";
    return filter;
  });
}

function formatCell(key: string, value: string | number | null) {
  if (value === null) return "—";
  if (key === "refund_rate") return String(value);
  if (["sales_amount", "average_order_value", "current_sales", "previous_sales", "change", "sales_amount_delta", "sales_amount_current", "sales_amount_previous", "order_count_contribution", "aov_contribution", "average_order_value_previous", "average_order_value_current", "mrr"].includes(key)) {
    return `¥${Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return typeof value === "number" ? value.toLocaleString("zh-CN") : value;
}

function formatMetricValue(metric: MetricValue) {
  if (metric.value === null) return "—";
  if (metric.unit.startsWith("CNY")) return `¥${Number(metric.value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (metric.unit === "percent") return String(metric.value);
  return typeof metric.value === "number" ? metric.value.toLocaleString("zh-CN") : String(metric.value);
}

function downloadCsv(rows: ResultRow[], keys: string[]) {
  const dynamicLabels = Object.fromEntries(
    rows.filter((row) => keys.includes(row.key)).map((row) => [row.key, row.label]),
  );
  const csv = createResultCsv(rows, keys, { ...COLUMN_LABELS, ...dynamicLabels });
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "chatbi-result.csv";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ResultTable({ rows }: { rows: ResultRow[] }) {
  const [sort, setSort] = useState<ResultTableSort>(null);
  if (rows.length === 0) return <p className="empty-results">没有符合条件的数据。</p>;
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row.values)))].filter((key) => key !== "product_id");
  const sortedRows = sortResultRows(rows, sort);
  function toggleSort(key: string) {
    setSort((current) => ({
      key,
      direction: current?.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }
  function sortableHeading(key: string, label: string) {
    const direction = sort?.key === key ? sort.direction : null;
    return (
      <th key={key} aria-sort={direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none"}>
        <button className="table-sort" type="button" onClick={() => toggleSort(key)}>
          {label}{direction === "asc" ? " ↑" : direction === "desc" ? " ↓" : ""}
        </button>
      </th>
    );
  }
  return (
    <div className="data-table-wrap">
      <div className="table-actions"><button type="button" onClick={() => downloadCsv(sortedRows, keys)}>导出 CSV</button></div>
      <table><thead><tr>{sortableHeading("label", "周期 / 名称")}{keys.map((key) => sortableHeading(key, COLUMN_LABELS[key] ?? key))}</tr></thead>
        <tbody>{sortedRows.map((row) => <tr key={row.key}><td>{row.label}</td>{keys.map((key) => <td key={key}>{formatCell(key, row.values[key] ?? null)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function BarChart({ rows }: { rows: ResultRow[] }) {
  const metric = ["change", "sales_amount", "average_order_value", "order_count", "mrr", "active_subscriptions", "new_subscriptions"].find((key) => rows.some((row) => row.values[key] !== undefined));
  if (!metric || rows.length === 0) return null;
  const numbers = rows.map((row) => Number(row.values[metric] ?? 0));
  const max = Math.max(...numbers.map(Math.abs), 1);
  return <div className="bar-chart" aria-label={`${COLUMN_LABELS[metric] ?? metric}横向柱状图`}>
    {rows.map((row, index) => <div className="bar-row" key={row.key}><span className="bar-label">{row.label}</span><div className="bar-track"><span className={`bar-fill ${numbers[index] < 0 ? "negative" : ""}`} style={{ width: `${Math.max(Math.abs(numbers[index]) / max * 100, 1)}%` }} /></div><span className="bar-value">{formatCell(metric, row.values[metric])}</span></div>)}
  </div>;
}

function ResultCard({ response, mockUserId, sessionId, queryPerspective, onClarificationSubmit, busy }: { response: TurnResponse; mockUserId: string; sessionId: string; queryPerspective: QueryPerspective; onClarificationSubmit: (question: string) => void; busy: boolean }) {
  const perspective = QUERY_PERSPECTIVES[queryPerspective];
  const range = response.interpretation.time_range;
  const [periodStart, setPeriodStart] = useState(() => latestCompleteWeek().start);
  const [periodEnd, setPeriodEnd] = useState(() => latestCompleteWeek().end);
  const [periodError, setPeriodError] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<DebugInfo | null>(null);
  const [debugError, setDebugError] = useState<string | null>(null);
  const [feedbackStatus, setFeedbackStatus] = useState<string | null>(null);
  const [feedbackCategory, setFeedbackCategory] = useState("result");
  const [feedbackRating, setFeedbackRating] = useState<"positive" | "negative" | null>(null);
  async function loadDebug() {
    if (!response.debug_ref || debugInfo || debugError) return;
    try {
      const result = await fetch(`${API}/debug/queries/${response.debug_ref}`, { headers: { "X-Mock-User": mockUserId } });
      if (!result.ok) throw new Error("调试视图已关闭或记录已过期");
      setDebugInfo(await result.json() as DebugInfo);
    } catch (reason: unknown) {
      setDebugError(reason instanceof Error ? reason.message : "无法加载调试信息");
    }
  }
  async function sendFeedback(rating: "positive" | "negative") {
    if (!sessionId || !response.turn_id || mockUserId === "viewer") return;
    setFeedbackRating(rating);
    setFeedbackStatus(null);
    try {
      const result = await fetch(`${API}/sessions/${sessionId}/turns/${response.turn_id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Mock-User": mockUserId },
        body: JSON.stringify({ rating, category: rating === "positive" ? "looks_good" : feedbackCategory }),
      });
      if (!result.ok) throw new Error("反馈保存失败");
      setFeedbackStatus("已记录反馈");
    } catch (reason: unknown) {
      setFeedbackStatus(reason instanceof Error ? reason.message : "反馈保存失败");
    }
  }
  const isPeriodComparisonClarification = response.status === "clarification_required"
    && (
      ["order_count", "sales_amount", "average_order_value"].every((metricId) =>
        response.interpretation.metric_ids.includes(metricId),
      )
      || response.clarification_prompt?.includes("两个需要比较的完整日期区间") === true
    );
  const isDateRangeClarification = response.status === "clarification_required"
    && !isPeriodComparisonClarification
    && /时间范围|日期范围|自然日时间范围/.test(response.clarification_prompt ?? "");
  function submitPeriod(start: string, end: string) {
    if (!start || !end || start > end) {
      setPeriodError("请选择有效的开始和结束日期。");
      return;
    }
    const days = Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1;
    const previousStart = shiftDate(start, -days);
    if (days > 366 || previousStart < ECOMMERCE_DATA_START || end >= ECOMMERCE_DATA_END_EXCLUSIVE) {
      setPeriodError(`本次和对比周期都需要落在数据范围 ${ECOMMERCE_DATA_START} 至 ${shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)} 内，请缩短或调整日期。`);
      return;
    }
    setPeriodError(null);
    const previousEnd = shiftDate(start, -1);
    onClarificationSubmit(`比较 ${start} 至 ${end} 和 ${previousStart} 至 ${previousEnd}`);
  }
  function submitDateRange(start: string, end: string) {
    if (!start || !end || start > end) {
      setPeriodError("请选择有效的开始和结束日期。");
      return;
    }
    const days = Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1;
    if (days > 366 || start < ECOMMERCE_DATA_START || end >= ECOMMERCE_DATA_END_EXCLUSIVE) {
      setPeriodError(`日期需在 Mock 数据范围 ${ECOMMERCE_DATA_START} 至 ${shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)} 内，且不超过 366 天。`);
      return;
    }
    setPeriodError(null);
    onClarificationSubmit(`${start} 至 ${end}`);
  }
  return (
    <article className="answer-card">
      <div className={`answer-perspective answer-perspective-${queryPerspective}`}><strong>{perspective.label}关注重点（演示）</strong><span>{perspective.answerFocus}</span><small>演示角色只调整关注重点，不代表真实权限；查询口径和数据结果保持一致。</small></div>
      <p className={`answer-copy status-${response.status}`}>{response.answer_text}</p>
      {response.status === "completed" && <div className={`role-reading role-reading-${queryPerspective}`}><strong>{perspective.label}解读重点</strong><span>{roleReading(response, queryPerspective)}</span></div>}
      {response.values.length > 0 && (
        <div className="metric-grid">
          {response.values.map((metric) => (
            <div className="metric-card" key={metric.metric_id}>
              <span className="metric-label">{metric.label}</span>
              <strong>{formatMetricValue(metric)}</strong>
              <small>{metric.definition}</small>
            </div>
          ))}
        </div>
      )}
      {response.visualization.type === "line" && <TrendChart rows={response.visualization.data} />}
      {response.visualization.type === "line" && <ResultTable rows={response.visualization.data} />}
      {response.visualization.type === "bar" && <BarChart rows={response.visualization.data} />}
      {["bar", "table"].includes(response.visualization.type) && <ResultTable rows={response.visualization.data} />}
      {response.clarification_prompt && <p className="clarification-prompt">{response.clarification_prompt}</p>}
      {isPeriodComparisonClarification && <section className="period-chooser" aria-label="选择比较日期">
        <p>不确定选哪周？可直接用最近一个完整周，或自行选择日期；系统会自动比较紧邻的前一段同长度周期。</p>
        <button type="button" className="period-preset" disabled={busy} onClick={() => {
          const week = latestCompleteWeek();
          submitPeriod(week.start, week.end);
        }}>比较最近完整周（周一至周日：{latestCompleteWeek().start} 至 {latestCompleteWeek().end}）</button>
        <div className="period-date-fields">
          <label>开始日期<input type="date" min={ECOMMERCE_DATA_START} max={shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)} value={periodStart} disabled={busy} onChange={(event) => setPeriodStart(event.target.value)} /></label>
          <label>结束日期<input type="date" min={ECOMMERCE_DATA_START} max={shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)} value={periodEnd} disabled={busy} onChange={(event) => setPeriodEnd(event.target.value)} /></label>
          <button type="button" disabled={busy} onClick={() => submitPeriod(periodStart, periodEnd)}>{busy ? "查询中…" : "比较所选周期"}</button>
        </div>
        <small>Mock 数据范围：{ECOMMERCE_DATA_START} 至 {shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)}；自选周期需与前一周期都在范围内。</small>
        {periodError && <small className="period-error" role="alert">{periodError}</small>}
      </section>}
      {isDateRangeClarification && <section className="period-chooser" aria-label="选择查询日期">
        <p>可以点选常用周期，也可以手动选起止日期（结束日包含在统计范围内）。</p>
        <div className="period-presets">
          {(() => {
            const lastDay = shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1);
            const completeWeek = latestCompleteWeek();
            const completeMonth = latestCompleteMonth();
            return [
              { label: "昨天", start: lastDay, end: lastDay },
              { label: "最近 7 天", start: shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -7), end: lastDay },
              { label: "最近 30 天", start: shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -30), end: lastDay },
              { label: "最近完整周", ...completeWeek },
              { label: "最近完整月", ...completeMonth },
            ].map((preset) => <button key={preset.label} type="button" disabled={busy} onClick={() => submitDateRange(preset.start, preset.end)}>{preset.label}{preset.label === "最近完整周" ? `（${preset.start} 至 ${preset.end}）` : ""}</button>);
          })()}
        </div>
        <div className="period-date-fields">
          <label>开始日期<input type="date" min={ECOMMERCE_DATA_START} max={shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)} value={periodStart} disabled={busy} onChange={(event) => setPeriodStart(event.target.value)} /></label>
          <label>结束日期<input type="date" min={ECOMMERCE_DATA_START} max={shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)} value={periodEnd} disabled={busy} onChange={(event) => setPeriodEnd(event.target.value)} /></label>
          <button type="button" disabled={busy} onClick={() => submitDateRange(periodStart, periodEnd)}>{busy ? "查询中…" : "查询所选日期"}</button>
        </div>
        <small>Mock 数据范围：{ECOMMERCE_DATA_START} 至 {shiftDate(ECOMMERCE_DATA_END_EXCLUSIVE, -1)}。</small>
        {periodError && <small className="period-error" role="alert">{periodError}</small>}
      </section>}
      {response.suggested_terms.length > 0 && <p className="suggestions">可尝试：{response.suggested_terms.join(" · ")}</p>}
      {response.status === "completed" && mockUserId !== "viewer" && <section className="feedback-controls" aria-label="答案反馈">
        <span>这条回答有帮助吗？</span>
        <button type="button" aria-pressed={feedbackRating === "positive"} onClick={() => void sendFeedback("positive")}>有帮助</button>
        <button type="button" aria-pressed={feedbackRating === "negative"} onClick={() => setFeedbackRating("negative")}>需改进</button>
        {feedbackRating === "negative" && <label>问题类别<select value={feedbackCategory} onChange={(event) => setFeedbackCategory(event.target.value)}>
          <option value="understanding">问题理解</option><option value="metric_definition">指标口径</option><option value="filter">筛选条件</option><option value="result">结果</option><option value="chart">图表</option><option value="other">其他</option>
        </select><button type="button" onClick={() => void sendFeedback("negative")}>提交分类</button></label>}
        {feedbackStatus && <small role="status">{feedbackStatus}</small>}
      </section>}
      <section className="evidence-block">
        <h3>解析与查询条件</h3>
        <dl>
          <dt>指标</dt><dd>{response.values.length ? response.values.map((value) => value.label).join("、") : response.interpretation.metric_ids.map((metric) => COLUMN_LABELS[metric] ?? metric).join("、") || "未识别"}</dd>
          <dt>分组维度</dt><dd>{response.interpretation.dimension_ids.map((dimension) => DIMENSION_LABELS[dimension] ?? dimension).join("、") || "无"}</dd>
          <dt>时间范围</dt><dd>{range ? `${range.start_inclusive} 至 ${range.end_exclusive}（不含结束日，${range.timezone}）` : response.status === "clarification_required" ? "待补充" : "未识别"}</dd>
          <dt>过滤条件</dt><dd>{presentFilters(response.interpretation.filters).join("；") || "无"}</dd>
          <dt>数据集</dt><dd>{response.evidence.dataset_id} v{response.evidence.dataset_version} · Mock</dd>
        </dl>
      </section>
      {!PUBLIC_DEMO && mockUserId !== "viewer" && <details className="debug-details">
        <summary onClick={() => void loadDebug()}>验收 / 调试信息</summary>
        {!debugInfo && !debugError && <p>打开后从本地调试接口加载。</p>}
        {debugError && <p>{debugError}</p>}
        {debugInfo && <>
          <p>模板：{debugInfo.template_id} · 是否执行查询：{debugInfo.query_executed ? "是" : "否"} · 返回行数：{debugInfo.result_row_count}{debugInfo.duration_ms === null ? "" : ` · ${debugInfo.duration_ms} ms`}</p>
          {debugInfo.sql && <pre>{debugInfo.sql}{"\n\n参数："}{JSON.stringify(debugInfo.parameters, null, 2)}</pre>}
        </>}
        <small>Request ID：{response.request_id}</small>
      </details>}
    </article>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthState>("checking");
  const [sessionArchive, setSessionArchive] = useState<SavedSession[]>(readSavedSessions);
  const [activeLocalSessionId, setActiveLocalSessionId] = useState<string | null>(() => {
    const saved = readSavedSessions();
    const storedId = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    return saved.some((session) => session.id === storedId) ? storedId : saved[0]?.id ?? null;
  });
  const initialSession = sessionArchive.find((session) => session.id === activeLocalSessionId);
  const [datasetId, setDatasetId] = useState<"ecommerce_mock_v1" | "saas_subscription_mock_v1">(initialSession?.datasetId ?? "ecommerce_mock_v1");
  const mockUserId = DEMO_API_IDENTITY;
  const [queryPerspective, setQueryPerspective] = useState<QueryPerspective>(initialSession?.queryPerspective ?? "management");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>(initialSession?.messages ?? []);
  const [pendingClarificationId, setPendingClarificationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [healthCheckKey, setHealthCheckKey] = useState(0);
  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackSummary | null>(null);
  const [feedbackSummaryError, setFeedbackSummaryError] = useState<string | null>(null);
  const [semanticGuide, setSemanticGuide] = useState<SemanticGuide | null>(null);
  const [semanticGuideLoading, setSemanticGuideLoading] = useState(false);
  const [semanticGuideError, setSemanticGuideError] = useState<string | null>(null);
  const initialSessionBootstrap = useRef(false);
  const conversationRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeLocalSessionId || initialSessionBootstrap.current) return;
    initialSessionBootstrap.current = true;
    const id = createSessionId();
    const sequence = allocateSessionNumber(sessionArchive);
    const now = new Date().toISOString();
    setSessionArchive((current) => [{ id, sequence, title: sessionTitle(sequence, queryPerspective), datasetId, queryPerspective, createdAt: now, updatedAt: now, messages: [] }, ...current]);
    setActiveLocalSessionId(id);
  }, [activeLocalSessionId]);

  useEffect(() => {
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sessionArchive));
    } catch {
      // Keep the current in-memory conversations usable if browser storage is full.
    }
  }, [sessionArchive]);

  useEffect(() => {
    try {
      if (activeLocalSessionId) localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, activeLocalSessionId);
    } catch {
      // Session selection still works in memory if browser storage is unavailable.
    }
  }, [activeLocalSessionId]);

  useEffect(() => {
    if (!activeLocalSessionId) return;
    setSessionArchive((current) => current.map((session) => {
      if (session.id !== activeLocalSessionId) return session;
      const firstQuestion = messages.find((message) => message.question.trim())?.question.trim();
      return {
        ...session,
        title: sessionTitle(session.sequence, session.queryPerspective, firstQuestion),
        datasetId,
        queryPerspective,
        messages,
        updatedAt: new Date().toISOString(),
      };
    }).sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)));
  }, [messages, activeLocalSessionId]);

  useEffect(() => {
    const conversation = conversationRef.current;
    if (!conversation) return;
    const frame = requestAnimationFrame(() => {
      conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [messages]);

  useEffect(() => {
    const controller = new AbortController();
    setHealth("checking");
    setSessionId(null);
    if (!activeLocalSessionId) return () => controller.abort();
    fetch(`${API}/health/ready`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("API 或本地 Mock 数据库未就绪");
        const healthPayload = await response.json() as { status: string };
        if (healthPayload.status !== "ready") throw new Error("API 尚未就绪");
        const sessionResponse = await fetch(`${API}/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Mock-User": mockUserId },
          body: JSON.stringify({ dataset_id: datasetId }),
          signal: controller.signal,
        });
        if (!sessionResponse.ok) throw new Error("无法创建问数会话");
        const session = await sessionResponse.json() as { session_id: string };
        setSessionId(session.session_id);
        setHealth("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setHealth("unavailable");
        }
      });
    return () => controller.abort();
  }, [datasetId, activeLocalSessionId, mockUserId, healthCheckKey]);

  const perspective = QUERY_PERSPECTIVES[queryPerspective];
  const examples = datasetId === "ecommerce_mock_v1" ? perspective.ecommerce : SAAS_EXAMPLES;
  const topicLabel = datasetId === "ecommerce_mock_v1" ? "电商经营问数" : "SaaS 订阅经营问数";
  const activeSession = sessionArchive.find((session) => session.id === activeLocalSessionId);

  function startNewSession(nextPerspective = queryPerspective, nextDataset = datasetId) {
    const id = createSessionId();
    const sequence = allocateSessionNumber(sessionArchive);
    const now = new Date().toISOString();
    setSessionArchive((current) => [{
      id,
      sequence,
      title: sessionTitle(sequence, nextPerspective),
      datasetId: nextDataset,
      queryPerspective: nextPerspective,
      createdAt: now,
      updatedAt: now,
      messages: [],
    }, ...current]);
    setActiveLocalSessionId(id);
    setDatasetId(nextDataset);
    setQueryPerspective(nextPerspective);
    setSessionId(null);
    setMessages([]);
    setQuestion("");
    setPendingClarificationId(null);
    setHealth("checking");
  }

  function switchPerspective(nextPerspective: QueryPerspective) {
    if (nextPerspective === queryPerspective) return;
    if (messages.length > 0) {
      startNewSession(nextPerspective);
      return;
    }

    // An empty conversation is still useful as the active draft. Reuse it when
    // changing the demo perspective so role changes do not accumulate blanks.
    setQueryPerspective(nextPerspective);
    setSessionArchive((current) => current.map((session) => {
      if (session.id !== activeLocalSessionId) return session;
      return {
        ...session,
        queryPerspective: nextPerspective,
        title: sessionTitle(session.sequence, nextPerspective),
        updatedAt: new Date().toISOString(),
      };
    }));
    setQuestion("");
    setPendingClarificationId(null);
  }

  function switchSession(id: string) {
    const saved = sessionArchive.find((session) => session.id === id);
    if (!saved || saved.id === activeLocalSessionId) return;
    setActiveLocalSessionId(saved.id);
    setDatasetId(saved.datasetId);
    setQueryPerspective(saved.queryPerspective);
    setSessionId(null);
    setMessages(saved.messages);
    setQuestion("");
    setPendingClarificationId(null);
    setHealth("checking");
  }

  function deleteActiveSession() {
    if (!activeSession || !window.confirm(`删除会话“${activeSession.title}”及其本地历史记录？此操作无法撤销。`)) return;
    const remaining = sessionArchive.filter((session) => session.id !== activeSession.id);
    setSessionArchive(remaining);
    if (remaining.length > 0) switchSession(remaining[0].id);
    else {
      setActiveLocalSessionId(null);
      setSessionId(null);
      setMessages([]);
      setQuestion("");
      setPendingClarificationId(null);
      setHealth("checking");
    }
  }

  async function loadFeedbackSummary() {
    setFeedbackSummaryError(null);
    try {
      const response = await fetch(`${API}/feedback/summary`, { headers: { "X-Mock-User": DEMO_ADMIN_API_IDENTITY } });
      if (!response.ok) throw new Error("无法读取反馈汇总");
      setFeedbackSummary(await response.json() as FeedbackSummary);
    } catch (reason: unknown) {
      setFeedbackSummaryError(reason instanceof Error ? reason.message : "无法读取反馈汇总");
    }
  }

  async function loadSemanticGuide() {
    if (semanticGuide?.dataset_id === datasetId || semanticGuideLoading) return;
    setSemanticGuideLoading(true);
    setSemanticGuideError(null);
    try {
      const response = await fetch(`${API}/semantics?dataset_id=${encodeURIComponent(datasetId)}`, {
        headers: { "X-Mock-User": mockUserId },
      });
      if (!response.ok) throw new Error("暂时无法读取指标口径，请稍后重试。");
      setSemanticGuide(await response.json() as SemanticGuide);
    } catch (reason: unknown) {
      setSemanticGuideError(reason instanceof Error ? reason.message : "暂时无法读取指标口径。");
    } finally {
      setSemanticGuideLoading(false);
    }
  }

  async function submitQuestion(value = question, retryIndex: number | null = null, displayQuestion?: string, dateContext?: string, answerPerspective: QueryPerspective = queryPerspective) {
    const text = value.trim();
    if (!text || !sessionId || busy) return;
    const targetIndex = retryIndex ?? messages.length;
    if (retryIndex === null) setQuestion("");
    setBusy(true);
    setMessages((current) => retryIndex === null
      ? [...current, { question: displayQuestion ?? text, requestQuestion: text, dateContext, queryPerspective: answerPerspective }]
      : current.map((message, index) => index === targetIndex ? { ...message, question: displayQuestion ?? text, requestQuestion: text, dateContext, queryPerspective: answerPerspective } : message));
    try {
      let activeSessionId = sessionId;
      let response = await fetch(`${API}/sessions/${activeSessionId}/turns`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Mock-User": mockUserId },
        body: JSON.stringify({ question: text, clarifies_turn_id: pendingClarificationId }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: string } | null;
        if (response.status === 404 && body?.detail === "Session not found.") {
          const sessionResponse = await fetch(`${API}/sessions`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Mock-User": mockUserId },
            body: JSON.stringify({ dataset_id: datasetId }),
          });
          if (!sessionResponse.ok) throw new Error("会话已失效，且无法创建新会话，请刷新页面后重试。");
          const session = await sessionResponse.json() as { session_id: string };
          activeSessionId = session.session_id;
          setSessionId(activeSessionId);
          setPendingClarificationId(null);
          response = await fetch(`${API}/sessions/${activeSessionId}/turns`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Mock-User": mockUserId },
            body: JSON.stringify({ question: text }),
          });
        }
        if (!response.ok) {
          const retryBody = await response.json().catch(() => null) as { detail?: string } | null;
          throw new Error(retryBody?.detail ?? `请求失败（${response.status}）`);
        }
      }
      const result = await response.json() as TurnResponse;
      setPendingClarificationId(result.status === "clarification_required" ? result.clarification_id : null);
      setMessages((current) => current.map((message, index) => index === targetIndex ? { ...message, response: result } : message));
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "查询失败，请稍后重试。";
      setMessages((current) => current.map((entry, index) => index === targetIndex ? { ...entry, error: message } : entry));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitQuestion();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (question.trim()) void submitQuestion();
    }
  }

  function removeMessage(index: number) {
    const message = messages[index];
    if (!message || busy) return;
    const confirmed = window.confirm("确定从当前页面移除这条提问和对应回答吗？后台历史记录不会被删除。");
    if (!confirmed) return;
    setMessages((current) => current.filter((_, currentIndex) => currentIndex !== index));
    if (message.response?.status === "clarification_required") setPendingClarificationId(null);
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="ChatBI 首页"><span className="brand-mark">C</span><span>ChatBI</span></a>
        <a className="product-intro-link" href={PRODUCT_INTRO_URL}>产品介绍 <span aria-hidden="true">↗</span></a>
        <label className="dataset-picker">业务主题
          <select value={datasetId} disabled={busy} onChange={(event) => {
            const next = event.target.value as typeof datasetId;
            startNewSession(queryPerspective, next);
          }}>
            <option value="ecommerce_mock_v1">电商</option>
            <option value="saas_subscription_mock_v1">SaaS 订阅</option>
          </select>
        </label>
        <label className="dataset-picker perspective-picker">演示角色
          <select value={queryPerspective} disabled={busy} onChange={(event) => switchPerspective(event.target.value as QueryPerspective)}>
            <option value="management">管理者</option>
            <option value="operations">运营/产品经理</option>
            <option value="analyst">数据分析师</option>
          </select>
        </label>
        {!PUBLIC_DEMO && <details className="feedback-summary" onToggle={(event) => {
          if ((event.currentTarget as HTMLDetailsElement).open) void loadFeedbackSummary();
        }}>
          <summary>演示反馈汇总（开发用）</summary>
          {feedbackSummaryError && <small role="status">{feedbackSummaryError}</small>}
          {feedbackSummary && <div><strong>共 {feedbackSummary.total} 条</strong>{feedbackSummary.counts.map((item) => <span key={`${item.rating}-${item.category}`}>{item.rating === "positive" ? "有帮助" : "需改进"} · {item.category}: {item.count}</span>)}</div>}
        </details>}
        <span className="mock-badge">{PUBLIC_DEMO ? "公开演示 · 演示角色不代表真实权限 · 仅 Mock 数据" : "演示角色不代表真实权限 · 仅 Mock 数据"}</span>
      </header>
      <section className={`workspace${messages.length > 0 ? " has-messages" : ""}`} aria-labelledby="welcome-title">
        <div className="session-manager" aria-label="会话管理">
          <label>会话历史
            <select value={activeLocalSessionId ?? ""} onChange={(event) => switchSession(event.target.value)} disabled={busy || sessionArchive.length === 0}>
              {sessionArchive.length === 0 && <option value="">暂无会话</option>}
              {sessionArchive.map((session) => <option key={session.id} value={session.id}>{session.title} · {formatSessionDate(session.updatedAt)}</option>)}
            </select>
          </label>
          <button type="button" onClick={() => startNewSession()} disabled={busy}>＋ 新建会话</button>
          <button type="button" className="delete-session-button" onClick={deleteActiveSession} disabled={busy || !activeSession}>删除当前会话</button>
          <small>历史保存在当前浏览器</small>
        </div>
        <details className="semantic-guide" onToggle={(event) => {
          if ((event.currentTarget as HTMLDetailsElement).open) void loadSemanticGuide();
        }}>
          <summary>指标口径速查 <span>查看当前数据集支持的指标、说法和分组维度</span></summary>
          {semanticGuideLoading && <p role="status">正在读取指标目录…</p>}
          {semanticGuideError && <p className="semantic-guide-error" role="alert">{semanticGuideError} <button type="button" onClick={() => void loadSemanticGuide()}>重试</button></p>}
          {semanticGuide?.dataset_id === datasetId && <>
            <p className="semantic-guide-meta">目录 v{semanticGuide.version} · 数据范围 {semanticGuide.date_window.start_inclusive} 至 {shiftDate(semanticGuide.date_window.end_exclusive, -1)} · {semanticGuide.timezone}</p>
            <div className="semantic-guide-grid">
              {semanticGuide.metrics.map((metric) => <article key={metric.id}>
                <strong>{metric.label}</strong><small>{metric.definition}</small>
                <span>常见说法：{metric.aliases.length ? metric.aliases.join("、") : "标准名称"}</span>
                <span>可按：{metric.dimensions.length ? metric.dimensions.join("、") : "整体汇总"}</span>
              </article>)}
            </div>
            {semanticGuide.ambiguous_terms.length > 0 && <div className="semantic-ambiguities"><strong>需要先确认的说法</strong>{semanticGuide.ambiguous_terms.map((term) => <p key={term.text}><b>{term.text}</b>：{term.note}</p>)}</div>}
          </>}
        </details>
        <div className={`landing-hero${messages.length > 0 ? " has-conversation" : ""}`}>
        <div className={`workspace-heading${messages.length > 0 ? " is-collapsed" : ""}`}>
          <div className="eyebrow">{topicLabel} · 确定性 MVP</div>
          <h1 id="welcome-title">让经营数据，<span>更容易问清楚。</span></h1>
          <p className="intro">直接提问，查看结果、指标口径和查询条件。暂不支持的问题会明确提示。</p>
          <div className={`status-row${health === "unavailable" ? " is-unavailable" : ""}`} role="status"><span className={`status-dot ${health}`} aria-hidden="true" /><span>{health === "checking" ? "正在连接问数服务" : health === "ready" ? "问数服务已就绪" : "问数服务暂时不可用"}</span>{health === "unavailable" && <button type="button" className="connection-retry" onClick={() => setHealthCheckKey((current) => current + 1)}>重试</button>}</div>
        </div>
        {messages.length === 0 && (
          <div className="empty-state">
            <span className="empty-icon" aria-hidden="true">✳</span>
            <h2>从一个具体问题开始</h2>
            <p className="perspective-focus"><strong>{perspective.label}视角：</strong>{perspective.focus} 角色仅调整示例与回答重点，不代表真实权限，也不改变指标口径或查询结果。</p>
            <form className="composer composer-empty" onSubmit={onSubmit}>
              <label className="question-label" htmlFor="question-input">想看看什么经营数据？我来帮你查查</label>
              <div className="question-box"><textarea id="question-input" rows={1} maxLength={1000} placeholder={datasetId === "ecommerce_mock_v1" ? "例如：本月和上月的销售额差多少？" : "例如：按套餐看看活跃订阅数？"} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} disabled={busy || health !== "ready"} /><button type="submit" aria-label={busy ? "正在查询" : "发送问题"} title={busy ? "正在查询" : "发送问题"} disabled={busy || health !== "ready" || !question.trim()}><svg className="send-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 11.2 19 4.8l-4.7 14.4-3.1-5.8-6.7-2.2Z" /><path d="m11.2 13.4 4.2-4.2" /></svg></button></div>
              <p className="composer-hint">Enter 发送 · Shift + Enter 换行</p>
            </form>
            <div className="example-list">{examples.map((example) => <button type="button" key={example} onClick={() => void submitQuestion(example)} disabled={health !== "ready" || busy}>{example}<span>→</span></button>)}</div>
            <p className="empty-mock-note">Mock 演示数据 · 快照日 2026-08-01 · 不代表真实经营结果</p>
          </div>
        )}
        </div>
        {messages.length > 0 && <div className="data-notice" role="note"><strong>Mock 演示数据</strong><span>快照日 2026-08-01（Asia/Shanghai）；数据日期覆盖 2025-08-01 至 2026-07-31，不代表真实经营结果。</span></div>}
        {messages.length > 0 && (
          <div className="conversation" aria-live="polite" ref={conversationRef}>
            <div className="conversation-toolbar"><span>本次会话 · {messages.length} 个问题</span><span>{perspective.label}视角</span></div>
            <section className="role-question-prompts" aria-label={`${perspective.label}示例问法`}>
              <div><strong>{perspective.label}还可以这样问</strong><small>角色改变分析重点，不改变指标口径和查询数值。</small></div>
              <div>{examples.map((example) => <button key={example} type="button" disabled={busy || health !== "ready"} onClick={() => void submitQuestion(example)}>{example}<span>→</span></button>)}</div>
            </section>
            {messages.map((message, index) => <div className="turn" key={`${index}-${message.question}`}><div className="user-turn"><div className="user-question"><div className="user-message-copy"><p>{message.question}</p>{message.dateContext && <small className="user-date-context">{message.dateContext.startsWith("比较") ? message.dateContext : `日期范围：${message.dateContext}`}</small>}</div><span className="avatar user-avatar">我</span></div><div className="user-turn-actions"><button className="delete-turn" type="button" onClick={() => removeMessage(index)} disabled={busy} aria-label="删除这条提问" title="删除这条提问"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M10 11v6m4-6v6M5.5 7l1 13h11l1-13M9 7V4h6v3" /></svg></button></div></div>{message.response ? <div className="assistant-answer"><span className="avatar bot-avatar">C</span><ResultCard response={message.response} mockUserId={mockUserId} sessionId={sessionId ?? ""} queryPerspective={message.queryPerspective ?? queryPerspective} busy={busy} onClarificationSubmit={(clarification) => void submitQuestion(`${message.question} ${clarification}`, null, message.question, clarification, message.queryPerspective ?? queryPerspective)} /></div> : message.error ? <div className="assistant-answer"><span className="avatar bot-avatar">C</span><div className="request-error"><p>{message.error}</p><small>请检查服务状态或网络后重试，也可以修改问题再提交。</small><button type="button" onClick={() => void submitQuestion(message.requestQuestion ?? message.question, index, message.question, message.dateContext, message.queryPerspective ?? queryPerspective)} disabled={busy || health !== "ready"}>重试这条问题</button></div></div> : <div className="assistant-answer"><span className="avatar bot-avatar">C</span><p className="pending">正在按确定性规则查询<span className="loading-dots" aria-hidden="true"><i>.</i><i>.</i><i>.</i></span></p></div>}</div>)}
          </div>
        )}
        {messages.length > 0 && <form className="composer composer-followup" onSubmit={onSubmit}>
          <label className="question-label" htmlFor="question-input">想看看什么经营数据？我来帮你查查</label>
          <div className="question-box"><textarea id="question-input" rows={1} maxLength={1000} placeholder={datasetId === "ecommerce_mock_v1" ? "例如：本月和上月的销售额差多少？" : "例如：按套餐看看活跃订阅数？"} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} disabled={busy || health !== "ready"} /><button type="submit" aria-label={busy ? "正在查询" : "发送问题"} title={busy ? "正在查询" : "发送问题"} disabled={busy || health !== "ready" || !question.trim()}><svg className="send-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 11.2 19 4.8l-4.7 14.4-3.1-5.8-6.7-2.2Z" /><path d="m11.2 13.4 4.2-4.2" /></svg></button></div>
          <p className="composer-hint">Enter 发送 · Shift + Enter 换行 · 查询完成或报错后可继续提问</p>
        </form>}
      </section>
      {messages.length > 0 && <footer>固定 {datasetId === "ecommerce_mock_v1" ? "电商" : "SaaS 订阅"} Mock 数据 · 快照日 2026-08-01 · 不代表真实经营结果</footer>}
    </main>
  );
}
