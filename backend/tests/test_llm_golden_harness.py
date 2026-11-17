from __future__ import annotations

import json
from pathlib import Path

from backend.chatbi.intent_schemas import IntentDraft
from harness.run_llm_eval import (
    _repository_provenance,
    evaluate_case,
    score_draft,
    select_model_fallback_cases,
)

ROOT = Path(__file__).resolve().parents[2]


def test_report_provenance_identifies_worktree_and_evaluation_inputs() -> None:
    provenance = _repository_provenance()

    assert provenance["code_revision"]
    assert isinstance(provenance["working_tree_clean"], bool)
    assert len(provenance["working_tree_status_sha256"]) == 64
    assert len(provenance["tracked_diff_sha256"]) == 64
    assert len(provenance["source_fingerprint_sha256"]) == 64
    assert provenance["source_fingerprint_file_count"] > 0


def test_llm_golden_suite_has_a_hard_seven_case_cap_and_one_fallback() -> None:
    suite = json.loads((ROOT / "harness" / "llm_golden_cases.json").read_text("utf-8"))

    assert suite["max_cases"] == 7
    assert len(suite["cases"]) == 7
    assert len({case["id"] for case in suite["cases"]}) == 7
    assert [
        case["id"] for case in suite["cases"] if case["evaluation_route"] == "model_fallback"
    ] == ["P7-04-channel-sales-situation-fallback"]


def test_model_eval_selection_requires_an_explicit_fallback_case() -> None:
    suite = json.loads((ROOT / "harness" / "llm_golden_cases.json").read_text("utf-8"))

    selected = select_model_fallback_cases(
        suite["cases"], ["P7-04-channel-sales-situation-fallback"]
    )
    assert [case["id"] for case in selected] == ["P7-04-channel-sales-situation-fallback"]

    for case_ids in ([], ["P7-01-channel-sells-how"]):
        try:
            select_model_fallback_cases(suite["cases"], case_ids)
        except ValueError:
            pass
        else:
            raise AssertionError("selection must reject missing or rule-hit case IDs")


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
    assert result["query_executed"] is False
    assert result["backend_validation_status"] == "passed"
    assert result["template_id"] is None
