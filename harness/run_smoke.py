"""P5 data-to-database smoke harness; query API adapter will be added in P6."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from backend.chatbi.database import make_engine

ROOT = Path(__file__).resolve().parents[1]
DATASETS = (
    "ecommerce_mock_v1",
    "ecommerce_empty_day_fixture_v1",
    "saas_subscription_mock_v1",
)
DB_TABLE_BY_FILE_STEM = {
    "accounts": "saas_accounts",
    "plans": "saas_plans",
    "subscriptions": "saas_subscriptions",
    "acquisition_channels": "saas_acquisition_channels",
}


def foreign_key_violation_count(connection) -> int:  # type: ignore[no-untyped-def]
    """Count rows violating declared FKs using SQL portable across SQLite/PostgreSQL."""
    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote
    violations = 0
    for table_name in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table_name):
            source_columns = foreign_key.get("constrained_columns") or []
            target_table = foreign_key.get("referred_table")
            target_columns = foreign_key.get("referred_columns") or []
            if (
                not source_columns
                or not target_table
                or len(source_columns) != len(target_columns)
            ):
                continue
            source_non_null = " AND ".join(
                f"src.{quote(column)} IS NOT NULL" for column in source_columns
            )
            join_predicates = " AND ".join(
                f"src.{quote(source)} = ref.{quote(target)}"
                for source, target in zip(source_columns, target_columns, strict=True)
            )
            statement = text(
                f"SELECT COUNT(*) FROM {quote(table_name)} AS src "
                f"WHERE {source_non_null} AND NOT EXISTS ("
                f"SELECT 1 FROM {quote(target_table)} AS ref WHERE {join_predicates})"
            )
            violations += int(connection.execute(statement).scalar_one())
    return violations


def verify_generated_files(dataset_id: str) -> dict[str, int]:
    directory = ROOT / "data" / "generated" / dataset_id
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != dataset_id:
        raise ValueError(f"manifest dataset_id mismatch: {dataset_id}")
    actual_counts: dict[str, int] = {}
    for filename, expected in manifest["files"].items():
        path = directory / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            actual_count = sum(1 for _ in csv.DictReader(source))
        if actual_count != expected["rows"]:
            raise ValueError(f"Row count mismatch: {path}")
        actual_counts[path.stem] = actual_count
    return actual_counts


def expected_uq01() -> tuple[int, int]:
    markdown = (ROOT / "docs" / "acceptance" / "GOLDEN_RESULTS.md").read_text(
        encoding="utf-8"
    )
    section = markdown.split("## UQ-01 昨日汇总", maxsplit=1)[1].split(
        "## ", maxsplit=1
    )[0]
    match = re.search(
        r"\|\s*2026-07-31\s*\|\s*([0-9]+(?:\.[0-9]{2})?)\s*\|\s*(\d+)\s*\|", section
    )
    if match is None:
        raise ValueError("Could not parse UQ-01 expected result from GOLDEN_RESULTS.md")
    cents = int(match.group(1).replace(".", ""))
    return cents, int(match.group(2))


def load_golden_question_ids() -> list[str]:
    markdown = (ROOT / "docs" / "acceptance" / "GOLDEN_QUESTIONS.md").read_text(
        encoding="utf-8"
    )
    question_ids = re.findall(r"^\|\s*(UQ-\d{2})\s*\|", markdown, flags=re.MULTILINE)
    return sorted(set(question_ids))


def run_smoke() -> dict[str, Any]:
    generated_counts = {
        dataset_id: verify_generated_files(dataset_id) for dataset_id in DATASETS
    }
    engine = make_engine()
    checks: list[dict[str, Any]] = []
    try:
        with engine.connect() as connection:
            manifest_versions: dict[str, str] = {}
            for dataset_id in DATASETS:
                row = connection.execute(
                    text(
                        "SELECT version, timezone, manifest_json FROM dataset_manifests "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"dataset_id": dataset_id},
                ).one_or_none()
                if row is None:
                    raise ValueError(f"Dataset is not seeded: {dataset_id}")
                manifest_versions[dataset_id] = str(row.version)
                expected_manifest = json.loads(
                    (
                        ROOT / "data" / "generated" / dataset_id / "manifest.json"
                    ).read_text(encoding="utf-8")
                )
                stored_manifest = json.loads(str(row.manifest_json))
                checks.append(
                    {
                        "id": f"manifest:{dataset_id}:content",
                        "passed": stored_manifest == expected_manifest
                        and str(row.version) == str(expected_manifest["version"])
                        and str(row.timezone) == str(expected_manifest["timezone"]),
                    }
                )
                for table_name, expected_count in generated_counts[dataset_id].items():
                    db_table = DB_TABLE_BY_FILE_STEM.get(table_name, table_name)
                    actual_count = connection.execute(
                        text(
                            f"SELECT COUNT(*) FROM {db_table} WHERE dataset_id = :dataset_id"
                        ),
                        {"dataset_id": dataset_id},
                    ).scalar_one()
                    checks.append(
                        {
                            "id": f"db_rows:{dataset_id}:{table_name}",
                            "passed": actual_count == expected_count,
                            "expected": expected_count,
                            "actual": actual_count,
                        }
                    )

            expected_sales_cents, expected_order_count = expected_uq01()
            actual_sales_cents, actual_order_count = connection.execute(
                text("""
                    SELECT COALESCE(SUM(paid_amount_cents), 0), COUNT(DISTINCT order_id)
                    FROM orders
                    WHERE dataset_id = :dataset_id
                      AND order_status IN ('paid', 'completed')
                      AND paid_at IS NOT NULL
                      AND paid_at >= :start_at
                      AND paid_at < :end_at
                """),
                {
                    "dataset_id": "ecommerce_mock_v1",
                    "start_at": "2026-07-31T00:00:00+08:00",
                    "end_at": "2026-08-01T00:00:00+08:00",
                },
            ).one()
            checks.append(
                {
                    "id": "UQ-01:2026-07-31",
                    "passed": (actual_sales_cents, actual_order_count)
                    == (expected_sales_cents, expected_order_count),
                    "expected_sales_cents": expected_sales_cents,
                    "actual_sales_cents": actual_sales_cents,
                    "expected_order_count": expected_order_count,
                    "actual_order_count": actual_order_count,
                }
            )

            fixture_manifest = json.loads(
                (
                    ROOT
                    / "data"
                    / "generated"
                    / "ecommerce_empty_day_fixture_v1"
                    / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            expected_trend = fixture_manifest["expected_three_day_trend"]
            actual_trend: dict[str, dict[str, int]] = {}
            for day_text in expected_trend:
                day = date.fromisoformat(day_text)
                next_day = day + timedelta(days=1)
                sales_cents, count = connection.execute(
                    text("""
                        SELECT COALESCE(SUM(paid_amount_cents), 0), COUNT(DISTINCT order_id)
                        FROM orders
                        WHERE dataset_id = :dataset_id
                          AND order_status IN ('paid', 'completed')
                          AND paid_at IS NOT NULL
                          AND paid_at >= :start_at
                          AND paid_at < :end_at
                    """),
                    {
                        "dataset_id": "ecommerce_empty_day_fixture_v1",
                        "start_at": f"{day.isoformat()}T00:00:00+08:00",
                        "end_at": f"{next_day.isoformat()}T00:00:00+08:00",
                    },
                ).one()
                actual_trend[day_text] = {
                    "valid_order_count": int(count),
                    "sales_cents": int(sales_cents),
                }
            fixture_ok = all(
                actual_trend[day_text]["valid_order_count"]
                == expected["valid_order_count"]
                and actual_trend[day_text]["sales_cents"]
                == int(expected["sales_amount"].replace(".", ""))
                for day_text, expected in expected_trend.items()
            )
            checks.append(
                {
                    "id": "fixture:three_day_zero_fill",
                    "passed": fixture_ok,
                    "actual": actual_trend,
                }
            )

            violations = foreign_key_violation_count(connection)
            checks.append(
                {
                    "id": "db:foreign_key_check",
                    "passed": violations == 0,
                    "violations": violations,
                }
            )
    finally:
        engine.dispose()

    return {
        "suite_id": "p5_dataset_and_seed_smoke_v1",
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "adapter": "sqlalchemy_database",
        "golden_question_ids": load_golden_question_ids(),
        "executed_golden_question_ids": ["UQ-01"],
        "deferred_to_query_api": [
            "UQ-02",
            "UQ-03",
            "UQ-04",
            "UQ-05",
            "UQ-06",
            "UQ-07",
            "UQ-08",
            "UQ-09",
            "UQ-10",
        ],
        "metrics": {
            "check_count": len(checks),
            "passed_check_count": sum(1 for item in checks if item["passed"]),
            "check_accuracy": sum(1 for item in checks if item["passed"]) / len(checks)
            if checks
            else 0,
        },
        "datasets": {
            dataset_id: {
                "version": manifest_versions[dataset_id],
                "row_counts": generated_counts[dataset_id],
            }
            for dataset_id in DATASETS
        },
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic P5 data/seed smoke suite."
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument(
        "--compare", type=Path, help="Optional prior report to compare against"
    )
    args = parser.parse_args()
    try:
        report = run_smoke()
    except FileNotFoundError:
        report = {
            "suite_id": "p5_dataset_and_seed_smoke_v1",
            "status": "failed",
            "error_category": "DATASET_FILE_MISSING",
        }
    except SQLAlchemyError:
        report = {
            "suite_id": "p5_dataset_and_seed_smoke_v1",
            "status": "failed",
            "error_category": "DATA_SOURCE_ERROR",
        }
    except (KeyError, ValueError):
        report = {
            "suite_id": "p5_dataset_and_seed_smoke_v1",
            "status": "failed",
            "error_category": "DATASET_OR_GOLDEN_INVALID",
        }
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.compare:
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        print(
            "report_comparison=identical"
            if previous == report
            else "report_comparison=changed"
        )
        if previous != report:
            return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
