"""Run P8-4 SaaS route-contract acceptance against independently read Mock CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

os.environ.setdefault("CHATBI_DEBUG_ENABLED", "true")

from backend.chatbi.intent_schemas import IntentDraft
from backend.chatbi.llm_provider import IntentParseContext
from backend.chatbi.main import create_session, get_query_debug, submit_turn
from backend.chatbi.query_schemas import (
    CreateSessionRequest,
    SessionResponse,
    TurnRequest,
    TurnResponse,
)
from backend.chatbi.saas_catalog import ACTIVE_SAAS_CATALOG, DATASET_ID
from backend.chatbi.saas_query_service import answer_saas_question
from backend.chatbi.semantic_catalog import ACTIVE_CATALOG

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "generated" / DATASET_ID


class FixedIntentProvider:
    def __init__(self, draft: IntentDraft) -> None:
        self.draft = draft
        self.context: IntentParseContext | None = None

    def parse(self, _question: str, context: IntentParseContext) -> IntentDraft:
        self.context = context
        return self.draft


def _read(name: str) -> list[dict[str, str]]:
    with (DATA_DIR / name).open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def expected_values() -> dict[str, Any]:
    subscriptions = _read("subscriptions.csv")
    plans = {row["plan_id"]: row for row in _read("plans.csv")}
    as_of = ACTIVE_SAAS_CATALOG.as_of_date.isoformat() + "T00:00:00+08:00"
    active = [
        row
        for row in subscriptions
        if row["status"] == "active"
        and row["started_at"] < as_of
        and (not row["canceled_at"] or row["canceled_at"] >= as_of)
    ]
    mrr_cents = sum(int(plans[row["plan_id"]]["monthly_fee_cents"]) for row in active)
    by_plan: dict[str, dict[str, int]] = {
        plan_id: {"active_subscriptions": 0, "mrr_cents": 0} for plan_id in plans
    }
    for row in active:
        by_plan[row["plan_id"]]["active_subscriptions"] += 1
        by_plan[row["plan_id"]]["mrr_cents"] += int(
            plans[row["plan_id"]]["monthly_fee_cents"]
        )
    start = ACTIVE_SAAS_CATALOG.as_of_date - timedelta(days=7)
    daily_counts: dict[str, int] = {}
    for row in subscriptions:
        day = date.fromisoformat(row["started_at"][:10])
        if start <= day < ACTIVE_SAAS_CATALOG.as_of_date:
            daily_counts[day.isoformat()] = daily_counts.get(day.isoformat(), 0) + 1
    return {
        "active_count": len(active),
        "mrr": f"{mrr_cents // 100}.{mrr_cents % 100:02d}",
        "by_plan": by_plan,
        "daily_new": [
            {
                "day": (start + timedelta(days=index)).isoformat(),
                "count": daily_counts.get(
                    (start + timedelta(days=index)).isoformat(), 0
                ),
            }
            for index in range(7)
        ],
    }


def run() -> dict[str, Any]:
    expected = expected_values()
    checks: list[dict[str, Any]] = []
    request = SimpleNamespace(
        state=SimpleNamespace(request_id="p8-saas-harness"),
        headers={"x-mock-user": "analyst"},
    )
    session_model = create_session(CreateSessionRequest(dataset_id=DATASET_ID), request)
    session = SessionResponse.model_validate(
        session_model.model_dump(mode="json")
    ).model_dump(mode="json")
    checks.append(
        {
            "id": "session_topic_metadata",
            "passed": session["dataset_id"] == DATASET_ID
            and session["semantic_catalog_id"] == ACTIVE_SAAS_CATALOG.catalog.catalog_id
            and session["semantic_catalog_version"]
            == ACTIVE_SAAS_CATALOG.catalog.version,
        }
    )

    def ask(question: str) -> tuple[dict[str, Any], dict[str, Any]]:
        response = submit_turn(
            session["session_id"], TurnRequest(question=question), request
        )
        result = TurnResponse.model_validate(
            response.model_dump(mode="json")
        ).model_dump(mode="json")
        debug_model = get_query_debug(result["debug_ref"], request)
        if debug_model is None:
            raise RuntimeError("Query debug evidence is missing")
        return result, debug_model.model_dump(mode="json")

    active, active_debug = ask("截至参考日有多少活跃订阅？")
    active_value = next(
        value["value"]
        for value in active["values"]
        if value["metric_id"] == "active_subscriptions"
    )
    checks.append(
        {
            "id": "active_snapshot",
            "expected": expected["active_count"],
            "actual": active_value,
            "passed": active_value == expected["active_count"]
            and active_debug["query_executed"],
        }
    )

    mrr, mrr_debug = ask("当前 MRR 是多少？")
    mrr_value = next(
        value["value"] for value in mrr["values"] if value["metric_id"] == "mrr"
    )
    checks.append(
        {
            "id": "mrr_snapshot",
            "expected": expected["mrr"],
            "actual": mrr_value,
            "passed": mrr_value == expected["mrr"]
            and mrr["values"][0]["metric_id"] == "mrr"
            and "标准月付价" in mrr["values"][0]["definition"]
            and mrr_debug["query_executed"],
        }
    )

    by_plan_result, plan_debug = ask("按套餐看当前活跃订阅数")
    actual_by_plan = {
        row["key"]: int(row["values"]["active_subscriptions"])
        for row in by_plan_result["visualization"]["data"]
    }
    expected_by_plan = {
        key: value["active_subscriptions"] for key, value in expected["by_plan"].items()
    }
    checks.append(
        {
            "id": "active_by_plan",
            "expected": expected_by_plan,
            "actual": actual_by_plan,
            "passed": actual_by_plan == expected_by_plan
            and plan_debug["query_executed"],
        }
    )

    mrr_by_plan, mrr_plan_debug = ask("按套餐看当前 MRR")
    actual_mrr_by_plan = {
        row["key"]: row["values"]["mrr"] for row in mrr_by_plan["visualization"]["data"]
    }
    expected_mrr_by_plan = {
        key: f"{value['mrr_cents'] // 100}.{value['mrr_cents'] % 100:02d}"
        for key, value in expected["by_plan"].items()
    }
    checks.append(
        {
            "id": "mrr_by_plan",
            "expected": expected_mrr_by_plan,
            "actual": actual_mrr_by_plan,
            "passed": actual_mrr_by_plan == expected_mrr_by_plan
            and mrr_plan_debug["query_executed"],
        }
    )

    trend, trend_debug = ask("最近7天每天新增订阅趋势")
    actual_daily = [
        {"day": row["label"], "count": int(row["values"]["new_subscriptions"])}
        for row in trend["visualization"]["data"]
    ]
    checks.append(
        {
            "id": "seven_day_new_subscription_trend",
            "expected": expected["daily_new"],
            "actual": actual_daily,
            "passed": actual_daily == expected["daily_new"]
            and trend_debug["query_executed"],
        }
    )

    unsupported, unsupported_debug = ask("流失率是多少？")
    checks.append(
        {
            "id": "unsupported_churn",
            "actual": unsupported["status"],
            "passed": unsupported["status"] == "unknown_term"
            and not unsupported_debug["query_executed"],
        }
    )

    ambiguous_income, income_debug = ask("收入是多少？")
    checks.append(
        {
            "id": "ambiguous_income_requires_clarification",
            "actual": ambiguous_income["status"],
            "passed": ambiguous_income["status"] == "clarification_required"
            and not income_debug["query_executed"],
        }
    )

    no_range, no_range_debug = ask("新增订阅数是多少？")
    checks.append(
        {
            "id": "new_subscriptions_requires_time",
            "actual": no_range["status"],
            "passed": no_range["status"] == "clarification_required"
            and not no_range_debug["query_executed"],
        }
    )

    unsupported_dimension, dimension_debug = ask("按地区看活跃订阅数")
    checks.append(
        {
            "id": "unsupported_dimension_rejected",
            "actual": unsupported_dimension["status"],
            "passed": unsupported_dimension["status"] == "unknown_term"
            and not dimension_debug["query_executed"],
        }
    )
    try:
        CreateSessionRequest.model_validate({"dataset_id": "another_dataset"})
        unknown_dataset_rejected = False
    except ValidationError:
        unknown_dataset_rejected = True
    checks.append(
        {"id": "unknown_dataset_rejected", "passed": unknown_dataset_rejected}
    )

    ecommerce_session = create_session(CreateSessionRequest(), request)
    ecommerce_turn = submit_turn(
        ecommerce_session.session_id,
        TurnRequest(question="昨天的销售额和订单数是多少？"),
        request,
    )
    ecommerce_values = {
        metric.metric_id: metric.value for metric in ecommerce_turn.values
    }
    checks.append(
        {
            "id": "ecommerce_uq01_route_regression",
            "expected": {"sales_amount": "257984.80", "order_count": 41},
            "actual": ecommerce_values,
            "passed": ecommerce_session.semantic_catalog_id
            == ACTIVE_CATALOG.catalog.catalog_id
            and ecommerce_values == {"sales_amount": "257984.80", "order_count": 41},
        }
    )

    valid_model_provider = FixedIntentProvider(
        IntentDraft(
            status="ready",
            question_kind="saas01",
            metric_ids=["active_subscriptions"],
        )
    )
    model_result = answer_saas_question(
        "how many current subscriptions",
        "p8-saas-model-harness",
        intent_provider=valid_model_provider,
    )
    checks.append(
        {
            "id": "llm_fallback_uses_only_saas_catalog",
            "actual_catalog_id": (
                valid_model_provider.context.catalog_id
                if valid_model_provider.context
                else None
            ),
            "passed": model_result.status == "completed"
            and valid_model_provider.context is not None
            and valid_model_provider.context.catalog_id
            == ACTIVE_SAAS_CATALOG.catalog.catalog_id
            and model_result.debug_ref is not None,
        }
    )

    invalid_model_provider = FixedIntentProvider(
        IntentDraft(
            status="ready",
            question_kind="saas01",
            metric_ids=["active_subscriptions"],
            filter_ids=["arbitrary_filter"],
        )
    )
    invalid_model_result = answer_saas_question(
        "how many current subscriptions",
        "p8-saas-invalid-model-harness",
        intent_provider=invalid_model_provider,
    )
    checks.append(
        {
            "id": "llm_extra_filter_rejected_without_query",
            "actual_status": invalid_model_result.status,
            "passed": invalid_model_result.status == "unsupported"
            and invalid_model_result.debug_ref is not None,
        }
    )

    return {
        "suite_id": "saas_subscription_p8_v1",
        "adapter": "direct FastAPI route contract (Windows asyncio socketpair workaround)",
        "dataset_id": DATASET_ID,
        "dataset_version": ACTIVE_SAAS_CATALOG.dataset_version,
        "semantic_catalog_id": ACTIVE_SAAS_CATALOG.catalog.catalog_id,
        "semantic_catalog_version": ACTIVE_SAAS_CATALOG.catalog.version,
        "case_count": len(checks),
        "passed_case_count": sum(item["passed"] for item in checks),
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic P8-4 SaaS route acceptance."
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run()
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
