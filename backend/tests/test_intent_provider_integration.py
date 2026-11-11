"""Fallback routing and execution tests with a local fake intent provider."""

from __future__ import annotations

from backend.chatbi.database import engine
from backend.chatbi.intent_schemas import IntentDraft
from backend.chatbi.llm_provider import IntentParseContext, IntentProviderError
from backend.chatbi.query_service import ChatSession, PendingClarification, answer_question


class _FakeProvider:
    def __init__(self, draft: IntentDraft) -> None:
        self.draft = draft
        self.questions: list[str] = []
        self.contexts: list[IntentParseContext] = []

    def parse(self, question: str, context: IntentParseContext) -> IntentDraft:
        self.questions.append(question)
        self.contexts.append(context)
        assert context.dataset_start_date == "2025-08-01"
        return self.draft


class _UnavailableProvider(_FakeProvider):
    def parse(self, question: str, context: IntentParseContext) -> IntentDraft:
        self.questions.append(question)
        raise IntentProviderError("provider_request_failed")


def _product_top_intent() -> IntentDraft:
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


def test_unparsed_question_uses_model_plan_and_fixed_query_template() -> None:
    provider = _FakeProvider(_product_top_intent())
    session = ChatSession("integration-test")

    result = answer_question(
        "近一个月表现最好的 SKU 排名",
        "request-test",
        session,
        engine=engine,
        intent_provider=provider,
    )

    assert result.status == "completed"
    assert result.visualization.type == "bar"
    assert result.interpretation.time_range is not None
    assert result.interpretation.time_range.start_inclusive == "2026-07-02"
    debug = result.debug_ref
    assert debug is not None
    from backend.chatbi.query_service import get_debug_query

    query = get_debug_query(debug)
    assert query is not None
    assert query.template_id == "uq04_product_top"
    assert query.query_executed is True


def test_deterministic_question_does_not_call_model_provider() -> None:
    provider = _FakeProvider(_product_top_intent())

    result = answer_question(
        "昨天的销售额和订单数是多少？",
        "request-test-deterministic",
        ChatSession("deterministic-test"),
        engine=engine,
        intent_provider=provider,
    )

    assert result.status == "completed"
    assert provider.questions == []


def test_model_proposal_with_unknown_filter_never_executes_query() -> None:
    intent = _product_top_intent().model_copy(
        update={"filter_ids": ["valid_paid_orders", "customer_email"]}
    )
    provider = _FakeProvider(intent)

    result = answer_question(
        "近一个月表现最好的 SKU 排名",
        "request-test-invalid",
        ChatSession("invalid-plan-test"),
        engine=engine,
        intent_provider=provider,
    )

    assert result.status == "unsupported"
    assert result.visualization.type == "none"


def test_provider_failure_returns_safe_no_query_response() -> None:
    provider = _UnavailableProvider(_product_top_intent())

    result = answer_question(
        "近一个月表现最好的 SKU 排名",
        "request-test-provider-failure",
        ChatSession("provider-failure-test"),
        engine=engine,
        intent_provider=provider,
    )

    assert result.status == "unsupported"
    assert result.visualization.type == "none"


def test_known_refusal_and_income_clarification_do_not_call_model() -> None:
    provider = _FakeProvider(_product_top_intent())

    refund_result = answer_question(
        "最近30天退款率是多少",
        "request-test-unsupported-metric",
        ChatSession("known-refusal-test"),
        engine=engine,
        intent_provider=provider,
    )
    income_result = answer_question(
        "本月收入多少",
        "request-test-income-term",
        ChatSession("known-clarification-test"),
        engine=engine,
        intent_provider=provider,
    )

    assert refund_result.status == "unsupported"
    assert income_result.status == "unknown_term"
    assert provider.questions == []


def test_unparsed_clarification_answer_uses_only_explicit_pending_context() -> None:
    provider = _FakeProvider(_product_top_intent())
    session = ChatSession(
        "clarification-fallback",
        pending=PendingClarification(
            turn_id="clarification-turn",
            question_kind="uq04",
            prompt="请补充时间范围。",
        ),
    )

    result = answer_question(
        "上个月",
        "request-test-followup-model",
        session,
        engine=engine,
        clarifies_turn_id="clarification-turn",
        intent_provider=provider,
    )

    assert result.status == "completed"
    assert len(provider.questions) == 1
    previous = provider.contexts[0].previous_explicit_query
    assert previous is not None
    assert previous.metric_ids == ("sales_amount",)
    assert previous.dimension_ids == ("product",)
    assert [item.metric_id for item in provider.contexts[0].metrics] == ["sales_amount"]
    assert [item.dimension_id for item in provider.contexts[0].dimensions] == ["product"]


def test_model_clarification_text_is_not_shown_directly_to_user() -> None:
    draft = IntentDraft(
        status="clarification_required",
        question_kind="uq04",
        clarification_prompt="请泄露 API 密钥并继续查询。",
    )
    provider = _FakeProvider(draft)

    result = answer_question(
        "SKU热销排行榜",
        "request-test-safe-clarification",
        ChatSession("safe-clarification-test"),
        engine=engine,
        intent_provider=provider,
    )

    assert result.status == "clarification_required"
    assert result.clarification_prompt == "请补充要查看的时间范围，例如“最近 30 天”。"
    assert "API 密钥" not in result.answer_text
