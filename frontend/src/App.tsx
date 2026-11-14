import { useEffect, useMemo, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { createResultCsv, sortResultRows } from "./resultTable.mjs";
import type { ResultTableSort } from "./resultTable.mjs";

type HealthState = "checking" | "ready" | "unavailable";
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
type Message = { question: string; response?: TurnResponse; error?: string };
type FeedbackSummary = { total: number; counts: { rating: string; category: string; count: number }[] };

const API_BASE = (import.meta.env.VITE_CHATBI_API_BASE_URL || "http://127.0.0.1:8000")
  .replace(/\/$/, "");
const API = `${API_BASE}/api/v1`;
const PUBLIC_DEMO = import.meta.env.VITE_CHATBI_PUBLIC_DEMO === "true";
const ECOMMERCE_EXAMPLES = ["昨天的销售额和订单数是多少？", "最近 7 天每天销售额趋势如何？", "最近 30 天退款率最高的商品有哪些？"];
const SAAS_EXAMPLES = ["当前有多少活跃订阅？", "当前 MRR 是多少？", "最近 7 天新增订阅数"];

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
  const csv = createResultCsv(rows, keys, COLUMN_LABELS);
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
      <table><thead><tr>{sortableHeading("label", "名称")}{keys.map((key) => sortableHeading(key, COLUMN_LABELS[key] ?? key))}</tr></thead>
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

function ResultCard({ response, mockUserId, sessionId }: { response: TurnResponse; mockUserId: string; sessionId: string }) {
  const range = response.interpretation.time_range;
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
  return (
    <article className="answer-card">
      <p className={`answer-copy status-${response.status}`}>{response.answer_text}</p>
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
  const [datasetId, setDatasetId] = useState<"ecommerce_mock_v1" | "saas_subscription_mock_v1">("ecommerce_mock_v1");
  const [mockUserId, setMockUserId] = useState<"admin" | "analyst" | "viewer">("analyst");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingClarificationId, setPendingClarificationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [healthCheckKey, setHealthCheckKey] = useState(0);
  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackSummary | null>(null);
  const [feedbackSummaryError, setFeedbackSummaryError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setHealth("checking");
    setError(null);
    setSessionId(null);
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
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setHealth("unavailable");
          setError(reason instanceof Error ? reason.message : "连接 API 失败");
        }
      });
    return () => controller.abort();
  }, [datasetId, mockUserId, healthCheckKey]);

  const examples = datasetId === "ecommerce_mock_v1" ? ECOMMERCE_EXAMPLES : SAAS_EXAMPLES;
  const topicLabel = datasetId === "ecommerce_mock_v1" ? "电商经营问数" : "SaaS 订阅经营问数";

  async function loadFeedbackSummary() {
    setFeedbackSummaryError(null);
    try {
      const response = await fetch(`${API}/feedback/summary`, { headers: { "X-Mock-User": mockUserId } });
      if (!response.ok) throw new Error("无法读取反馈汇总");
      setFeedbackSummary(await response.json() as FeedbackSummary);
    } catch (reason: unknown) {
      setFeedbackSummaryError(reason instanceof Error ? reason.message : "无法读取反馈汇总");
    }
  }

  async function submitQuestion(value = question, retryIndex: number | null = null) {
    const text = value.trim();
    if (!text || !sessionId || busy) return;
    const targetIndex = retryIndex ?? messages.length;
    if (retryIndex === null) setQuestion("");
    setBusy(true);
    setError(null);
    setMessages((current) => retryIndex === null
      ? [...current, { question: text }]
      : current.map((message, index) => index === targetIndex ? { question: text } : message));
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

  function resetConversation() {
    setMessages([]);
    setQuestion("");
    setPendingClarificationId(null);
    setError(null);
    setHealthCheckKey((current) => current + 1);
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
        <label className="dataset-picker">业务主题
          <select value={datasetId} disabled={busy} onChange={(event) => {
            const next = event.target.value as typeof datasetId;
            if (mockUserId === "viewer" && next === "saas_subscription_mock_v1") {
              setError("只读演示身份仅有电商数据范围");
              return;
            }
            setHealth("checking");
            setDatasetId(next);
            setMessages([]);
            setPendingClarificationId(null);
            setError(null);
          }}>
            <option value="ecommerce_mock_v1">电商</option>
            <option value="saas_subscription_mock_v1">SaaS 订阅</option>
          </select>
        </label>
        <label className="dataset-picker">演示身份
          <select value={mockUserId} disabled={busy} onChange={(event) => {
            const next = event.target.value as typeof mockUserId;
            setHealth("checking");
            setMockUserId(next);
            setMessages([]);
            setPendingClarificationId(null);
            setError(null);
          }}>
            <option value="admin">管理员（Mock）</option>
            <option value="analyst">分析者（Mock）</option>
            <option value="viewer">只读者（Mock）</option>
          </select>
        </label>
        {!PUBLIC_DEMO && mockUserId === "admin" && <details className="feedback-summary" onToggle={(event) => {
          if ((event.currentTarget as HTMLDetailsElement).open) void loadFeedbackSummary();
        }}>
          <summary>反馈汇总</summary>
          {feedbackSummaryError && <small role="status">{feedbackSummaryError}</small>}
          {feedbackSummary && <div><strong>共 {feedbackSummary.total} 条</strong>{feedbackSummary.counts.map((item) => <span key={`${item.rating}-${item.category}`}>{item.rating === "positive" ? "有帮助" : "需改进"} · {item.category}: {item.count}</span>)}</div>}
        </details>}
        <span className="mock-badge">{PUBLIC_DEMO ? "公开演示 · 角色仅模拟权限 · 仅 Mock 数据" : "仅 Mock 数据"}</span>
      </header>
      <section className={`workspace${messages.length > 0 ? " has-messages" : ""}`} aria-labelledby="welcome-title">
        <div className={`workspace-heading${messages.length > 0 ? " is-collapsed" : ""}`}>
          <div className="eyebrow">{topicLabel} · 确定性 MVP</div>
          <h1 id="welcome-title">让经营数据，<span>更容易问清楚。</span></h1>
          <p className="intro">直接提问，查看结果、指标口径和查询条件。暂不支持的问题会明确提示。</p>
          <div className="status-row"><span className={`status-dot ${health}`} /><span>{health === "checking" ? "正在连接问数服务" : health === "ready" ? "问数服务已就绪" : error ?? "服务不可用"}</span>{health === "unavailable" && <button type="button" className="connection-retry" onClick={() => setHealthCheckKey((current) => current + 1)}>重新连接</button>}</div>
        </div>
        {messages.length > 0 && <div className="data-notice" role="note"><strong>Mock 演示数据</strong><span>快照日 2026-08-01（Asia/Shanghai）；数据日期覆盖 2025-08-01 至 2026-07-31，不代表真实经营结果。</span></div>}
        {messages.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon" aria-hidden="true">✳</span>
            <h2>从一个具体问题开始</h2>
            <p>{datasetId === "ecommerce_mock_v1" ? "可从销售汇总、近 7 天趋势或近 30 天商品退款订单率开始。" : "当前支持活跃订阅快照、MRR 与新增订阅数；周期指标需要明确时间范围。"}</p>
            <form className="composer composer-empty" onSubmit={onSubmit}>
              <label className="question-label" htmlFor="question-input">想看看什么经营数据？我来帮你查查</label>
              <div className="question-box"><textarea id="question-input" rows={1} maxLength={1000} placeholder={datasetId === "ecommerce_mock_v1" ? "例如：本月和上月的销售额差多少？" : "例如：按套餐看看活跃订阅数？"} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} disabled={busy || health !== "ready"} /><button type="submit" disabled={busy || health !== "ready" || !question.trim()}>{busy ? "查询中…" : "查询"}</button></div>
              <p className="composer-hint">Enter 发送 · Shift + Enter 换行</p>
            </form>
            <div className="example-list">{examples.map((example) => <button type="button" key={example} onClick={() => void submitQuestion(example)} disabled={health !== "ready" || busy}>{example}<span>→</span></button>)}</div>
            <p className="empty-mock-note">Mock 演示数据 · 快照日 2026-08-01 · 不代表真实经营结果</p>
          </div>
        ) : (
          <div className="conversation" aria-live="polite">
            <div className="conversation-toolbar"><span>本次对话 · {messages.length} 个问题</span><button type="button" onClick={resetConversation} disabled={busy} title="仅清空当前页面显示，不会删除后台记录">↺ 重新开始</button></div>
            {messages.map((message, index) => <div className="turn" key={`${index}-${message.question}`}><div className="user-turn"><div className="user-question"><p>{message.question}</p><span className="avatar user-avatar">我</span></div><div className="user-turn-actions"><button className="delete-turn" type="button" onClick={() => removeMessage(index)} disabled={busy} aria-label="删除这条提问" title="删除这条提问"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M10 11v6m4-6v6M5.5 7l1 13h11l1-13M9 7V4h6v3" /></svg></button></div></div>{message.response ? <div className="assistant-answer"><span className="avatar bot-avatar">C</span><ResultCard response={message.response} mockUserId={mockUserId} sessionId={sessionId ?? ""} /></div> : message.error ? <div className="assistant-answer"><span className="avatar bot-avatar">C</span><div className="request-error"><p>{message.error}</p><small>请检查服务状态或网络后重试，也可以修改问题再提交。</small><button type="button" onClick={() => void submitQuestion(message.question, index)} disabled={busy || health !== "ready"}>重试这条问题</button></div></div> : <div className="assistant-answer"><span className="avatar bot-avatar">C</span><p className="pending">正在按确定性规则查询<span className="loading-dots" aria-hidden="true"><i>.</i><i>.</i><i>.</i></span></p></div>}</div>)}
          </div>
        )}
        {messages.length > 0 && <form className="composer composer-followup" onSubmit={onSubmit}>
          <label className="question-label" htmlFor="question-input">想看看什么经营数据？我来帮你查查</label>
          <div className="question-box"><textarea id="question-input" rows={1} maxLength={1000} placeholder={datasetId === "ecommerce_mock_v1" ? "例如：本月和上月的销售额差多少？" : "例如：按套餐看看活跃订阅数？"} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} disabled={busy || health !== "ready"} /><button type="submit" disabled={busy || health !== "ready" || !question.trim()}>{busy ? "查询中…" : "查询"}</button></div>
          <p className="composer-hint">Enter 发送 · Shift + Enter 换行 · 查询完成或报错后可继续提问</p>
        </form>}
      </section>
      {messages.length > 0 && <footer>固定 {datasetId === "ecommerce_mock_v1" ? "电商" : "SaaS 订阅"} Mock 数据 · 快照日 2026-08-01 · 不代表真实经营结果</footer>}
    </main>
  );
}
