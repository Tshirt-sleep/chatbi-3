import pytest
from backend.chatbi.intent_schemas import IntentDraft
from backend.chatbi.intent_validation import IntentValidationError, validate_intent_draft
from pydantic import ValidationError


def _ready_uq04(**overrides: object) -> IntentDraft:
    fields: dict[str, object] = {
        "status": "ready",
        "question_kind": "uq04",
        "metric_ids": ["sales_amount"],
        "dimension_ids": ["product"],
        "time_range": {
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2026-07-02",
            "end_exclusive": "2026-08-01",
        },
        "filter_ids": ["valid_paid_orders", "positive_sales"],
        "sort": [
            {"field_id": "sales_amount", "direction": "desc"},
            {"field_id": "product_id", "direction": "asc"},
        ],
        "limit": 10,
    }
    fields.update(overrides)
    return IntentDraft.model_validate(fields)


def test_valid_top_ten_intent_passes_semantic_validation() -> None:
    draft = _ready_uq04()
    validated = validate_intent_draft(draft)

    assert validated.draft is draft
    assert validated.template_id == "uq04_product_top"


def test_valid_category_comparison_can_sort_by_derived_change() -> None:
    draft = IntentDraft(
        status="ready",
        question_kind="uq08",
        metric_ids=["sales_amount"],
        dimension_ids=["category"],
        time_range={
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2026-07-27",
            "end_exclusive": "2026-08-01",
        },
        comparison_range={
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2026-07-20",
            "end_exclusive": "2026-07-25",
        },
        filter_ids=["valid_paid_orders"],
        sort=[
            {"field_id": "change", "direction": "asc"},
            {"field_id": "category_id", "direction": "asc"},
        ],
    )

    assert validate_intent_draft(draft).template_id == "uq08_category_comparison"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"question_kind": "uq07"}, "query_kind_not_executable"),
        ({"metric_ids": ["refund_rate"]}, "metric_set_not_allowed_for_kind"),
        ({"dimension_ids": ["region"]}, "dimension_set_not_allowed_for_kind"),
        ({"limit": 20}, "top_ten_limit_required"),
        ({"filter_ids": ["valid_paid_orders", "raw_sql"]}, "filter_not_allowed"),
        (
            {
                "time_range": {
                    "timezone": "Asia/Shanghai",
                    "start_inclusive": "2026-07-02",
                    "end_exclusive": "2026-09-01",
                }
            },
            "date_out_of_dataset",
        ),
        (
            {"sort": [{"field_id": "customer_email", "direction": "asc"}]},
            "sort_field_not_allowed",
        ),
    ],
)
def test_unsafe_or_incompatible_plans_are_rejected(
    overrides: dict[str, object], reason: str
) -> None:
    with pytest.raises(IntentValidationError) as error:
        validate_intent_draft(_ready_uq04(**overrides))

    assert error.value.reason_code == reason


def test_unknown_extra_model_fields_fail_schema_validation() -> None:
    with pytest.raises(ValidationError):
        IntentDraft.model_validate({"status": "ready", "sql": "SELECT 1"})


def test_unknown_term_cannot_resolve_to_a_query_template() -> None:
    draft = IntentDraft(status="unknown_term", question_kind="uq10")

    assert validate_intent_draft(draft).template_id is None


def test_clarification_cannot_include_executable_time_conditions() -> None:
    draft = IntentDraft(
        status="clarification_required",
        question_kind="uq04",
        metric_ids=["sales_amount"],
        dimension_ids=["product"],
        time_range={
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2026-07-02",
            "end_exclusive": "2026-08-01",
        },
        clarification_prompt="请补充时间范围。",
    )

    with pytest.raises(IntentValidationError, match="clarification_contains_executable_conditions"):
        validate_intent_draft(draft)


def test_comparison_periods_must_not_overlap() -> None:
    draft = IntentDraft(
        status="ready",
        question_kind="uq09",
        metric_ids=["order_count", "sales_amount", "average_order_value"],
        time_range={
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2025-09-01",
            "end_exclusive": "2025-09-08",
        },
        comparison_range={
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2025-09-07",
            "end_exclusive": "2025-09-14",
        },
        filter_ids=["valid_paid_orders"],
    )

    with pytest.raises(IntentValidationError, match="comparison_ranges_overlap"):
        validate_intent_draft(draft)
