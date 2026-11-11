import pytest
from backend.chatbi import intent_validation
from backend.chatbi.intent_schemas import IntentDraft
from backend.chatbi.intent_validation import IntentValidationError, validate_intent_draft
from backend.chatbi.llm_provider import _build_system_prompt, redact_question
from backend.chatbi.query_service import _intent_context
from backend.chatbi.semantic_catalog import ACTIVE_CATALOG


def _ready_uq04() -> IntentDraft:
    return IntentDraft(
        status="ready",
        question_kind="uq04",
        metric_ids=["sales_amount"],
        dimension_ids=["product"],
        time_range={
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2026-07-02",
            "end_exclusive": "2026-08-01",
        },
        filter_ids=["valid_paid_orders", "positive_sales"],
        sort=[{"field_id": "sales_amount", "direction": "desc"}],
        limit=10,
    )


def test_intent_context_uses_relevant_directory_definitions_and_terms() -> None:
    context = _intent_context("最近30天商品GMV和营业额")

    assert [metric.metric_id for metric in context.metrics] == ["sales_amount"]
    sales_metric = next(
        item for item in ACTIVE_CATALOG.catalog.metrics if item.id == "sales_amount"
    )
    assert context.metrics[0].label == sales_metric.label
    assert context.metrics[0].definition == sales_metric.definition
    assert context.metrics[0].aliases == sales_metric.aliases
    assert [dimension.dimension_id for dimension in context.dimensions] == ["product"]
    assert [term.text for term in context.terms] == ["营业额"]
    prompt = _build_system_prompt(context)
    assert '"resolution":"ambiguous"' in prompt
    assert "按用户给定时间范围将商品按销售额降序取前 10" in prompt
    assert '"requires_explicit_time_range":true' in prompt
    assert "uq01=yesterday" not in prompt
    assert '"template_id"' not in prompt


def test_model_intent_validation_checks_catalog_mapping_against_code_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = dict(intent_validation.CATALOG_CAPABILITIES)
    configured["uq04"] = configured["uq04"].model_copy(
        update={"template_id": "unreviewed_template"}
    )
    monkeypatch.setattr(intent_validation, "CATALOG_CAPABILITIES", configured)

    with pytest.raises(IntentValidationError, match="catalog_capability_not_allowlisted"):
        validate_intent_draft(_ready_uq04())


def test_question_redaction_uses_catalog_aliases() -> None:
    catalog = ACTIVE_CATALOG.catalog
    sales_metric = next(item for item in catalog.metrics if item.id == "sales_amount")
    extended_metric = sales_metric.model_copy(
        update={"aliases": (*sales_metric.aliases, "自定义销售指标词")}
    )
    custom_catalog = catalog.model_copy(
        update={
            "metrics": tuple(
                extended_metric if item.id == "sales_amount" else item for item in catalog.metrics
            )
        }
    )

    redacted = redact_question("查自定义销售指标词", custom_catalog)

    assert redacted is not None
    assert "自定义销售指标词" in redacted
