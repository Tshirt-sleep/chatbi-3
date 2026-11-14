"""Deterministic, code-allowlisted query plans for the SaaS Mock theme."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from datetime import time as day_time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import database
from .intent_schemas import IntentDraft
from .llm_provider import (
    DimensionDefinition,
    IntentCapabilityDefinition,
    IntentParseContext,
    IntentProvider,
    IntentProviderError,
    MetricDefinition,
    SemanticTermDefinition,
)
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
from .saas_catalog import ACTIVE_SAAS_CATALOG, DATASET_ID

CATALOG = ACTIVE_SAAS_CATALOG.catalog
AS_OF = ACTIVE_SAAS_CATALOG.as_of_date
UTC_PLUS_8 = timezone(timedelta(hours=8))
query_logger = logging.getLogger("uvicorn.error")

SQL_TEMPLATES = {
    "saas_active_snapshot": """
        SELECT COUNT(DISTINCT subscription_id) AS active_count
        FROM saas_subscriptions
        WHERE dataset_id = :dataset_id AND status = 'active'
          AND started_at < :as_of_exclusive
          AND (canceled_at IS NULL OR canceled_at >= :as_of_exclusive)
    """,
    "saas_mrr_snapshot": """
        SELECT COALESCE(SUM(p.monthly_fee_cents), 0) AS mrr_cents
        FROM saas_subscriptions s
        JOIN saas_plans p ON p.dataset_id = s.dataset_id AND p.plan_id = s.plan_id
        WHERE s.dataset_id = :dataset_id AND s.status = 'active' AND p.status = 'active'
          AND s.started_at < :as_of_exclusive
          AND (s.canceled_at IS NULL OR s.canceled_at >= :as_of_exclusive)
    """,
    "saas_new_subscriptions_period": """
        SELECT COUNT(DISTINCT subscription_id) AS new_count
        FROM saas_subscriptions
        WHERE dataset_id = :dataset_id AND started_at >= :start_inclusive AND started_at < :end_exclusive
    """,
    "saas_new_subscriptions_trend": """
        SELECT substr(started_at, 1, 10) AS day, COUNT(DISTINCT subscription_id) AS new_count
        FROM saas_subscriptions
        WHERE dataset_id = :dataset_id AND started_at >= :start_inclusive AND started_at < :end_exclusive
        GROUP BY substr(started_at, 1, 10) ORDER BY day ASC
    """,
    "saas_active_by_plan": """
        SELECT p.plan_id, p.plan_name, COUNT(DISTINCT s.subscription_id) AS active_count
        FROM saas_plans p
        LEFT JOIN saas_subscriptions s ON s.dataset_id = p.dataset_id AND s.plan_id = p.plan_id
          AND s.status = 'active' AND s.started_at < :as_of_exclusive
          AND (s.canceled_at IS NULL OR s.canceled_at >= :as_of_exclusive)
        WHERE p.dataset_id = :dataset_id AND p.status = 'active'
        GROUP BY p.plan_id, p.plan_name ORDER BY active_count DESC, p.plan_id ASC
    """,
    "saas_mrr_by_plan": """
        SELECT p.plan_id, p.plan_name, COUNT(DISTINCT s.subscription_id) AS active_count,
               COALESCE(SUM(CASE WHEN s.subscription_id IS NOT NULL THEN p.monthly_fee_cents ELSE 0 END), 0) AS mrr_cents
        FROM saas_plans p
        LEFT JOIN saas_subscriptions s ON s.dataset_id = p.dataset_id AND s.plan_id = p.plan_id
          AND s.status = 'active' AND s.started_at < :as_of_exclusive
          AND (s.canceled_at IS NULL OR s.canceled_at >= :as_of_exclusive)
        WHERE p.dataset_id = :dataset_id AND p.status = 'active'
        GROUP BY p.plan_id, p.plan_name ORDER BY mrr_cents DESC, p.plan_id ASC
    """,
}


def _bound(day: date) -> str:
    return datetime.combine(day, day_time.min, tzinfo=UTC_PLUS_8).isoformat()


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _range(start: date, end: date) -> TimeRange:
    return TimeRange(start_inclusive=start.isoformat(), end_exclusive=end.isoformat())


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _matched_ids(value: str, entities: tuple[Any, ...]) -> set[str]:
    normalized = _normalize(value)
    return {
        entity.id
        for entity in entities
        if any(
            _normalize(alias) in normalized for alias in (entity.label, *entity.aliases) if alias
        )
    }


def _intent_context() -> IntentParseContext:
    return IntentParseContext(
        catalog_id=CATALOG.catalog_id,
        catalog_version=CATALOG.version,
        as_of_date=AS_OF.isoformat(),
        dataset_start_date=ACTIVE_SAAS_CATALOG.start_date.isoformat(),
        timezone=CATALOG.timezone,
        metrics=tuple(
            MetricDefinition(item.id, item.label, item.definition, item.aliases)
            for item in CATALOG.metrics
        ),
        dimensions=tuple(
            DimensionDefinition(item.id, item.label, item.aliases) for item in CATALOG.dimensions
        ),
        terms=tuple(
            SemanticTermDefinition(
                item.id,
                item.text,
                item.resolution,
                item.target_id,
                item.candidate_ids,
                item.note,
            )
            for item in CATALOG.terms
        ),
        capabilities=(
            IntentCapabilityDefinition(
                "saas01",
                "截至固定参考日统计活跃订阅数",
                False,
                False,
                ("active_subscriptions",),
                (),
            ),
            IntentCapabilityDefinition(
                "saas02",
                "截至固定参考日统计月度经常性收入（MRR）",
                False,
                False,
                ("mrr",),
                (),
            ),
            IntentCapabilityDefinition(
                "saas03",
                "在明确完整自然日时间范围内统计新增订阅数",
                True,
                False,
                ("new_subscriptions",),
                ("subscription_date",),
            ),
            IntentCapabilityDefinition(
                "saas04",
                "按套餐分组统计固定参考日活跃订阅数",
                False,
                False,
                ("active_subscriptions",),
                ("plan",),
            ),
            IntentCapabilityDefinition(
                "saas05",
                "按套餐分组统计固定参考日月度经常性收入（MRR）",
                False,
                False,
                ("mrr",),
                ("plan",),
            ),
            IntentCapabilityDefinition(
                "saas06",
                "在明确完整自然日时间范围内按日展示新增订阅趋势",
                True,
                False,
                ("new_subscriptions",),
                ("subscription_date",),
            ),
        ),
    )


def _validated_model_plan(
    draft: IntentDraft,
) -> tuple[str, TimeRange | str | None]:
    """Validate SaaS intent output against exact code-owned capability contracts."""
    if draft.status in {"unsupported", "unknown_term"}:
        if any(
            (
                draft.question_kind,
                draft.metric_ids,
                draft.dimension_ids,
                draft.time_range,
                draft.comparison_range,
                draft.filter_ids,
                draft.sort,
                draft.limit,
            )
        ):
            return "invalid", None
        return draft.status, None
    if draft.status == "clarification_required":
        if (
            draft.question_kind not in {"saas03", "saas06"}
            or not draft.clarification_prompt
            or any(
                (
                    draft.metric_ids,
                    draft.dimension_ids,
                    draft.time_range,
                    draft.comparison_range,
                    draft.filter_ids,
                    draft.sort,
                    draft.limit,
                )
            )
        ):
            return "invalid", None
        return "clarification_required", draft.clarification_prompt

    contracts = {
        "saas01": (frozenset({"active_subscriptions"}), frozenset(), False),
        "saas02": (frozenset({"mrr"}), frozenset(), False),
        "saas03": (
            frozenset({"new_subscriptions"}),
            frozenset({"subscription_date"}),
            True,
        ),
        "saas04": (frozenset({"active_subscriptions"}), frozenset({"plan"}), False),
        "saas05": (frozenset({"mrr"}), frozenset({"plan"}), False),
        "saas06": (
            frozenset({"new_subscriptions"}),
            frozenset({"subscription_date"}),
            True,
        ),
    }
    kind = draft.question_kind
    contract = contracts.get(kind or "")
    if contract is None or kind is None or draft.status != "ready":
        return "invalid", None
    metric_ids, dimension_ids, needs_time = contract
    if (
        frozenset(draft.metric_ids) != metric_ids
        or frozenset(draft.dimension_ids) != dimension_ids
        or draft.comparison_range is not None
        or draft.filter_ids
        or draft.sort
        or draft.limit is not None
    ):
        return "invalid", None
    time_range = draft.time_range
    if needs_time and time_range is None:
        return "clarification_required", "请提供完整的新增订阅查询时间范围。"
    if not needs_time and time_range is not None:
        return "invalid", None
    if time_range is not None:
        try:
            start = date.fromisoformat(time_range.start_inclusive)
            end = date.fromisoformat(time_range.end_exclusive)
        except ValueError:
            return "invalid", None
        if (
            time_range.timezone != CATALOG.timezone
            or start >= end
            or start < ACTIVE_SAAS_CATALOG.start_date
            or end > AS_OF
        ):
            return "invalid", None
        return kind, TimeRange(start_inclusive=start.isoformat(), end_exclusive=end.isoformat())
    return kind, None


def _time_range(question: str) -> TimeRange | None:
    if "最近7天" in question or "近7天" in question:
        return _range(AS_OF - timedelta(days=7), AS_OF)
    if "昨天" in question:
        return _range(AS_OF - timedelta(days=1), AS_OF)
    match = re.search(
        r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?\s*(?:至|到|~|—)\s*(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?",
        question,
    )
    if match:
        y1, m1, d1, y2, m2, d2 = map(int, match.groups())
        start = date(y1, m1, d1)
        end = date(y2, m2, d2) + timedelta(days=1)
        if start < end and ACTIVE_SAAS_CATALOG.start_date <= start and end <= AS_OF:
            return _range(start, end)
    return None


def _execute(
    engine: Engine, template_id: str, params: Mapping[str, str | int], request_id: str
) -> tuple[list[dict[str, Any]], QueryDebug]:
    sql = SQL_TEMPLATES[template_id].strip()
    query_id = str(uuid.uuid4())
    started = time.perf_counter()
    with engine.connect() as connection:
        rows = [dict(row._mapping) for row in connection.execute(text(sql), params)]
    duration_ms = round((time.perf_counter() - started) * 1000)
    query_logger.info(
        json.dumps(
            {
                "event": "query_execution",
                "request_id": request_id,
                "query_id": query_id,
                "dataset_id": DATASET_ID,
                "dataset_version": ACTIVE_SAAS_CATALOG.dataset_version,
                "semantic_catalog_id": CATALOG.catalog_id,
                "semantic_catalog_version": CATALOG.version,
                "template_id": template_id,
                "query_executed": True,
                "duration_ms": duration_ms,
                "result_row_count": len(rows),
                **release_fields(),
            },
            sort_keys=True,
        )
    )
    debug = QueryDebug(
        query_id=query_id,
        template_id=template_id,
        sql=sql,
        parameters=dict(params),
        query_executed=True,
        duration_ms=duration_ms,
        result_row_count=len(rows),
    )
    return rows, debug


def _response(
    request_id: str,
    turn_id: str,
    status: str,
    answer: str,
    interpretation: Interpretation,
    *,
    metrics: list[MetricValue] | None = None,
    visualization: Visualization | None = None,
    prompt: str | None = None,
    suggestions: list[str] | None = None,
    query: QueryDebug | None = None,
) -> TurnResponse:
    debug = query or QueryDebug(
        query_id=str(uuid.uuid4()), template_id="none", sql="", parameters={}, query_executed=False
    )
    from .query_service import debug_query_cache

    debug_query_cache[debug.query_id] = debug
    definitions = {item.id: item.definition for item in CATALOG.metrics}
    return TurnResponse(
        request_id=request_id,
        turn_id=turn_id,
        status=status,  # type: ignore[arg-type]
        answer_text=answer,
        clarification_id=turn_id if status == "clarification_required" else None,
        clarification_prompt=prompt,
        suggested_terms=suggestions or [],
        values=metrics or [],
        interpretation=interpretation,
        visualization=visualization or Visualization(type="none"),
        evidence=Evidence(
            dataset_id=DATASET_ID,
            dataset_version=ACTIVE_SAAS_CATALOG.dataset_version,
            semantic_catalog_id=CATALOG.catalog_id,
            semantic_catalog_version=CATALOG.version,
            metric_definitions=[definitions[item.metric_id] for item in (metrics or [])],
        ),
        debug_ref=debug.query_id,
    )


def answer_saas_question(
    question: str,
    request_id: str,
    engine: Engine | None = None,
    intent_provider: IntentProvider | None = None,
) -> TurnResponse:
    """Resolve only supported SaaS questions; never infer unsupported business meanings."""
    turn_id = str(uuid.uuid4())
    normalized = _normalize(question)
    metric_ids = _matched_ids(question, CATALOG.metrics)
    dimension_ids = _matched_ids(question, CATALOG.dimensions)
    matched_term = next(
        (
            term
            for term in CATALOG.terms
            if _normalize(term.text) in normalized
            and not (term.resolution == "ambiguous" and "mrr" in metric_ids)
        ),
        None,
    )
    if matched_term is not None:
        is_ambiguous = matched_term.resolution == "ambiguous"
        return _response(
            request_id,
            turn_id,
            "clarification_required" if is_ambiguous else "unknown_term",
            matched_term.note,
            Interpretation(clarification_state="required" if is_ambiguous else "none"),
            prompt=matched_term.note if is_ambiguous else None,
            suggestions=["活跃订阅数", "MRR", "新增订阅数"],
        )

    has_mrr = "mrr" in metric_ids
    has_active = "active_subscriptions" in metric_ids
    has_new = "new_subscriptions" in metric_ids
    by_plan = "plan" in dimension_ids
    if has_new:
        selected_range = _time_range(question)
        if selected_range is None:
            return _response(
                request_id,
                turn_id,
                "clarification_required",
                "查询新增订阅数前需要明确时间范围。",
                Interpretation(
                    metric_ids=["new_subscriptions"],
                    dimension_ids=["subscription_date"],
                    clarification_state="required",
                ),
                prompt="请选择或补充完整自然日时间范围，例如最近 7 天或昨天。",
                suggestions=["最近 7 天新增订阅数", "昨天新增订阅数"],
            )
        params = {
            "dataset_id": DATASET_ID,
            "start_inclusive": _bound(date.fromisoformat(selected_range.start_inclusive)),
            "end_exclusive": _bound(date.fromisoformat(selected_range.end_exclusive)),
        }
        query_engine = engine or database.engine
        if "按日" in normalized or "每天" in normalized or "趋势" in normalized:
            rows, debug = _execute(query_engine, "saas_new_subscriptions_trend", params, request_id)
            daily_counts = {str(row["day"]): int(row["new_count"]) for row in rows}
            start_day = date.fromisoformat(selected_range.start_inclusive)
            end_day = date.fromisoformat(selected_range.end_exclusive)
            chart_dates: list[date] = []
            day = start_day
            while day < end_day:
                chart_dates.append(day)
                day += timedelta(days=1)
            chart_rows = [
                ResultRow(
                    key=day.isoformat(),
                    label=day.isoformat(),
                    values={"new_subscriptions": daily_counts.get(day.isoformat(), 0)},
                )
                for day in chart_dates
            ]
            return _response(
                request_id,
                turn_id,
                "completed",
                "已按订阅开始日期统计新增订阅数。",
                Interpretation(
                    metric_ids=["new_subscriptions"],
                    dimension_ids=["subscription_date"],
                    time_range=selected_range,
                    filters=[
                        "subscription status in active or canceled; count distinct subscription_id"
                    ],
                ),
                metrics=[
                    MetricValue(
                        metric_id="new_subscriptions",
                        label="新增订阅数",
                        value=sum(daily_counts.values()),
                        unit="subscription",
                        definition=CATALOG.metrics[2].definition,
                    )
                ],
                visualization=Visualization(type="line", data=chart_rows),
                query=debug,
            )
        rows, debug = _execute(query_engine, "saas_new_subscriptions_period", params, request_id)
        count = int(rows[0]["new_count"])
        return _response(
            request_id,
            turn_id,
            "completed",
            "已按订阅开始日期统计新增订阅数。",
            Interpretation(
                metric_ids=["new_subscriptions"],
                dimension_ids=["subscription_date"],
                time_range=selected_range,
            ),
            metrics=[
                MetricValue(
                    metric_id="new_subscriptions",
                    label="新增订阅数",
                    value=count,
                    unit="subscription",
                    definition=CATALOG.metrics[2].definition,
                )
            ],
            visualization=Visualization(
                type="kpi",
                data=[
                    ResultRow(
                        key="new_subscriptions",
                        label="新增订阅数",
                        values={"new_subscriptions": count},
                    )
                ],
            ),
            query=debug,
        )

    if (has_mrr or has_active) and by_plan:
        template = "saas_mrr_by_plan" if has_mrr else "saas_active_by_plan"
        metric_id = "mrr" if has_mrr else "active_subscriptions"
        rows, debug = _execute(
            engine or database.engine,
            template,
            {"dataset_id": DATASET_ID, "as_of_exclusive": _bound(AS_OF)},
            request_id,
        )
        result_rows = []
        total = 0
        for row in rows:
            plan_value = int(row["mrr_cents"]) if has_mrr else int(row["active_count"])
            total += plan_value
            result_rows.append(
                ResultRow(
                    key=str(row["plan_id"]),
                    label=str(row["plan_name"]),
                    values={metric_id: _money(plan_value) if has_mrr else plan_value},
                )
            )
        metric_value: str | int = _money(total) if has_mrr else total
        label = "月度经常性收入（MRR）" if has_mrr else "活跃订阅数"
        unit = "CNY/month" if has_mrr else "subscription"
        definition = next(metric.definition for metric in CATALOG.metrics if metric.id == metric_id)
        return _response(
            request_id,
            turn_id,
            "completed",
            f"已按套餐汇总参考日的{label}。",
            Interpretation(
                metric_ids=[metric_id],
                dimension_ids=["plan"],
                filters=["reference date snapshot", "active subscriptions only"],
                sort=[f"{metric_id} desc"],
            ),
            metrics=[
                MetricValue(
                    metric_id=metric_id,
                    label=label,
                    value=metric_value,
                    unit=unit,
                    definition=definition,
                )
            ],
            visualization=Visualization(type="bar", data=result_rows),
            query=debug,
        )

    if has_mrr or has_active:
        template = "saas_mrr_snapshot" if has_mrr else "saas_active_snapshot"
        rows, debug = _execute(
            engine or database.engine,
            template,
            {"dataset_id": DATASET_ID, "as_of_exclusive": _bound(AS_OF)},
            request_id,
        )
        metric_id = "mrr" if has_mrr else "active_subscriptions"
        result_value: str | int = (
            _money(int(rows[0]["mrr_cents"])) if has_mrr else int(rows[0]["active_count"])
        )
        label = "月度经常性收入（MRR）" if has_mrr else "活跃订阅数"
        unit = "CNY/month" if has_mrr else "subscription"
        definition = next(metric.definition for metric in CATALOG.metrics if metric.id == metric_id)
        return _response(
            request_id,
            turn_id,
            "completed",
            f"已按 {AS_OF.isoformat()} 参考日快照计算{label}。",
            Interpretation(
                metric_ids=[metric_id],
                filters=["reference date snapshot", "active subscriptions only"],
            ),
            metrics=[
                MetricValue(
                    metric_id=metric_id,
                    label=label,
                    value=result_value,
                    unit=unit,
                    definition=definition,
                )
            ],
            visualization=Visualization(
                type="kpi",
                data=[ResultRow(key=metric_id, label=label, values={metric_id: result_value})],
            ),
            query=debug,
        )

    if intent_provider is not None:
        try:
            draft = intent_provider.parse(question, _intent_context())
        except (IntentProviderError, ValueError):
            draft = None
        if draft is not None:
            plan_kind, planned_range = _validated_model_plan(draft)
            if plan_kind == "clarification_required":
                metric_id = "new_subscriptions"
                return _response(
                    request_id,
                    turn_id,
                    "clarification_required",
                    "查询新增订阅数前需要明确时间范围。",
                    Interpretation(
                        metric_ids=[metric_id],
                        dimension_ids=["subscription_date"],
                        clarification_state="required",
                    ),
                    prompt=str(planned_range),
                    suggestions=["最近 7 天新增订阅数", "昨天新增订阅数"],
                )
            if plan_kind in {"unsupported", "unknown_term"}:
                return _response(
                    request_id,
                    turn_id,
                    "unknown_term",
                    "当前语义目录无法安全识别这个 SaaS 问法。可以尝试活跃订阅数、MRR 或新增订阅数。",
                    Interpretation(),
                    suggestions=["活跃订阅数", "MRR", "新增订阅数"],
                )
            if isinstance(planned_range, TimeRange):
                final_day = date.fromisoformat(planned_range.end_exclusive) - timedelta(days=1)
                canonical = f"新增订阅数 {planned_range.start_inclusive} 至 {final_day.isoformat()}"
                if plan_kind == "saas06":
                    canonical += " 每天趋势"
                return answer_saas_question(
                    canonical,
                    request_id,
                    engine=engine,
                    intent_provider=None,
                )
            if plan_kind in {"saas01", "saas02", "saas04", "saas05"}:
                canonical = {
                    "saas01": "活跃订阅数",
                    "saas02": "MRR",
                    "saas04": "活跃订阅数按套餐",
                    "saas05": "MRR按套餐",
                }[plan_kind]
                return answer_saas_question(
                    canonical,
                    request_id,
                    engine=engine,
                    intent_provider=None,
                )

    return _response(
        request_id,
        turn_id,
        "unsupported",
        "未识别该 SaaS 问法。当前支持活跃订阅数、MRR、新增订阅数及套餐分组。",
        Interpretation(),
        suggestions=["活跃订阅数", "当前 MRR", "最近 7 天新增订阅数", "按套餐看活跃订阅数"],
    )
