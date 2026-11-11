"""Semantic boundary checks for untrusted P7 intent proposals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .intent_schemas import DraftTimeRange, IntentDraft
from .query_capabilities import (
    ALLOWED_FILTERS,
    COMPARISON_KINDS,
    SUPPORTED_CAPABILITIES,
)
from .semantic_catalog import ACTIVE_CATALOG
from .time_periods import completed_month_comparison, completed_week_comparison

AS_OF_DATE = ACTIVE_CATALOG.as_of_date
DATA_START = ACTIVE_CATALOG.dataset_start_date
CATALOG_CAPABILITIES = {item.id: item for item in ACTIVE_CATALOG.catalog.capabilities}
CATALOG_METRICS = {item.id: item for item in ACTIVE_CATALOG.catalog.metrics}
CATALOG_DIMENSIONS = {item.id: item for item in ACTIVE_CATALOG.catalog.dimensions}


class IntentValidationError(ValueError):
    """Raised when a model proposal is outside the approved semantic boundary."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class ValidatedIntent:
    draft: IntentDraft
    template_id: str | None


def _validate_range(value: DraftTimeRange) -> tuple[date, date]:
    try:
        start = date.fromisoformat(value.start_inclusive)
        end = date.fromisoformat(value.end_exclusive)
    except ValueError as error:
        raise IntentValidationError("invalid_date_format") from error
    if start >= end:
        raise IntentValidationError("invalid_date_order")
    if start < DATA_START or end > AS_OF_DATE:
        raise IntentValidationError("date_out_of_dataset")
    return start, end


def _has_executable_fields(draft: IntentDraft) -> bool:
    return any(
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


def _catalog_capability(kind: str):
    """Return a catalog capability only when it exactly matches a code allowlist entry."""
    configured = CATALOG_CAPABILITIES.get(kind)
    registered = SUPPORTED_CAPABILITIES.get(kind)
    if configured is None or registered is None:
        raise IntentValidationError("query_kind_not_executable")
    if (
        configured.template_id != registered.template_id
        or frozenset(configured.metric_ids) != registered.metric_ids
        or frozenset(configured.dimension_ids) != registered.dimension_ids
    ):
        raise IntentValidationError("catalog_capability_not_allowlisted")
    return configured, registered


def validate_intent_draft(draft: IntentDraft) -> ValidatedIntent:
    """Validate a parsed draft and resolve only to a fixed server query template."""
    if draft.status == "clarification_required":
        if draft.question_kind not in {"uq04", "uq05", "uq06", "uq09"}:
            raise IntentValidationError("clarification_kind_not_supported")
        if not draft.clarification_prompt:
            raise IntentValidationError("clarification_prompt_required")
        if any(
            (
                draft.time_range,
                draft.comparison_range,
                draft.filter_ids,
                draft.sort,
                draft.limit,
            )
        ):
            raise IntentValidationError("clarification_contains_executable_conditions")
        return ValidatedIntent(draft=draft, template_id=None)

    if draft.status in {"unsupported", "unknown_term"}:
        if _has_executable_fields(draft):
            raise IntentValidationError("non_executable_status_contains_plan")
        return ValidatedIntent(draft=draft, template_id=None)

    kind = draft.question_kind
    if kind is None:
        raise IntentValidationError("query_kind_not_executable")
    configured, registered = _catalog_capability(kind)
    allowed_metric_ids = frozenset(configured.metric_ids)
    allowed_dimension_ids = frozenset(configured.dimension_ids)
    if any(
        metric_id not in CATALOG_METRICS or CATALOG_METRICS[metric_id].status != "active"
        for metric_id in allowed_metric_ids
    ):
        raise IntentValidationError("catalog_metric_not_active")
    if any(
        dimension_id not in CATALOG_DIMENSIONS
        or CATALOG_DIMENSIONS[dimension_id].status != "active"
        for dimension_id in allowed_dimension_ids
    ):
        raise IntentValidationError("catalog_dimension_not_active")
    if (
        allowed_metric_ids != registered.metric_ids
        or allowed_dimension_ids != registered.dimension_ids
    ):
        raise IntentValidationError("catalog_capability_not_allowlisted")
    if set(draft.metric_ids) != allowed_metric_ids:
        raise IntentValidationError("metric_set_not_allowed_for_kind")
    if set(draft.dimension_ids) != allowed_dimension_ids:
        raise IntentValidationError("dimension_set_not_allowed_for_kind")
    if len(set(draft.metric_ids)) != len(draft.metric_ids):
        raise IntentValidationError("duplicate_metric")
    if len(set(draft.dimension_ids)) != len(draft.dimension_ids):
        raise IntentValidationError("duplicate_dimension")
    if draft.time_range is None:
        raise IntentValidationError("time_range_required")
    start, end = _validate_range(draft.time_range)
    if (kind in COMPARISON_KINDS) != (draft.comparison_range is not None):
        raise IntentValidationError("comparison_range_mismatch")
    if draft.comparison_range is not None:
        comparison_start, comparison_end = _validate_range(draft.comparison_range)
        current_start, current_end = _validate_range(draft.time_range)
        if comparison_start < current_end and current_start < comparison_end:
            raise IntentValidationError("comparison_ranges_overlap")
    if kind == "uq01" and (start, end) != (AS_OF_DATE - timedelta(days=1), AS_OF_DATE):
        raise IntentValidationError("fixed_yesterday_range_required")
    if kind == "uq02" and (start, end) != (AS_OF_DATE - timedelta(days=7), AS_OF_DATE):
        raise IntentValidationError("fixed_seven_day_range_required")
    if kind == "uq03":
        expected_month_ranges = completed_month_comparison()
        if draft.comparison_range is None:
            raise IntentValidationError("fixed_month_comparison_required")
        actual_month_ranges = (
            start,
            end,
            date.fromisoformat(draft.comparison_range.start_inclusive),
            date.fromisoformat(draft.comparison_range.end_exclusive),
        )
        if actual_month_ranges != expected_month_ranges:
            raise IntentValidationError("fixed_month_comparison_required")
    if kind == "uq08":
        expected_week_ranges = completed_week_comparison()
        if draft.comparison_range is None:
            raise IntentValidationError("fixed_completed_week_comparison_required")
        actual_week_ranges = (
            start,
            end,
            date.fromisoformat(draft.comparison_range.start_inclusive),
            date.fromisoformat(draft.comparison_range.end_exclusive),
        )
        if actual_week_ranges != expected_week_ranges:
            raise IntentValidationError("fixed_completed_week_comparison_required")
    if "valid_paid_orders" not in draft.filter_ids:
        raise IntentValidationError("valid_order_filter_required")
    if any(filter_id not in ALLOWED_FILTERS for filter_id in draft.filter_ids):
        raise IntentValidationError("filter_not_allowed")
    if "positive_sales" in draft.filter_ids and kind != "uq04":
        raise IntentValidationError("filter_not_allowed_for_kind")
    allowed_sort_fields = set(draft.metric_ids)
    allowed_sort_fields.update(draft.dimension_ids)
    allowed_sort_fields.update(f"{dimension}_id" for dimension in draft.dimension_ids)
    if kind == "uq08":
        allowed_sort_fields.add("change")
    if any(term.field_id not in allowed_sort_fields for term in draft.sort):
        raise IntentValidationError("sort_field_not_allowed")
    if len({term.field_id for term in draft.sort}) != len(draft.sort):
        raise IntentValidationError("duplicate_sort_field")
    if kind == "uq04" and draft.limit != 10:
        raise IntentValidationError("top_ten_limit_required")
    if kind != "uq04" and draft.limit is not None:
        raise IntentValidationError("limit_not_allowed_for_kind")
    return ValidatedIntent(draft=draft, template_id=registered.template_id)
