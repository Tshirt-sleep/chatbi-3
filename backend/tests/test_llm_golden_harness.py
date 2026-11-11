from __future__ import annotations

import json
from pathlib import Path

from backend.chatbi.intent_schemas import IntentDraft
from harness.run_llm_eval import evaluate_case, score_draft

ROOT = Path(__file__).resolve().parents[2]


def test_llm_golden_suite_has_a_hard_six_request_cap() -> None:
    suite = json.loads((ROOT / "harness" / "llm_golden_cases.json").read_text("utf-8"))

    assert suite["max_cases"] == 7
    assert len(suite["cases"]) == 7
    assert len({case["id"] for case in suite["cases"]}) == 7


def test_intent_golden_score_accepts_only_validated_semantics() -> None:
    draft = IntentDraft(
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

    passed, error = score_draft(
        draft,
        {
            "status": "ready",
            "question_kind": "uq04",
            "metric_ids": ["sales_amount"],
            "dimension_ids": ["product"],
            "time_range": ["2026-07-02", "2026-08-01"],
            "limit": 10,
        },
    )

    assert passed is True
    assert error is None


def test_intent_golden_score_rejects_unapproved_semantics() -> None:
    draft = IntentDraft(
        status="ready",
        question_kind="uq04",
        metric_ids=["sales_amount"],
        dimension_ids=["product"],
        time_range={
            "timezone": "Asia/Shanghai",
            "start_inclusive": "2026-07-02",
            "end_exclusive": "2026-08-01",
        },
        filter_ids=["valid_paid_orders", "customer_email"],
        sort=[{"field_id": "sales_amount", "direction": "desc"}],
        limit=10,
    )

    passed, error = score_draft(draft, {"status": "ready", "question_kind": "uq04"})

    assert passed is False
    assert error == "filter_not_allowed"


def test_llm_evaluation_case_report_omits_question_and_model_text() -> None:
    class StubProvider:
        def __init__(self) -> None:
            self.last_model_id = "test-model"
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 4}

        def parse(self, question, context):
            return IntentDraft(
                status="unknown_term",
                question_kind=None,
                metric_ids=[],
                dimension_ids=[],
                time_range=None,
                comparison_range=None,
                filter_ids=[],
                sort=[],
                limit=None,
                clarification_prompt=None,
            )

    result = evaluate_case(
        StubProvider(),
        {
            "id": "privacy-check",
            "question": "查张三GMV",
            "expected": {"status": "unknown_term"},
        },
    )
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["passed"] is True
    assert "张三" not in serialized
    assert "question" not in result
    assert "prompt" not in result
    assert "model_text" not in result
