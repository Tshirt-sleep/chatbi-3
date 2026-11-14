"""Allowlisted deterministic query planning and execution for P6."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as day_time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import database
from .intent_schemas import IntentDraft
from .intent_validation import IntentValidationError, validate_intent_draft
from .llm_provider import (
    DimensionDefinition,
    ExplicitQueryContext,
    IntentCapabilityDefinition,
    IntentParseContext,
    IntentProvider,
    IntentProviderError,
    MetricDefinition,
    SemanticTermDefinition,
)
from .query_capabilities import SUPPORTED_CAPABILITIES
from .query_schemas import (
    Evidence,
    Interpretation,
    MetricValue,
    QueryDebug,
    ResultRow,
    TimeRange,
    TurnResponse,
    Visualization,
)
from .release import release_fields
from .saas_catalog import ACTIVE_SAAS_CATALOG
from .semantic_catalog import ACTIVE_CATALOG
from .time_periods import completed_month_comparison, completed_week_comparison

CATALOG = ACTIVE_CATALOG.catalog
DATASET_ID = CATALOG.dataset_id
CATALOG_ID = CATALOG.catalog_id
CATALOG_VERSION = CATALOG.version
AS_OF_DATE = ACTIVE_CATALOG.as_of_date
TIMEZONE = CATALOG.timezone
VALID_ORDER_FILTER = "order_status IN ('paid', 'completed') AND paid_at IS NOT NULL"
METRIC_DEFINITIONS = {
    metric.id: metric.definition for metric in CATALOG.metrics if metric.status == "active"
}
_METRICS_BY_ID = {metric.id: metric for metric in CATALOG.metrics}
_DIMENSIONS_BY_ID = {dimension.id: dimension for dimension in CATALOG.dimensions}
_FOLLOWUP_DIMENSION_IDS = frozenset({"product", "category", "channel"})

SQL_TEMPLATES: dict[str, str] = {
    "uq01_daily_summary": """
        SELECT COALESCE(SUM(paid_amount_cents), 0) AS sales_cents,
               COUNT(DISTINCT order_id) AS order_count
        FROM orders
        WHERE dataset_id = :dataset_id
          AND order_status IN ('paid', 'completed')
          AND paid_at IS NOT NULL
          AND paid_at >= :start_inclusive AND paid_at < :end_exclusive
    """,
    "uq02_daily_sales_trend": """
        SELECT substr(paid_at, 1, 10) AS day,
               COALESCE(SUM(paid_amount_cents), 0) AS sales_cents
        FROM orders
        WHERE dataset_id = :dataset_id
          AND order_status IN ('paid', 'completed')
          AND paid_at IS NOT NULL
          AND paid_at >= :start_inclusive AND paid_at < :end_exclusive
        GROUP BY substr(paid_at, 1, 10)
        ORDER BY day ASC
    """,
    "uq03_monthly_comparison": """
        SELECT
          COALESCE(SUM(CASE WHEN paid_at >= :current_start AND paid_at < :current_end
                            THEN paid_amount_cents ELSE 0 END), 0) AS current_cents,
          COALESCE(SUM(CASE WHEN paid_at >= :previous_start AND paid_at < :previous_end
                            THEN paid_amount_cents ELSE 0 END), 0) AS previous_cents
        FROM orders
        WHERE dataset_id = :dataset_id
          AND order_status IN ('paid', 'completed') AND paid_at IS NOT NULL
          AND paid_at >= :previous_start AND paid_at < :current_end
    """,
    "uq04_product_top": """
        SELECT p.product_id, p.product_name,
               COALESCE(SUM(oi.line_amount_after_discount_cents), 0) AS sales_cents
        FROM orders o
        JOIN order_items oi ON oi.dataset_id = o.dataset_id AND oi.order_id = o.order_id
        JOIN products p ON p.dataset_id = oi.dataset_id AND p.product_id = oi.product_id
        WHERE o.dataset_id = :dataset_id
          AND o.order_status IN ('paid', 'completed') AND o.paid_at IS NOT NULL
          AND o.paid_at >= :start_inclusive AND o.paid_at < :end_exclusive
        GROUP BY p.product_id, p.product_name
        HAVING SUM(oi.line_amount_after_discount_cents) > 0
        ORDER BY sales_cents DESC, p.product_id ASC
        LIMIT 10
    """,
    "uq07_product_refund_rate": """
        SELECT p.product_id, p.product_name,
               COUNT(DISTINCT CASE WHEN r.refund_id IS NOT NULL THEN o.order_id END) AS refund_order_count,
               COUNT(DISTINCT o.order_id) AS eligible_order_count,
               CAST(COUNT(DISTINCT CASE WHEN r.refund_id IS NOT NULL THEN o.order_id END) AS FLOAT)
                 / NULLIF(COUNT(DISTINCT o.order_id), 0) AS refund_rate
        FROM products p
        JOIN order_items oi ON oi.dataset_id = p.dataset_id AND oi.product_id = p.product_id
        JOIN orders o ON o.dataset_id = oi.dataset_id AND o.order_id = oi.order_id
          AND o.order_status IN ('paid', 'completed') AND o.paid_at IS NOT NULL
          AND o.paid_at >= :start_inclusive AND o.paid_at < :end_exclusive
        LEFT JOIN refunds r ON r.dataset_id = oi.dataset_id
          AND r.order_item_id = oi.order_item_id AND r.refund_status = 'completed'
        WHERE p.dataset_id = :dataset_id
        GROUP BY p.product_id, p.product_name
        HAVING COUNT(DISTINCT o.order_id) > 0
        ORDER BY refund_rate DESC, p.product_id ASC
        LIMIT 10
    """,
    "uq05_category_summary": """
        SELECT c.category_id, c.category_name,
               COUNT(DISTINCT CASE WHEN o.order_id IS NOT NULL THEN o.order_id END) AS order_count,
               COALESCE(SUM(CASE WHEN o.order_id IS NOT NULL
                                 THEN oi.line_amount_after_discount_cents ELSE 0 END), 0) AS sales_cents
        FROM categories c
        LEFT JOIN products p ON p.dataset_id = c.dataset_id
                            AND p.primary_leaf_category_id = c.category_id
        LEFT JOIN order_items oi ON oi.dataset_id = p.dataset_id AND oi.product_id = p.product_id
        LEFT JOIN orders o ON o.dataset_id = oi.dataset_id AND o.order_id = oi.order_id
          AND o.order_status IN ('paid', 'completed') AND o.paid_at IS NOT NULL
          AND o.paid_at >= :start_inclusive AND o.paid_at < :end_exclusive
        WHERE c.dataset_id = :dataset_id AND c.level = 2
        GROUP BY c.category_id, c.category_name
        ORDER BY c.category_id ASC
    """,
    "uq06_channel_aov": """
        SELECT ch.channel_id, ch.channel_name,
               COUNT(DISTINCT o.order_id) AS order_count,
               COALESCE(SUM(o.paid_amount_cents), 0) AS sales_cents
        FROM channels ch
        LEFT JOIN orders o ON o.dataset_id = ch.dataset_id AND o.channel_id = ch.channel_id
          AND o.order_status IN ('paid', 'completed') AND o.paid_at IS NOT NULL
          AND o.paid_at >= :start_inclusive AND o.paid_at < :end_exclusive
        WHERE ch.dataset_id = :dataset_id
        GROUP BY ch.channel_id, ch.channel_name
        ORDER BY ch.channel_id ASC
    """,
    "uq11_category_top": """
        SELECT c.category_id, c.category_name,
               COALESCE(SUM(oi.line_amount_after_discount_cents), 0) AS sales_cents
        FROM categories c
        JOIN products p ON p.dataset_id = c.dataset_id
                       AND p.primary_leaf_category_id = c.category_id
        JOIN order_items oi ON oi.dataset_id = p.dataset_id AND oi.product_id = p.product_id
        JOIN orders o ON o.dataset_id = oi.dataset_id AND o.order_id = oi.order_id
          AND o.order_status IN ('paid', 'completed') AND o.paid_at IS NOT NULL
          AND o.paid_at >= :start_inclusive AND o.paid_at < :end_exclusive
        WHERE c.dataset_id = :dataset_id AND c.level = 2
        GROUP BY c.category_id, c.category_name
        HAVING SUM(oi.line_amount_after_discount_cents) > 0
        ORDER BY sales_cents DESC, c.category_id ASC
        LIMIT 10
    """,
    "uq08_category_comparison": """
        SELECT c.category_id, c.category_name,
          COALESCE(SUM(CASE WHEN o.paid_at >= :current_start AND o.paid_at < :current_end
                            THEN oi.line_amount_after_discount_cents ELSE 0 END), 0) AS current_cents,
          COALESCE(SUM(CASE WHEN o.paid_at >= :previous_start AND o.paid_at < :previous_end
                            THEN oi.line_amount_after_discount_cents ELSE 0 END), 0) AS previous_cents
        FROM categories c
        LEFT JOIN products p ON p.dataset_id = c.dataset_id
                            AND p.primary_leaf_category_id = c.category_id
        LEFT JOIN order_items oi ON oi.dataset_id = p.dataset_id AND oi.product_id = p.product_id
        LEFT JOIN orders o ON o.dataset_id = oi.dataset_id AND o.order_id = oi.order_id
          AND o.order_status IN ('paid', 'completed') AND o.paid_at IS NOT NULL
          AND o.paid_at >= :previous_start AND o.paid_at < :current_end
        WHERE c.dataset_id = :dataset_id AND c.level = 2
        GROUP BY c.category_id, c.category_name
        ORDER BY (
          COALESCE(SUM(CASE WHEN o.paid_at >= :current_start AND o.paid_at < :current_end
                            THEN oi.line_amount_after_discount_cents ELSE 0 END), 0)
          - COALESCE(SUM(CASE WHEN o.paid_at >= :previous_start AND o.paid_at < :previous_end
                              THEN oi.line_amount_after_discount_cents ELSE 0 END), 0)
        ) ASC, c.category_id ASC
    """,
    "uq09_period_summary": """
        SELECT
          COALESCE(SUM(CASE WHEN paid_at >= :current_start AND paid_at < :current_end
                            THEN paid_amount_cents ELSE 0 END), 0) AS current_cents,
          COUNT(DISTINCT CASE WHEN paid_at >= :current_start AND paid_at < :current_end
                              THEN order_id END) AS current_orders,
          COALESCE(SUM(CASE WHEN paid_at >= :previous_start AND paid_at < :previous_end
                            THEN paid_amount_cents ELSE 0 END), 0) AS previous_cents,
          COUNT(DISTINCT CASE WHEN paid_at >= :previous_start AND paid_at < :previous_end
                              THEN order_id END) AS previous_orders
        FROM orders
        WHERE dataset_id = :dataset_id
          AND order_status IN ('paid', 'completed') AND paid_at IS NOT NULL
          AND paid_at >= :previous_start AND paid_at < :current_end
    """,
    "followup_product_group": """
        SELECT p.product_id, p.product_name,
               COUNT(DISTINCT o.order_id) AS order_count,
               COALESCE(SUM(oi.line_amount_after_discount_cents), 0) AS sales_cents
        FROM orders o
        JOIN order_items oi ON oi.dataset_id = o.dataset_id AND oi.order_id = o.order_id
        JOIN products p ON p.dataset_id = oi.dataset_id AND p.product_id = oi.product_id
        WHERE o.dataset_id = :dataset_id
          AND o.order_status IN ('paid', 'completed') AND o.paid_at IS NOT NULL
          AND o.paid_at >= :start_inclusive AND o.paid_at < :end_exclusive
        GROUP BY p.product_id, p.product_name
        ORDER BY p.product_id ASC
    """,
}

UQ07_EMPTY_DIAGNOSTICS_SQL = """
    WITH eligible_orders AS (
        SELECT dataset_id, order_id
        FROM orders
        WHERE dataset_id = :dataset_id
          AND order_status IN ('paid', 'completed')
          AND paid_at IS NOT NULL
          AND paid_at >= :start_inclusive AND paid_at < :end_exclusive
    ), matching_items AS (
        SELECT oi.dataset_id, oi.order_id, oi.order_item_id, oi.product_id
        FROM order_items oi
        JOIN eligible_orders o
          ON o.dataset_id = oi.dataset_id AND o.order_id = oi.order_id
    ), matching_products AS (
        SELECT mi.dataset_id, mi.product_id
        FROM matching_items mi
        JOIN products p
          ON p.dataset_id = mi.dataset_id AND p.product_id = mi.product_id
    )
    SELECT
        (SELECT COUNT(*) FROM products WHERE dataset_id = :dataset_id) AS product_count,
        (SELECT COUNT(*) FROM eligible_orders) AS eligible_order_count,
        (SELECT COUNT(*) FROM matching_items) AS matching_order_item_count,
        (SELECT COUNT(DISTINCT product_id) FROM matching_products) AS matching_product_count,
        (SELECT COUNT(*)
         FROM refunds r
         JOIN matching_items mi
           ON mi.dataset_id = r.dataset_id AND mi.order_item_id = r.order_item_id
         WHERE r.refund_status = 'completed') AS matching_completed_refund_count
"""


@dataclass
class PendingClarification:
    turn_id: str
    question_kind: str
    prompt: str


@dataclass
class ChatSession:
    session_id: str
    dataset_id: str = DATASET_ID
    owner_user_id: str = "analyst"
    semantic_catalog_id: str = CATALOG_ID
    semantic_catalog_version: str = CATALOG_VERSION
    pending: PendingClarification | None = None
    last_metric_ids: list[str] | None = None
    last_time_range: TimeRange | None = None
    last_dimension_ids: list[str] | None = None
    turn_statuses: dict[str, str] | None = None


class SessionStore:
    """Process-local sessions are sufficient for a single-process Mock MVP."""

    MAX_SESSIONS = 2_000

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}

    def create(self, dataset_id: str = DATASET_ID, owner_user_id: str = "analyst") -> ChatSession:
        if len(self._sessions) >= self.MAX_SESSIONS:
            self._sessions.pop(next(iter(self._sessions)))
        snapshot = ACTIVE_CATALOG if dataset_id == DATASET_ID else ACTIVE_SAAS_CATALOG
        session = ChatSession(
            session_id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            owner_user_id=owner_user_id,
            semantic_catalog_id=snapshot.catalog.catalog_id,
            semantic_catalog_version=snapshot.catalog.version,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)


sessions = SessionStore()
debug_query_cache: dict[str, QueryDebug] = {}
# Route safe query diagnostics through Uvicorn's configured application handler
# so managed services capture them. Records contain template IDs and row counts,
# never SQL, parameters, or user input.
query_logger = logging.getLogger("uvicorn.error")


def _format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    absolute_cents = abs(cents)
    return f"{sign}{absolute_cents // 100}.{absolute_cents % 100:02d}"


def _range(start: date, end: date) -> TimeRange:
    return TimeRange(start_inclusive=start.isoformat(), end_exclusive=end.isoformat())


def _datetime_bound(day: date) -> str:
    if TIMEZONE != "Asia/Shanghai":
        raise ValueError(f"Unsupported query timezone: {TIMEZONE}")
    return datetime.combine(day, day_time.min, tzinfo=timezone(timedelta(hours=8))).isoformat()


def _evidence(definitions: list[str]) -> Evidence:
    return Evidence(
        dataset_id=DATASET_ID,
        dataset_version=ACTIVE_CATALOG.dataset_version,
        semantic_catalog_id=CATALOG_ID,
        semantic_catalog_version=CATALOG_VERSION,
        metric_definitions=definitions,
    )


def _base_response(
    request_id: str,
    turn_id: str,
    status: str,
    answer_text: str,
    interpretation: Interpretation,
    definitions: list[str] | None = None,
    visualization: Visualization | None = None,
    values: list[MetricValue] | None = None,
    clarification_id: str | None = None,
    clarification_prompt: str | None = None,
    suggested_terms: list[str] | None = None,
    query: QueryDebug | None = None,
) -> TurnResponse:
    debug_item = query or QueryDebug(
        query_id=str(uuid.uuid4()),
        template_id="none",
        sql="",
        parameters={},
        query_executed=False,
    )
    debug_query_cache[debug_item.query_id] = debug_item
    if len(debug_query_cache) > 500:
        debug_query_cache.pop(next(iter(debug_query_cache)))
    return TurnResponse(
        request_id=request_id,
        turn_id=turn_id,
        status=status,  # type: ignore[arg-type]
        answer_text=answer_text,
        clarification_id=clarification_id,
        clarification_prompt=clarification_prompt,
        suggested_terms=suggested_terms or [],
        values=values or [],
        interpretation=interpretation,
        visualization=visualization or Visualization(type="none"),
        evidence=_evidence(definitions or []),
        debug_ref=debug_item.query_id,
    )


def _execute(
    engine: Engine,
    template_id: str,
    parameters: Mapping[str, str | int],
    request_id: str,
) -> tuple[list[dict[str, Any]], QueryDebug]:
    sql = SQL_TEMPLATES[template_id].strip()
    started = time.perf_counter()
    query_id = str(uuid.uuid4())
    with engine.connect() as connection:
        rows = [dict(row._mapping) for row in connection.execute(text(sql), parameters)]
        empty_diagnostics = None
        if template_id == "uq07_product_refund_rate" and not rows:
            diagnostic_row = (
                connection.execute(text(UQ07_EMPTY_DIAGNOSTICS_SQL), parameters).mappings().one()
            )
            empty_diagnostics = {key: int(value) for key, value in diagnostic_row.items()}
    duration_ms = round((time.perf_counter() - started) * 1000)
    if empty_diagnostics is not None:
        query_logger.info(
            json.dumps(
                {
                    "event": "query_empty_diagnostics",
                    "request_id": request_id,
                    "query_id": query_id,
                    "template_id": template_id,
                    "date_bounds": {
                        "start_inclusive": parameters["start_inclusive"],
                        "end_exclusive": parameters["end_exclusive"],
                    },
                    "empty_result_counts": empty_diagnostics,
                    **release_fields(),
                },
                sort_keys=True,
            )
        )
    return rows, QueryDebug(
        query_id=query_id,
        template_id=template_id,
        sql=sql,
        parameters=dict(parameters),
        query_executed=True,
        duration_ms=duration_ms,
        result_row_count=len(rows),
    )


def get_debug_query(query_id: str) -> QueryDebug | None:
    return debug_query_cache.get(query_id)


def failed_response(request_id: str) -> TurnResponse:
    return _base_response(
        request_id,
        str(uuid.uuid4()),
        "failed",
        "查询暂时无法完成，请稍后重试。结果没有生成。",
        Interpretation(),
    )


def _clock_range(kind: str) -> TimeRange:
    end = AS_OF_DATE
    if kind == "yesterday":
        start = end - timedelta(days=1)
    elif kind == "recent_7_days":
        start = end - timedelta(days=7)
    else:
        raise ValueError(f"Unsupported fixed time range: {kind}")
    return _range(start, end)


def _clarification(
    request_id: str,
    turn_id: str,
    kind: str,
    prompt: str,
) -> TurnResponse:
    metric_dimensions = {
        "uq04": (["sales_amount"], ["product"]),
        "uq05": (["order_count", "sales_amount"], ["category"]),
        "uq06": (["average_order_value"], ["channel"]),
        "uq12": (["sales_amount", "order_count"], ["channel"]),
        "uq10": (["sales_amount"], ["category"]),
        "uq11": (["sales_amount"], ["category"]),
        "uq09": (["order_count", "sales_amount", "average_order_value"], []),
    }
    metric_ids, dimension_ids = metric_dimensions.get(kind, ([], []))
    interpretation = Interpretation(
        metric_ids=metric_ids,
        dimension_ids=dimension_ids,
        clarification_state="required",
    )
    return _base_response(
        request_id,
        turn_id,
        "clarification_required",
        prompt,
        interpretation,
        clarification_id=turn_id,
        clarification_prompt=prompt,
    )


def _params_for_range(date_range: TimeRange) -> dict[str, str]:
    return {
        "dataset_id": DATASET_ID,
        "start_inclusive": _datetime_bound(date.fromisoformat(date_range.start_inclusive)),
        "end_exclusive": _datetime_bound(date.fromisoformat(date_range.end_exclusive)),
    }


def _comparison_params(current: TimeRange, previous: TimeRange) -> dict[str, str]:
    return {
        "dataset_id": DATASET_ID,
        "current_start": _datetime_bound(date.fromisoformat(current.start_inclusive)),
        "current_end": _datetime_bound(date.fromisoformat(current.end_exclusive)),
        "previous_start": _datetime_bound(date.fromisoformat(previous.start_inclusive)),
        "previous_end": _datetime_bound(date.fromisoformat(previous.end_exclusive)),
    }


def _normalize_semantic_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _matched_entity_ids(
    value: str,
    entities: tuple[Any, ...],
) -> frozenset[str]:
    normalized = _normalize_semantic_text(value)
    return frozenset(
        entity.id
        for entity in entities
        if entity.status == "active"
        and any(
            _normalize_semantic_text(alias) in normalized
            for alias in (entity.label, *entity.aliases)
        )
    )


def _matched_catalog_term(value: str, resolution: str) -> Any | None:
    normalized = _normalize_semantic_text(value)
    matches = [
        term
        for term in CATALOG.terms
        if term.resolution == resolution and _normalize_semantic_text(term.text) in normalized
    ]
    return max(matches, key=lambda term: len(_normalize_semantic_text(term.text)), default=None)


def _matched_inactive_dimension(value: str) -> Any | None:
    normalized = _normalize_semantic_text(value)
    matches = [
        dimension
        for dimension in CATALOG.dimensions
        if dimension.status == "inactive"
        and any(
            _normalize_semantic_text(alias) in normalized
            for alias in (dimension.label, *dimension.aliases)
        )
    ]
    return max(
        matches,
        key=lambda dimension: len(_normalize_semantic_text(dimension.label)),
        default=None,
    )


def _active_semantic_suggestions(include_dimensions: bool = False) -> list[str]:
    suggestions = [metric.label for metric in CATALOG.metrics if metric.status == "active"]
    if include_dimensions:
        suggestions.extend(
            dimension.label for dimension in CATALOG.dimensions if dimension.status == "active"
        )
    return suggestions


def _classify(normalized: str) -> str | None:
    if _matched_catalog_term(normalized, "ambiguous") is not None:
        return "ambiguous_term"
    if _matched_catalog_term(normalized, "unsupported") is not None:
        return "unsupported_term"
    if _matched_inactive_dimension(normalized) is not None:
        return "unsupported_dimension"

    metric_ids = _matched_entity_ids(normalized, CATALOG.metrics)
    dimension_ids = _matched_entity_ids(normalized, CATALOG.dimensions)
    has_sales_amount = "sales_amount" in metric_ids
    has_order_count = "order_count" in metric_ids
    has_average_order_value = "average_order_value" in metric_ids

    if "为什么" in normalized and has_order_count and has_sales_amount:
        return "uq09"
    if "本周" in normalized and "category" in dimension_ids and "下降" in normalized:
        return "uq08"
    if (
        "channel" in dimension_ids
        and (has_sales_amount or has_order_count)
        and not has_average_order_value
    ):
        return "uq12"
    if "channel" in dimension_ids and has_average_order_value:
        return "uq06"
    if (
        "product" in dimension_ids
        and "refund_rate" in metric_ids
        and any(term in normalized for term in ("最高", "前10", "top10", "排行", "排名"))
    ):
        return "uq07"
    if "refund_rate" in metric_ids:
        return "unsupported"
    if (
        "category" in dimension_ids
        and has_sales_amount
        and any(term in normalized for term in ("最高", "排行", "排名", "top10", "前10"))
    ):
        return "uq11"
    if "category" in dimension_ids and (has_order_count or has_sales_amount):
        return "uq05"
    if (
        "product" in dimension_ids
        and any(term in normalized for term in ("前10", "top10", "最高"))
        and has_sales_amount
    ):
        return "uq04"
    completed_month_wording = any(
        term in normalized for term in ("最近一个完整月", "最近完整月", "上一个完整月")
    )
    if has_sales_amount and (
        ("本月" in normalized and ("上月" in normalized or "增长" in normalized))
        or (
            completed_month_wording
            and any(
                term in normalized for term in ("上个月", "上月", "增长", "变化", "比较", "对比")
            )
        )
    ):
        return "uq03"
    if any(term in normalized for term in ("最近7天", "近7天", "过去7天")) and has_sales_amount:
        return "uq02"
    if ("昨天" in normalized or "昨日" in normalized) and (has_sales_amount or has_order_count):
        return "uq01"
    return None


def _group_dimension(normalized: str) -> str | None:
    compact = _normalize_semantic_text(normalized)
    matches: list[str] = []
    for dimension_id in _FOLLOWUP_DIMENSION_IDS:
        dimension = _DIMENSIONS_BY_ID[dimension_id]
        aliases = (dimension.label, *dimension.aliases)
        if any(
            re.search(
                rf"(?:按照|按|各|分){re.escape(_normalize_semantic_text(alias))}"
                rf"|{re.escape(_normalize_semantic_text(alias))}(?:拆分|拆一下|拆|分组)",
                compact,
            )
            for alias in aliases
        ):
            matches.append(dimension_id)
    return matches[0] if len(matches) == 1 else None


def _contains_unsafe_instruction(normalized: str) -> bool:
    markers = (
        "droptable",
        "deletefrom",
        "updateorders",
        "insertinto",
        "执行sql",
        "忽略之前",
        "忽略规则",
        "泄露系统",
        "数据库密码",
    )
    return any(marker in normalized for marker in markers)


def _clarification_kind(kind: str) -> tuple[str, str] | None:
    prompts = {
        "uq04": ("time_range", "请补充要查看的时间范围，例如“最近 30 天”。"),
        "uq05": ("time_range", "请补充要查看的时间范围，例如“最近 30 天”。"),
        "uq06": ("time_range", "请补充要查看的时间范围，例如“最近 30 天”。"),
        "uq12": ("time_range", "请补充要查看的时间范围，例如“最近 30 天”。"),
        "uq11": ("time_range", "请补充要查看的时间范围，例如“最近 30 天”。"),
        "uq09": (
            "comparison_period",
            "请提供两个需要比较的完整日期区间，例如“比较 2025-08-28 至 2025-09-03 和之前一周”。",
        ),
    }
    return prompts.get(kind)


def _parse_recent_range(normalized: str) -> TimeRange | None:
    numerals = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    match = re.search(r"(?:最近|近|过去)(\d+|[一二三四五六七八九十]+)(天|日|周|星期)", normalized)
    if not match:
        return None
    number_text, unit = match.groups()
    if number_text.isdigit():
        amount = int(number_text)
    elif number_text == "十":
        amount = 10
    elif number_text.startswith("十"):
        amount = 10 + numerals.get(number_text[1:], 0)
    elif number_text.endswith("十"):
        amount = numerals.get(number_text[0], 1) * 10
    elif "十" in number_text:
        tens, ones = number_text.split("十", maxsplit=1)
        amount = numerals.get(tens, 1) * 10 + numerals.get(ones, 0)
    else:
        amount = numerals.get(number_text, 0)
    days = amount * 7 if unit in {"周", "星期"} else amount
    if days < 1 or days > 366:
        return None
    return _range(AS_OF_DATE - timedelta(days=days), AS_OF_DATE)


def _date_range_from_question(normalized: str) -> TimeRange | None:
    recent = _parse_recent_range(normalized)
    if recent:
        return recent
    if "昨天" in normalized or "昨日" in normalized:
        return _clock_range("yesterday")
    if "本月" in normalized:
        current_start, current_end, _, _ = completed_month_comparison()
        return _range(current_start, current_end)
    if "本周" in normalized:
        current_start, current_end, _, _ = completed_week_comparison()
        return _range(current_start, current_end)
    return None


def _parse_two_periods(normalized: str) -> tuple[TimeRange, TimeRange] | None:
    dates = re.findall(r"(20\d{2}-\d{2}-\d{2})", normalized)
    if len(dates) < 2:
        return None
    if ("之前一周" in normalized and len(dates) != 2) or (
        "之前一周" not in normalized and len(dates) != 4
    ):
        return None
    try:
        current_start = date.fromisoformat(dates[0])
        current_last_day = date.fromisoformat(dates[1])
    except ValueError:
        return None
    current_end = current_last_day + timedelta(days=1)
    duration = (current_end - current_start).days
    if duration < 1 or duration > 366:
        return None
    if "之前一周" in normalized:
        previous_end = current_start
        previous_start = previous_end - timedelta(days=duration)
    else:
        try:
            previous_start = date.fromisoformat(dates[2])
            previous_last_day = date.fromisoformat(dates[3])
        except (ValueError, IndexError):
            return None
        previous_end = previous_last_day + timedelta(days=1)
    dataset_start = ACTIVE_CATALOG.dataset_start_date
    if (
        current_start < dataset_start
        or previous_start < dataset_start
        or current_end > AS_OF_DATE
        or previous_end > current_start
    ):
        return None
    return _range(current_start, current_end), _range(previous_start, previous_end)


def _metric(
    metric_id: str,
    label: str,
    value: str | int | None,
    unit: str,
    definition: str,
) -> MetricValue:
    return MetricValue(
        metric_id=metric_id,
        label=label,
        value=value,
        unit=unit,
        definition=definition,
    )


def _answer_for_kind(
    kind: str,
    question: str,
    request_id: str,
    turn_id: str,
    engine: Engine,
    date_range: TimeRange | None = None,
    periods: tuple[TimeRange, TimeRange] | None = None,
) -> TurnResponse:
    definitions = METRIC_DEFINITIONS
    if kind == "uq01":
        actual_range = date_range or _clock_range("yesterday")
        rows, debug = _execute(
            engine, kind + "_daily_summary", _params_for_range(actual_range), request_id
        )
        row = rows[0]
        values = [
            _metric(
                "sales_amount",
                "销售额",
                _format_money(int(row["sales_cents"])),
                "CNY",
                definitions["sales_amount"],
            ),
            _metric(
                "order_count",
                "订单数",
                int(row["order_count"]),
                "orders",
                definitions["order_count"],
            ),
        ]
        interpretation = Interpretation(
            metric_ids=["sales_amount", "order_count"],
            time_range=actual_range,
            filters=[VALID_ORDER_FILTER],
        )
        rows_data = [
            ResultRow(key=value.metric_id, label=value.label, values={value.metric_id: value.value})
            for value in values
        ]
        return _base_response(
            request_id,
            turn_id,
            "completed",
            "昨天的查询结果已完成。",
            interpretation,
            definitions=list(definitions.values()),
            visualization=Visualization(type="kpi", data=rows_data),
            values=values,
            query=debug,
        )

    if kind == "uq02":
        actual_range = date_range or _clock_range("recent_7_days")
        rows, debug = _execute(
            engine,
            kind + "_daily_sales_trend",
            _params_for_range(actual_range),
            request_id,
        )
        values_by_day = {str(row["day"]): int(row["sales_cents"]) for row in rows}
        days = [
            date.fromisoformat(actual_range.start_inclusive) + timedelta(days=index)
            for index in range(7)
        ]
        rows_data = [
            ResultRow(
                key=day.isoformat(),
                label=day.isoformat(),
                values={"sales_amount": _format_money(values_by_day.get(day.isoformat(), 0))},
            )
            for day in days
        ]
        total = sum(values_by_day.values())
        value = _metric(
            "sales_amount", "期间销售额", _format_money(total), "CNY", definitions["sales_amount"]
        )
        interpretation = Interpretation(
            metric_ids=["sales_amount"],
            dimension_ids=["order_date"],
            time_range=actual_range,
            filters=[VALID_ORDER_FILTER],
            sort=["order_date asc"],
        )
        return _base_response(
            request_id,
            turn_id,
            "completed",
            "最近 7 天每日销售额趋势如下。",
            interpretation,
            definitions=[definitions["sales_amount"]],
            visualization=Visualization(type="line", data=rows_data),
            values=[value],
            query=debug,
        )

    if kind == "uq03":
        if periods is None:
            current_start, current_end, previous_start, previous_end = completed_month_comparison()
            periods = (_range(current_start, current_end), _range(previous_start, previous_end))
        current, previous = periods
        rows, debug = _execute(
            engine,
            kind + "_monthly_comparison",
            _comparison_params(current, previous),
            request_id,
        )
        row = rows[0]
        current_cents, previous_cents = int(row["current_cents"]), int(row["previous_cents"])
        delta = current_cents - previous_cents
        rate = (
            None
            if previous_cents == 0
            else str(
                (Decimal(delta) * 100 / Decimal(previous_cents)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )
        )
        current_month_date = date.fromisoformat(current.start_inclusive)
        previous_month_date = date.fromisoformat(previous.start_inclusive)
        current_month = f"{current_month_date.year}年{current_month_date.month}月"
        previous_month = f"{previous_month_date.year}年{previous_month_date.month}月"
        values = [
            _metric(
                "sales_amount_current",
                f"{current_month}销售额",
                _format_money(current_cents),
                "CNY",
                definitions["sales_amount"],
            ),
            _metric(
                "sales_amount_previous",
                f"{previous_month}销售额",
                _format_money(previous_cents),
                "CNY",
                definitions["sales_amount"],
            ),
            _metric(
                "sales_amount_delta",
                "变化额",
                _format_money(delta),
                "CNY",
                "本期销售额减去上期销售额。",
            ),
            _metric(
                "sales_amount_change_rate",
                "变化率",
                None if rate is None else f"{rate}%",
                "percent",
                "变化额除以上期销售额；上期为 0 时无法计算。",
            ),
        ]
        interpretation = Interpretation(
            metric_ids=["sales_amount"],
            time_range=current,
            comparison_range=previous,
            filters=[VALID_ORDER_FILTER],
        )
        data = [
            ResultRow(key=value.metric_id, label=value.label, values={value.metric_id: value.value})
            for value in values
        ]
        return _base_response(
            request_id,
            turn_id,
            "completed",
            f"按固定参考日比较最近完整月（{current_month}）与前一个月（{previous_month}）。",
            interpretation,
            definitions=[definitions["sales_amount"]],
            visualization=Visualization(type="table", data=data),
            values=values,
            query=debug,
        )

    if kind in {"uq04", "uq05", "uq06", "uq07", "uq11", "uq12"}:
        if date_range is None:
            prompt = "请补充要查看的时间范围，例如“最近 30 天”。"
            session_pending = PendingClarification(turn_id, kind, prompt)
            # Pending state is set by answer_question after this response is returned.
            _ = session_pending
            return _clarification(request_id, turn_id, kind, prompt)
        params = _params_for_range(date_range)
        if kind == "uq04":
            rows, debug = _execute(engine, "uq04_product_top", params, request_id)
            result_rows = [
                ResultRow(
                    key=str(row["product_id"]),
                    label=str(row["product_name"]),
                    values={
                        "product_id": str(row["product_id"]),
                        "sales_amount": _format_money(int(row["sales_cents"])),
                    },
                )
                for row in rows
            ]
            result_values = [
                _metric(
                    "sales_amount",
                    "销售额",
                    _format_money(sum(int(row["sales_cents"]) for row in rows)),
                    "CNY",
                    definitions["sales_amount"],
                )
            ]
            interpretation = Interpretation(
                metric_ids=["sales_amount"],
                dimension_ids=["product"],
                time_range=date_range,
                filters=[VALID_ORDER_FILTER, "销售额大于 0"],
                sort=["sales_amount desc", "product_id asc"],
                limit=10,
            )
            return _base_response(
                request_id,
                turn_id,
                "completed",
                "按销售额降序列出前 10 个商品。",
                interpretation,
                definitions=[definitions["sales_amount"]],
                visualization=Visualization(type="bar", data=result_rows),
                values=result_values,
                query=debug,
            )
        if kind == "uq07":
            rows, debug = _execute(engine, "uq07_product_refund_rate", params, request_id)
            result_rows = [
                ResultRow(
                    key=str(row["product_id"]),
                    label=str(row["product_name"]),
                    values={
                        "refund_order_count": int(row["refund_order_count"]),
                        "order_count": int(row["eligible_order_count"]),
                        "refund_rate": f"{(Decimal(int(row['refund_order_count'])) * 100 / Decimal(int(row['eligible_order_count']))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%",
                    },
                )
                for row in rows
            ]
            top_rate = result_rows[0].values["refund_rate"] if result_rows else None
            interpretation = Interpretation(
                metric_ids=["refund_rate"],
                dimension_ids=["product"],
                time_range=date_range,
                filters=[VALID_ORDER_FILTER, "退款状态为 completed；按商品与订单去重"],
                sort=["refund_rate desc", "product_id asc"],
                limit=10,
            )
            return _base_response(
                request_id,
                turn_id,
                "completed",
                "以下商品按退款订单率降序排列。分子为所选支付日期范围内、截至 Mock 快照至少有一笔已完成退款的商品订单数；分母为该商品涉及的有效订单数。部分退款按一单计，多次退款按订单去重。",
                interpretation,
                definitions=[definitions["refund_rate"]],
                visualization=Visualization(type="table", data=result_rows),
                values=[
                    _metric(
                        "refund_rate",
                        "最高商品退款订单率",
                        top_rate,
                        "percent",
                        definitions["refund_rate"],
                    )
                ],
                query=debug,
            )
        if kind == "uq05":
            rows, debug = _execute(engine, "uq05_category_summary", params, request_id)
            result_rows = [
                ResultRow(
                    key=str(row["category_id"]),
                    label=str(row["category_name"]),
                    values={
                        "order_count": int(row["order_count"]),
                        "sales_amount": _format_money(int(row["sales_cents"])),
                    },
                )
                for row in rows
            ]
            values = [
                _metric(
                    "order_count",
                    "类目内订单数",
                    sum(int(row["order_count"]) for row in rows),
                    "orders",
                    "订单是否涉及该类目，类目内按订单 ID 去重；跨类目订单会重复计入。",
                ),
                _metric(
                    "sales_amount",
                    "销售额",
                    _format_money(sum(int(row["sales_cents"]) for row in rows)),
                    "CNY",
                    definitions["sales_amount"],
                ),
            ]
            interpretation = Interpretation(
                metric_ids=["order_count", "sales_amount"],
                dimension_ids=["category"],
                time_range=date_range,
                filters=[VALID_ORDER_FILTER],
                sort=["category_id asc"],
            )
            return _base_response(
                request_id,
                turn_id,
                "completed",
                "类目订单数按订单涉及关系分别计数，因此跨类目订单可能在多个类目中出现。",
                interpretation,
                definitions=[definitions["order_count"], definitions["sales_amount"]],
                visualization=Visualization(type="bar", data=result_rows),
                values=values,
                query=debug,
            )
        if kind == "uq11":
            rows, debug = _execute(engine, "uq11_category_top", params, request_id)
            result_rows = [
                ResultRow(
                    key=str(row["category_id"]),
                    label=str(row["category_name"]),
                    values={"sales_amount": _format_money(int(row["sales_cents"]))},
                )
                for row in rows
            ]
            interpretation = Interpretation(
                metric_ids=["sales_amount"],
                dimension_ids=["category"],
                time_range=date_range,
                filters=[VALID_ORDER_FILTER, "销售额大于 0"],
                sort=["sales_amount desc", "category_id asc"],
                limit=10,
            )
            return _base_response(
                request_id,
                turn_id,
                "completed",
                "以下品类按所选期间销售额降序排列，最多显示 10 个；同额按品类 ID 升序。",
                interpretation,
                definitions=[definitions["sales_amount"]],
                visualization=Visualization(type="bar", data=result_rows),
                values=[
                    _metric(
                        "sales_amount",
                        "Top 10 品类销售额合计",
                        _format_money(sum(int(row["sales_cents"]) for row in rows)),
                        "CNY",
                        definitions["sales_amount"],
                    )
                ],
                query=debug,
            )
        rows, debug = _execute(engine, "uq06_channel_aov", params, request_id)
        result_rows = []
        for row in rows:
            order_count = int(row["order_count"])
            sales_cents = int(row["sales_cents"])
            aov = (
                None
                if order_count == 0
                else _format_money(
                    int(
                        (Decimal(sales_cents) / order_count).quantize(
                            Decimal(1), rounding=ROUND_HALF_UP
                        )
                    )
                )
            )
            result_rows.append(
                ResultRow(
                    key=str(row["channel_id"]),
                    label=str(row["channel_name"]),
                    values={
                        "order_count": order_count,
                        "sales_amount": _format_money(sales_cents),
                        "average_order_value": aov,
                    },
                )
            )
        total_sales = sum(int(row["sales_cents"]) for row in rows)
        total_orders = sum(int(row["order_count"]) for row in rows)
        aov_total = (
            None
            if total_orders == 0
            else _format_money(
                int(
                    (Decimal(total_sales) / total_orders).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
            )
        )
        values = []
        channel_metrics = set()
        if "sales_amount" in _matched_entity_ids(question, CATALOG.metrics):
            channel_metrics.add("sales_amount")
        if "order_count" in _matched_entity_ids(question, CATALOG.metrics):
            channel_metrics.add("order_count")
        if "average_order_value" in _matched_entity_ids(question, CATALOG.metrics):
            channel_metrics.add("average_order_value")
        if not channel_metrics:
            channel_metrics = {"average_order_value"}
        if kind == "uq06":
            channel_metrics = {"sales_amount", "order_count", "average_order_value"}
        result_rows = [
            ResultRow(
                key=result_row.key,
                label=result_row.label,
                values={
                    metric_id: result_row.values[metric_id]
                    for metric_id in ("sales_amount", "order_count", "average_order_value")
                    if metric_id in channel_metrics and metric_id in result_row.values
                },
            )
            for result_row in result_rows
        ]
        if "sales_amount" in channel_metrics:
            values.append(
                _metric(
                    "sales_amount",
                    "渠道销售额合计",
                    _format_money(total_sales),
                    "CNY",
                    definitions["sales_amount"],
                )
            )
        if "order_count" in channel_metrics:
            values.append(
                _metric(
                    "order_count",
                    "渠道有效订单数合计",
                    total_orders,
                    "orders",
                    definitions["order_count"],
                )
            )
        if "average_order_value" in channel_metrics:
            values.append(
                _metric(
                    "average_order_value",
                    "总体客单价",
                    aov_total,
                    "CNY",
                    "所选期间销售额除以所选期间去重有效订单数；按渠道分组时分别计算。",
                )
            )
        interpretation = Interpretation(
            metric_ids=[
                metric
                for metric in ("sales_amount", "order_count", "average_order_value")
                if metric in channel_metrics
            ],
            dimension_ids=["channel"],
            time_range=date_range,
            filters=[VALID_ORDER_FILTER],
            sort=["channel_id asc"],
        )
        return _base_response(
            request_id,
            turn_id,
            "completed",
            "渠道表按问题展示各渠道指标；上方汇总卡列出所问指标在所选期间的合计。",
            interpretation,
            definitions=[value.definition for value in values],
            visualization=Visualization(type="bar", data=result_rows),
            values=values,
            query=debug,
        )

    if kind == "uq08":
        if periods is None:
            current_start, current_end, previous_start, previous_end = completed_week_comparison()
            periods = (_range(current_start, current_end), _range(previous_start, previous_end))
        current, previous = periods
        rows, debug = _execute(
            engine,
            "uq08_category_comparison",
            _comparison_params(current, previous),
            request_id,
        )
        result_rows = []
        for row in rows:
            current_cents, previous_cents = int(row["current_cents"]), int(row["previous_cents"])
            result_rows.append(
                ResultRow(
                    key=str(row["category_id"]),
                    label=str(row["category_name"]),
                    values={
                        "current_sales": _format_money(current_cents),
                        "previous_sales": _format_money(previous_cents),
                        "change": _format_money(current_cents - previous_cents),
                    },
                )
            )
        interpretation = Interpretation(
            metric_ids=["sales_amount"],
            dimension_ids=["category"],
            time_range=current,
            comparison_range=previous,
            filters=[VALID_ORDER_FILTER],
            sort=["change asc", "category_id asc"],
        )
        return _base_response(
            request_id,
            turn_id,
            "completed",
            f"按截至 {(AS_OF_DATE - timedelta(days=1)).isoformat()} 已完成的周内天数比较，"
            "并按销售额下降额从大到小排列；这里只描述数据变化。",
            interpretation,
            definitions=[definitions["sales_amount"]],
            visualization=Visualization(type="bar", data=result_rows),
            values=[],
            query=debug,
        )

    if kind == "uq09":
        if periods is None:
            prompt = "请提供两个需要比较的完整日期区间。"
            return _clarification(request_id, turn_id, kind, prompt)
        current, previous = periods
        rows, debug = _execute(
            engine,
            "uq09_period_summary",
            _comparison_params(current, previous),
            request_id,
        )
        row = rows[0]
        current_cents, previous_cents = int(row["current_cents"]), int(row["previous_cents"])
        current_orders, previous_orders = int(row["current_orders"]), int(row["previous_orders"])
        current_aov = Decimal(current_cents) / current_orders if current_orders else Decimal(0)
        previous_aov = Decimal(previous_cents) / previous_orders if previous_orders else Decimal(0)
        count_contribution = int(
            ((current_orders - previous_orders) * previous_aov).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
        )
        delta = current_cents - previous_cents
        aov_contribution = delta - count_contribution
        values = [
            _metric(
                "order_count_previous",
                "对比期订单数",
                previous_orders,
                "orders",
                definitions["order_count"],
            ),
            _metric(
                "order_count_current",
                "当前期订单数",
                current_orders,
                "orders",
                definitions["order_count"],
            ),
            _metric(
                "average_order_value_previous",
                "对比期客单价",
                _format_money(int(previous_aov.quantize(Decimal(1), rounding=ROUND_HALF_UP))),
                "CNY",
                "销售额除以去重有效订单数。",
            ),
            _metric(
                "average_order_value_current",
                "当前期客单价",
                _format_money(int(current_aov.quantize(Decimal(1), rounding=ROUND_HALF_UP))),
                "CNY",
                "销售额除以去重有效订单数。",
            ),
            _metric(
                "sales_amount_delta",
                "销售额变化",
                _format_money(delta),
                "CNY",
                "当前期销售额减去对比期销售额。",
            ),
            _metric(
                "order_count_contribution",
                "订单数变化贡献",
                _format_money(count_contribution),
                "CNY",
                "按旧期客单价计算的确定性数值分解项，不代表因果。",
            ),
            _metric(
                "aov_contribution",
                "客单价变化贡献",
                _format_money(aov_contribution),
                "CNY",
                "按当前期订单数计算的确定性数值分解项，不代表因果。",
            ),
        ]
        interpretation = Interpretation(
            metric_ids=["order_count", "sales_amount", "average_order_value"],
            time_range=current,
            comparison_range=previous,
            filters=[VALID_ORDER_FILTER],
        )
        result_rows = [
            ResultRow(key=value.metric_id, label=value.label, values={value.metric_id: value.value})
            for value in values
        ]
        return _base_response(
            request_id,
            turn_id,
            "completed",
            "销售额变化可分解为订单数变化项和客单价变化项。这是恒等数值分解，不代表因果关系。",
            interpretation,
            definitions=list(definitions.values()),
            visualization=Visualization(type="table", data=result_rows),
            values=values,
            query=debug,
        )

    if kind == "ambiguous_term":
        term = _matched_catalog_term(question, "ambiguous")
        sales_metric = _METRICS_BY_ID["sales_amount"]
        prompt = (
            f"“{term.text if term else '该术语'}”没有默认映射为“{sales_metric.label}”。"
            f"“{sales_metric.label}”口径为：{sales_metric.definition}（退款不扣减）。"
            f"{term.note if term else '请澄清该术语的具体含义。'} 澄清前不执行查询。"
        )
        return _base_response(
            request_id,
            turn_id,
            "unknown_term",
            prompt,
            Interpretation(clarification_state="required"),
            suggested_terms=_active_semantic_suggestions(),
        )

    if kind == "unsupported_term":
        term = _matched_catalog_term(question, "unsupported")
        target_metric = _METRICS_BY_ID.get(term.target_id or "") if term else None
        unsupported_label = (
            target_metric.label if target_metric else (term.text if term else "该术语")
        )
        note = term.note if term else "当前没有经过审核的查询口径。"
        return _base_response(
            request_id,
            turn_id,
            "unsupported",
            f"首版暂不支持“{unsupported_label}”。{note}",
            Interpretation(),
            suggested_terms=_active_semantic_suggestions(),
        )

    if kind == "unsupported_dimension":
        dimension = _matched_inactive_dimension(question)
        return _base_response(
            request_id,
            turn_id,
            "unsupported",
            f"当前暂不支持按“{dimension.label if dimension else '该维度'}”查询。",
            Interpretation(),
            suggested_terms=_active_semantic_suggestions(),
        )

    return _base_response(
        request_id,
        turn_id,
        "unsupported",
        "暂时无法按已确认规则识别这个问题。请使用明确的指标和时间范围。",
        Interpretation(),
        suggested_terms=_active_semantic_suggestions(),
    )


def _answer_group_followup(
    dimension: str,
    metric_ids: list[str],
    date_range: TimeRange,
    request_id: str,
    turn_id: str,
    engine: Engine,
) -> TurnResponse:
    template_id = {
        "channel": "uq06_channel_aov",
        "category": "uq05_category_summary",
        "product": "followup_product_group",
    }[dimension]
    rows, debug = _execute(engine, template_id, _params_for_range(date_range), request_id)
    result_rows: list[ResultRow] = []
    total_orders = 0
    total_sales = 0
    for row in rows:
        key_field, label_field = {
            "channel": ("channel_id", "channel_name"),
            "category": ("category_id", "category_name"),
            "product": ("product_id", "product_name"),
        }[dimension]
        key, label = str(row[key_field]), str(row[label_field])
        order_count, sales_cents = int(row["order_count"]), int(row["sales_cents"])
        total_orders += order_count
        total_sales += sales_cents
        row_values: dict[str, str | int | None] = {}
        if "order_count" in metric_ids:
            row_values["order_count"] = order_count
        if "sales_amount" in metric_ids:
            row_values["sales_amount"] = _format_money(sales_cents)
        if "average_order_value" in metric_ids:
            row_values["average_order_value"] = (
                None
                if order_count == 0
                else _format_money(
                    int(
                        (Decimal(sales_cents) / order_count).quantize(
                            Decimal(1), rounding=ROUND_HALF_UP
                        )
                    )
                )
            )
        result_rows.append(ResultRow(key=key, label=label, values=row_values))

    overall_values: list[MetricValue] = []
    if "order_count" in metric_ids:
        overall_values.append(
            _metric(
                "order_count",
                "分组订单数合计",
                total_orders,
                "orders",
                METRIC_DEFINITIONS["order_count"],
            )
        )
    if "sales_amount" in metric_ids:
        overall_values.append(
            _metric(
                "sales_amount",
                "分组销售额合计",
                _format_money(total_sales),
                "CNY",
                METRIC_DEFINITIONS["sales_amount"],
            )
        )
    if "average_order_value" in metric_ids:
        average = (
            None
            if total_orders == 0
            else _format_money(
                int(
                    (Decimal(total_sales) / total_orders).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
            )
        )
        overall_values.append(
            _metric(
                "average_order_value",
                "总体客单价",
                average,
                "CNY",
                METRIC_DEFINITIONS["average_order_value"],
            )
        )
    dimension_name = {"channel": "渠道", "category": "类目", "product": "商品"}[dimension]
    note = "商品维度最多展示销售额排名前 20 个商品。" if dimension == "product" else ""
    interpretation = Interpretation(
        metric_ids=metric_ids,
        dimension_ids=[dimension],
        time_range=date_range,
        filters=[VALID_ORDER_FILTER],
        sort=["sales_amount desc", "dimension_id asc"],
        limit=20 if dimension == "product" else None,
    )
    return _base_response(
        request_id,
        turn_id,
        "completed",
        f"已沿用上一轮明确的指标和时间范围，按{dimension_name}重新分组。{note}",
        interpretation,
        definitions=[
            METRIC_DEFINITIONS[metric] for metric in metric_ids if metric in METRIC_DEFINITIONS
        ],
        visualization=Visualization(type="table", data=result_rows),
        values=overall_values,
        query=debug,
    )


def answer_question(
    question: str,
    request_id: str,
    session: ChatSession,
    engine: Engine | None = None,
    clarifies_turn_id: str | None = None,
    intent_provider: IntentProvider | None = None,
) -> TurnResponse:
    """Resolve an allowlisted question or explicitly linked clarification."""
    turn_id = str(uuid.uuid4())
    normalized = "".join(question.strip().lower().split())
    if not normalized:
        return _base_response(
            request_id,
            turn_id,
            "unsupported",
            "请输入问题后再查询。",
            Interpretation(),
            suggested_terms=_active_semantic_suggestions(),
        )
    if _contains_unsafe_instruction(normalized):
        return _base_response(
            request_id,
            turn_id,
            "unsupported",
            "这个请求包含当前不允许的操作或指令，系统没有执行任何查询。",
            Interpretation(),
            suggested_terms=_active_semantic_suggestions(),
        )
    query_engine = engine or database.engine
    date_range: TimeRange | None = None
    periods: tuple[TimeRange, TimeRange] | None = None
    kind: str | None = None
    dimension = _group_dimension(normalized)
    incoming_kind = _classify(normalized)
    if session.pending and incoming_kind and incoming_kind != session.pending.question_kind:
        # A clearly different, complete question starts a new turn instead of being
        # consumed as the answer to the previous clarification.
        session.pending = None
    is_linked_clarification = session.pending is not None
    if session.pending is None and dimension is None:
        session.last_metric_ids = None
        session.last_time_range = None
        session.last_dimension_ids = None
    if session.pending:
        pending = session.pending
        if clarifies_turn_id != pending.turn_id:
            return _base_response(
                request_id,
                turn_id,
                "clarification_required",
                "请先回答当前待澄清的问题，或重新开始一个新会话。",
                Interpretation(clarification_state="required"),
                clarification_id=pending.turn_id,
                clarification_prompt=pending.prompt,
            )
        kind = pending.question_kind
        if kind in {"uq04", "uq05", "uq06", "uq07", "uq11", "uq12"}:
            date_range = _parse_recent_range(normalized)
            if date_range is None:
                if intent_provider is not None:
                    draft = _parse_with_model(intent_provider, question, request_id, kind)
                    if draft is not None:
                        session.pending = None
                        model_result = _answer_from_model_intent(
                            draft, request_id, turn_id, session, question, query_engine
                        )
                        if model_result is not None:
                            return model_result
                return _base_response(
                    request_id,
                    turn_id,
                    "clarification_required",
                    "我还没有识别出明确的时间范围，请补充，例如“最近 30 天”。",
                    Interpretation(clarification_state="required"),
                    clarification_id=pending.turn_id,
                    clarification_prompt=pending.prompt,
                )
        elif kind == "uq09":
            periods = _parse_two_periods(normalized)
            if periods is None:
                if intent_provider is not None:
                    draft = _parse_with_model(intent_provider, question, request_id, kind)
                    if draft is not None:
                        session.pending = None
                        model_result = _answer_from_model_intent(
                            draft, request_id, turn_id, session, question, query_engine
                        )
                        if model_result is not None:
                            return model_result
                return _base_response(
                    request_id,
                    turn_id,
                    "clarification_required",
                    "日期范围不完整或超出 Mock 数据范围，请提供两个完整且不重叠的周期。",
                    Interpretation(clarification_state="required"),
                    clarification_id=pending.turn_id,
                    clarification_prompt=pending.prompt,
                )
        session.pending = None
    else:
        kind = incoming_kind
        if kind in {"uq04", "uq05", "uq06", "uq07", "uq11", "uq12"}:
            date_range = _date_range_from_question(normalized)
        if kind == "uq09":
            periods = _parse_two_periods(normalized)

    if dimension and (kind is None or kind in {"uq01", "uq02"}):
        if kind is None and session.last_metric_ids and session.last_time_range:
            if session.last_dimension_ids is not None and len(session.last_dimension_ids) > 1:
                return _base_response(
                    request_id,
                    turn_id,
                    "unsupported",
                    "当前追问只支持一个分组维度，请重新提出单维度问题。",
                    Interpretation(),
                )
            result = _answer_group_followup(
                dimension,
                session.last_metric_ids,
                session.last_time_range,
                request_id,
                turn_id,
                query_engine,
            )
            _remember_completed_plan(session, result)
            return result
        if kind == "uq01":
            date_range = _clock_range("yesterday")
        elif kind == "uq02":
            date_range = _clock_range("recent_7_days")
        if date_range is not None:
            inherited_metrics = session.last_metric_ids if kind is None else None
            inherited_range = session.last_time_range if kind is None else None
            if inherited_metrics and inherited_range and session.last_dimension_ids is not None:
                if len(session.last_dimension_ids) > 1:
                    return _base_response(
                        request_id,
                        turn_id,
                        "unsupported",
                        "当前追问只支持一个分组维度，请重新提出单维度问题。",
                        Interpretation(),
                    )
                result = _answer_group_followup(
                    dimension,
                    inherited_metrics,
                    inherited_range,
                    request_id,
                    turn_id,
                    query_engine,
                )
                _remember_completed_plan(session, result)
                return result
            if kind in {"uq01", "uq02"}:
                metric_ids = ["sales_amount", "order_count"] if kind == "uq01" else ["sales_amount"]
                result = _answer_group_followup(
                    dimension, metric_ids, date_range, request_id, turn_id, query_engine
                )
                _remember_completed_plan(session, result)
                return result
        elif kind is None:
            return _base_response(
                request_id,
                turn_id,
                "clarification_required",
                "请先明确一个指标和时间范围，再提出按单个维度分组的追问。",
                Interpretation(clarification_state="required"),
                clarification_prompt="例如：“昨天的销售额是多少？”然后再问“按渠道拆分”。",
            )

    if kind is None:
        # Call the hosted model only after deterministic parsing has failed. Known
        # refusals/terms stay local; unresolved linked clarification answers are handled above.
        if intent_provider is not None and incoming_kind is None and not is_linked_clarification:
            draft = _parse_with_model(intent_provider, question, request_id)
            if draft is not None:
                model_result = _answer_from_model_intent(
                    draft, request_id, turn_id, session, question, query_engine
                )
                if model_result is not None:
                    return model_result
        return _answer_for_kind("unsupported", question, request_id, turn_id, query_engine)

    if kind in {"uq04", "uq05", "uq06", "uq07", "uq11", "uq12"} and date_range is None:
        prompt = "请补充要查看的时间范围，例如“最近 30 天”。"
        response = _clarification(request_id, turn_id, kind, prompt)
        session.pending = PendingClarification(turn_id=turn_id, question_kind=kind, prompt=prompt)
        return response

    if kind == "uq09" and periods is None:
        prompt = (
            "请提供两个需要比较的完整日期区间，例如“比较 2025-08-28 至 2025-09-03 和之前一周”。"
        )
        response = _clarification(request_id, turn_id, kind, prompt)
        session.pending = PendingClarification(turn_id=turn_id, question_kind=kind, prompt=prompt)
        return response

    if not is_linked_clarification:
        session.last_metric_ids = None
        session.last_time_range = None
        session.last_dimension_ids = None
    result = _answer_for_kind(
        kind,
        question,
        request_id,
        turn_id,
        query_engine,
        date_range=date_range,
        periods=periods,
    )
    _remember_completed_plan(session, result)
    return result


def _remember_completed_plan(session: ChatSession, response: TurnResponse) -> None:
    if (
        response.status != "completed"
        or response.interpretation.time_range is None
        or response.interpretation.comparison_range is not None
    ):
        session.last_metric_ids = None
        session.last_time_range = None
        session.last_dimension_ids = None
        return
    session.last_metric_ids = list(response.interpretation.metric_ids)
    session.last_time_range = response.interpretation.time_range
    session.last_dimension_ids = list(response.interpretation.dimension_ids)


def _intent_context(question: str, previous_kind: str | None = None) -> IntentParseContext:
    """Build a small, question-relevant catalog context without data rows."""
    normalized = re.sub(r"[\W_]+", "", question.casefold(), flags=re.UNICODE)
    catalog = ACTIVE_CATALOG.catalog
    all_metrics = tuple(
        MetricDefinition(metric.id, metric.label, metric.definition, metric.aliases)
        for metric in catalog.metrics
        if metric.status == "active"
    )
    all_dimensions = tuple(
        DimensionDefinition(dimension.id, dimension.label, dimension.aliases)
        for dimension in catalog.dimensions
        if dimension.status == "active"
    )
    configured_capabilities = {item.id: item for item in catalog.capabilities}
    shape = configured_capabilities.get(previous_kind or "")
    if shape is not None:
        registered = SUPPORTED_CAPABILITIES.get(shape.id)
        if (
            registered is None
            or shape.template_id != registered.template_id
            or frozenset(shape.metric_ids) != registered.metric_ids
            or frozenset(shape.dimension_ids) != registered.dimension_ids
        ):
            shape = None
    metrics = tuple(
        item
        for item in all_metrics
        if any(
            re.sub(r"[\W_]+", "", alias.casefold(), flags=re.UNICODE) in normalized
            for alias in (item.label, *item.aliases)
        )
    )
    dimensions = tuple(
        item
        for item in all_dimensions
        if any(
            re.sub(r"[\W_]+", "", alias.casefold(), flags=re.UNICODE) in normalized
            for alias in (item.label, *item.aliases)
        )
    )
    # If wording uses an unknown alias, send only the compact supported catalog names
    # needed to identify an allowed concept; rows and customer/product values stay local.
    if shape is not None:
        metrics = tuple(item for item in all_metrics if item.metric_id in shape.metric_ids)
        dimensions = tuple(
            item for item in all_dimensions if item.dimension_id in shape.dimension_ids
        )
    elif not metrics:
        metrics = all_metrics
    if shape is None and not dimensions:
        dimensions = all_dimensions
    terms = tuple(
        SemanticTermDefinition(
            term_id=term.id,
            text=term.text,
            resolution=term.resolution,
            target_id=term.target_id,
            candidate_ids=term.candidate_ids,
            note=term.note,
        )
        for term in catalog.terms
        if re.sub(r"[\W_]+", "", term.text.casefold(), flags=re.UNICODE) in normalized
    )
    capability_contexts = tuple(
        IntentCapabilityDefinition(
            capability_id=item.id,
            description=item.description,
            requires_explicit_time_range=item.requires_explicit_time_range,
            requires_comparison_period=item.requires_comparison_period,
            metric_ids=item.metric_ids,
            dimension_ids=item.dimension_ids,
        )
        for item in catalog.capabilities
        if item.id in SUPPORTED_CAPABILITIES
        and item.template_id == SUPPORTED_CAPABILITIES[item.id].template_id
        and frozenset(item.metric_ids) == SUPPORTED_CAPABILITIES[item.id].metric_ids
        and frozenset(item.dimension_ids) == SUPPORTED_CAPABILITIES[item.id].dimension_ids
    )
    if shape is not None:
        capabilities = tuple(item for item in capability_contexts if item.capability_id == shape.id)
    else:
        capabilities = capability_contexts
    previous_context = None
    if shape is not None:
        previous_context = ExplicitQueryContext(
            metric_ids=shape.metric_ids,
            dimension_ids=shape.dimension_ids,
            time_start_inclusive=None,
            time_end_exclusive=None,
        )
    return IntentParseContext(
        catalog_id=CATALOG_ID,
        catalog_version=CATALOG_VERSION,
        as_of_date=AS_OF_DATE.isoformat(),
        dataset_start_date=ACTIVE_CATALOG.dataset_start_date.isoformat(),
        timezone=TIMEZONE,
        metrics=metrics,
        dimensions=dimensions,
        previous_explicit_query=previous_context,
        terms=terms,
        capabilities=capabilities,
    )


def _parse_with_model(
    provider: IntentProvider,
    question: str,
    request_id: str,
    previous_kind: str | None = None,
) -> IntentDraft | None:
    try:
        return provider.parse(question, _intent_context(question, previous_kind))
    except IntentProviderError:
        query_logger.info(
            json.dumps(
                {"event": "intent_provider_unavailable", "request_id": request_id},
                sort_keys=True,
            )
        )
        return None


def _answer_from_model_intent(
    draft: IntentDraft,
    request_id: str,
    turn_id: str,
    session: ChatSession,
    question: str,
    engine: Engine,
) -> TurnResponse | None:
    """Turn a validated model proposal into the existing fixed query executor."""
    try:
        validated = validate_intent_draft(draft)
    except IntentValidationError:
        return None
    if draft.status == "unsupported":
        return _base_response(
            request_id,
            turn_id,
            "unsupported",
            "这个问题目前不在支持范围内，没有执行查询。",
            Interpretation(),
            suggested_terms=_active_semantic_suggestions(include_dimensions=True),
        )
    if draft.status == "unknown_term":
        return _base_response(
            request_id,
            turn_id,
            "unknown_term",
            "我没有识别出问题中的业务术语。请改用已支持的指标或维度。",
            Interpretation(),
            suggested_terms=_active_semantic_suggestions(include_dimensions=True),
        )
    if draft.status == "clarification_required":
        kind = draft.question_kind
        if kind is None:
            return None
        clarification = _clarification_kind(kind)
        if clarification is None or not draft.clarification_prompt:
            return None
        _, server_prompt = clarification
        response = _clarification(request_id, turn_id, kind, server_prompt)
        session.pending = PendingClarification(
            turn_id=turn_id, question_kind=kind, prompt=server_prompt
        )
        return response
    if validated.template_id is None or draft.question_kind is None or draft.time_range is None:
        return None
    date_range = TimeRange(
        start_inclusive=draft.time_range.start_inclusive,
        end_exclusive=draft.time_range.end_exclusive,
    )
    periods = None
    if draft.comparison_range is not None:
        periods = (
            date_range,
            TimeRange(
                start_inclusive=draft.comparison_range.start_inclusive,
                end_exclusive=draft.comparison_range.end_exclusive,
            ),
        )
    result = _answer_for_kind(
        draft.question_kind,
        question,
        request_id,
        turn_id,
        engine,
        date_range=date_range,
        periods=periods,
    )
    if result.status == "clarification_required":
        session.pending = PendingClarification(
            turn_id=result.turn_id,
            question_kind=draft.question_kind,
            prompt=result.clarification_prompt or result.answer_text,
        )
    else:
        _remember_completed_plan(session, result)
    return result
