"""HTTP-adapter regression harness for the deterministic MVP golden questions."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CHATBI_DEBUG_ENABLED", "true")

from backend.chatbi.main import app
from backend.chatbi.query_service import CATALOG_ID, CATALOG_VERSION

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "harness" / "golden_cases.json"
RESULTS_PATH = ROOT / "docs" / "acceptance" / "GOLDEN_RESULTS.md"


def _section(markdown: str, title: str) -> str:
    start = markdown.index(f"## {title}")
    following = markdown.find("\n## ", start + 3)
    return markdown[start:] if following < 0 else markdown[start:following]


def _table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        if (
            not line.startswith("|")
            or set(line.replace("|", "").replace("-", "").replace(":", "").strip())
            == set()
        ):
            continue
        values = [part.strip() for part in line.strip().strip("|").split("|")]
        if values and not all(set(value) <= {"-", ":"} for value in values):
            rows.append(values)
    return rows


def load_expectations() -> dict[str, Any]:
    markdown = RESULTS_PATH.read_text(encoding="utf-8")
    uq01 = _table_rows(_section(markdown, "UQ-01 昨日汇总"))[1]
    uq02_rows = _table_rows(_section(markdown, "UQ-02 最近 7 天每日销售额"))[1:]
    uq03 = _table_rows(_section(markdown, "UQ-03 7 月与 6 月销售额比较"))[1]
    uq04_rows = _table_rows(_section(markdown, "UQ-04 最近 30 天商品销售额 Top 10"))[1:]
    uq05_rows = _table_rows(_section(markdown, "UQ-05 最近 30 天叶子类目汇总"))[1:]
    uq06_rows = _table_rows(_section(markdown, "UQ-06 最近 30 天渠道客单价"))[1:]
    uq08_rows = _table_rows(_section(markdown, "UQ-08 本周与上周同期类目销售额"))[1:]
    uq09_section = _section(markdown, "UQ-09 相邻 7 天期间的数值分解")
    uq09_rows = _table_rows(uq09_section)[1:]
    paragraph = re.search(
        r"销售额变化：([^；]+)；订单数变化：([^；]+)；订单数变化贡献：([^；]+)；客单价变化贡献：([^。]+)",
        uq09_section,
    )
    if paragraph is None:
        raise ValueError("Unable to parse UQ-09 decomposition golden result")
    current, previous = uq09_rows[0], uq09_rows[1]
    return {
        "UQ-01": {"values": {"sales_amount": uq01[1], "order_count": int(uq01[2])}},
        "UQ-02": {
            "rows": [
                {"key": row[0], "label": row[0], "values": {"sales_amount": row[1]}}
                for row in uq02_rows
            ]
        },
        "UQ-03": {
            "values": {
                "sales_amount_current": uq03[0],
                "sales_amount_previous": uq03[1],
                "sales_amount_delta": uq03[2],
                "sales_amount_change_rate": uq03[3],
            }
        },
        "UQ-04": {
            "rows": [
                {
                    "key": row[1],
                    "label": row[2],
                    "values": {"product_id": row[1], "sales_amount": row[3]},
                }
                for row in uq04_rows
            ]
        },
        "UQ-05": {
            "rows": [
                {
                    "key": row[0],
                    "label": row[0],
                    "values": {"order_count": int(row[1]), "sales_amount": row[2]},
                }
                for row in uq05_rows
            ]
        },
        "UQ-06": {
            "rows": [
                {
                    "key": row[0],
                    "label": row[0],
                    "values": {
                        "order_count": int(row[1]),
                        "sales_amount": row[2],
                        "average_order_value": row[3],
                    },
                }
                for row in uq06_rows
            ]
        },
        "UQ-08": {
            "rows": [
                {
                    "key": row[0],
                    "label": row[0],
                    "values": {
                        "current_sales": row[1],
                        "previous_sales": row[2],
                        "change": row[3],
                    },
                }
                for row in uq08_rows
            ]
        },
        "UQ-09": {
            "values": {
                "order_count_previous": int(previous[1]),
                "order_count_current": int(current[1]),
                "average_order_value_previous": previous[3],
                "average_order_value_current": current[3],
                "sales_amount_delta": paragraph.group(1),
                "order_count_contribution": paragraph.group(3),
                "aov_contribution": paragraph.group(4),
            }
        },
    }


async def _query_debug(client: AsyncClient, response: dict[str, Any]) -> dict[str, Any]:
    if "debug" in response:
        raise ValueError("Ordinary turn response leaked debug data")
    debug_response = await client.get(f"/api/v1/debug/queries/{response['debug_ref']}")
    debug_response.raise_for_status()
    return debug_response.json()


async def evaluate_case(
    case: dict[str, Any], expected: dict[str, Any]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-Mock-User": "analyst"},
    ) as client:
        session_response = await client.post(
            "/api/v1/sessions", json={"dataset_id": "ecommerce_mock_v1"}
        )
        session_response.raise_for_status()
        session_id = session_response.json()["session_id"]
        first_response = await client.post(
            f"/api/v1/sessions/{session_id}/turns", json={"question": case["question"]}
        )
        first_response.raise_for_status()
        result = first_response.json()
        first_debug = await _query_debug(client, result)
        if "clarification" in case:
            checks.append(
                {
                    "id": f"{case['id']}:clarification_status",
                    "passed": result["status"] == "clarification_required",
                }
            )
            checks.append(
                {
                    "id": f"{case['id']}:clarification_no_query",
                    "passed": first_debug["query_executed"] is False,
                }
            )
            followup_response = await client.post(
                f"/api/v1/sessions/{session_id}/turns",
                json={
                    "question": case["clarification"],
                    "clarifies_turn_id": result["clarification_id"],
                },
            )
            followup_response.raise_for_status()
            result = followup_response.json()
        debug = await _query_debug(client, result)
        expected_query = case["expected_query_executed"]
        checks.extend(
            [
                {
                    "id": f"{case['id']}:status",
                    "expected": case["expected_status"],
                    "actual": result["status"],
                    "passed": result["status"] == case["expected_status"],
                },
                {
                    "id": f"{case['id']}:query_execution",
                    "expected": expected_query,
                    "actual": debug["query_executed"],
                    "passed": debug["query_executed"] is expected_query,
                },
                {
                    "id": f"{case['id']}:visualization",
                    "expected": case["visualization"],
                    "actual": result["visualization"]["type"],
                    "passed": result["visualization"]["type"] == case["visualization"],
                },
            ]
        )
        if case["id"] in expected:
            if "values" in expected[case["id"]]:
                actual_values = {
                    item["metric_id"]: item["value"] for item in result["values"]
                }
                target = expected[case["id"]]["values"]
                checks.append(
                    {
                        "id": f"{case['id']}:exact_values",
                        "expected": target,
                        "actual": actual_values,
                        "passed": actual_values == target,
                    }
                )
            if "rows" in expected[case["id"]]:
                actual_rows = result["visualization"]["data"]
                target_rows = expected[case["id"]]["rows"]
                actual_projection = [
                    (row["label"], row["values"]) for row in actual_rows
                ]
                target_projection = [
                    (row["label"], row["values"]) for row in target_rows
                ]
                checks.append(
                    {
                        "id": f"{case['id']}:exact_rows",
                        "expected_count": len(target_rows),
                        "actual_count": len(actual_rows),
                        "passed": actual_projection == target_projection,
                    }
                )
        if result["status"] == "completed":
            evidence = result["evidence"]
            evidence_ok = (
                evidence["mock_data"] is True
                and bool(evidence["dataset_version"])
                and evidence["semantic_catalog_id"] == CATALOG_ID
                and evidence["semantic_catalog_version"] == CATALOG_VERSION
            )
            checks.append(
                {
                    "id": f"{case['id']}:mock_evidence",
                    "expected_catalog_id": CATALOG_ID,
                    "expected_catalog_version": CATALOG_VERSION,
                    "actual_catalog_id": evidence["semantic_catalog_id"],
                    "actual_catalog_version": evidence["semantic_catalog_version"],
                    "passed": evidence_ok,
                }
            )
    return checks


async def run_suite() -> dict[str, Any]:
    case_data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    expected = load_expectations()
    all_checks: list[dict[str, Any]] = []
    for case in case_data["cases"]:
        all_checks.extend(await evaluate_case(case, expected))
    passed = sum(check["passed"] for check in all_checks)
    return {
        "suite_id": case_data["suite_id"],
        "adapter": "FastAPI ASGI HTTP",
        "dataset_id": case_data["dataset_id"],
        "semantic_catalog_id": CATALOG_ID,
        "semantic_catalog_version": CATALOG_VERSION,
        "case_count": len(case_data["cases"]),
        "check_count": len(all_checks),
        "passed_check_count": passed,
        "check_accuracy": passed / len(all_checks) if all_checks else 1.0,
        "status": "passed" if passed == len(all_checks) else "failed",
        "checks": all_checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_suite())
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.compare:
        prior = json.loads(args.compare.read_text(encoding="utf-8"))
        print(
            "report_comparison=identical"
            if prior == report
            else "report_comparison=changed"
        )
        if prior != report:
            return 1
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
