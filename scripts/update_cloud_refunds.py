"""Safely add the v1.1.0 refund snapshot to the existing ChatBI Mock database."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.chatbi.database import make_engine
from backend.chatbi.models import (
    Category,
    Channel,
    Customer,
    DatasetManifest,
    Order,
    OrderItem,
    Product,
    Refund,
)
from backend.chatbi.seed import to_cents

DATASET_ID = "ecommerce_mock_v1"
OLD_VERSION = "1.0.0"
EXPECTED_VERSION = "1.1.0"
REFUND_CSV = ROOT / "data" / "generated" / DATASET_ID / "refunds.csv"
MANIFEST_PATH = ROOT / "data" / "generated" / DATASET_ID / "manifest.json"
CORE_MODELS = {
    "categories": Category,
    "channels": Channel,
    "customers": Customer,
    "products": Product,
    "orders": Order,
    "order_items": OrderItem,
}


class SafeUpdateError(Exception):
    """A validation error safe to display without connection details."""


def _load_source() -> tuple[dict[str, Any], list[dict[str, str]]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if (
        manifest.get("dataset_id") != DATASET_ID
        or manifest.get("version") != EXPECTED_VERSION
    ):
        raise SafeUpdateError(
            "Local ecommerce Mock manifest is not the expected v1.1.0."
        )
    metadata = manifest.get("files", {}).get("refunds.csv", {})
    digest = hashlib.sha256(REFUND_CSV.read_bytes()).hexdigest()
    if digest != metadata.get("sha256"):
        raise SafeUpdateError("Local refunds.csv checksum does not match its manifest.")
    with REFUND_CSV.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != [
            "refund_id",
            "order_item_id",
            "refunded_amount",
            "requested_at",
            "completed_at",
            "refund_status",
        ]:
            raise SafeUpdateError(
                "Local refunds.csv columns do not match the expected schema."
            )
        rows = list(reader)
    if len(rows) != metadata.get("rows"):
        raise SafeUpdateError("Local refund row count does not match its manifest.")
    if len({row["refund_id"] for row in rows}) != len(rows):
        raise SafeUpdateError("Local refund IDs are not unique.")
    allowed_statuses = {"completed", "requested", "rejected", "cancelled"}
    if any(row["refund_status"] not in allowed_statuses for row in rows):
        raise SafeUpdateError("Local refund data contains an unexpected status.")
    if any(to_cents(row["refunded_amount"]) <= 0 for row in rows):
        raise SafeUpdateError("Local refund data contains a non-positive amount.")
    return manifest, rows


def _validate_connection(url: str, expected_project_ref: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise SafeUpdateError("Target must be a PostgreSQL Supabase database.")
    if parsed.database != "postgres" or parsed.port != 5432:
        raise SafeUpdateError(
            "Use the Supabase Session Pooler connection on port 5432."
        )
    username = parsed.username or ""
    if not username.startswith("postgres."):
        raise SafeUpdateError(
            "Use the owner Session Pooler account for the selected project."
        )
    if username.split(".", maxsplit=1)[1] != expected_project_ref:
        raise SafeUpdateError(
            "Owner URL project reference does not match --expected-project-ref."
        )
    host = (parsed.host or "").lower()
    if not (
        host.endswith(".pooler.supabase.com")
        or host == f"db.{expected_project_ref}.supabase.co"
    ):
        raise SafeUpdateError(
            "Target host is not the Supabase project identified by the owner URL."
        )
    if parsed.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise SafeUpdateError(
            "Supabase connection URL must retain its TLS sslmode parameter."
        )


def _expected_old_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    expected = deepcopy(manifest)
    expected["version"] = OLD_VERSION
    expected["row_counts"].pop("refunds", None)
    expected["files"].pop("refunds.csv", None)
    return expected


def _old_snapshot_mismatches(
    current_json: dict[str, Any], manifest: dict[str, Any]
) -> list[str]:
    """Return safe field labels for mismatched stable snapshot metadata."""
    expected = _expected_old_manifest(manifest)
    stable_keys = (
        "dataset_id",
        "version",
        "as_of_date",
        "timezone",
        "date_window",
        "row_counts",
    )
    mismatches = []
    for key in stable_keys:
        actual = current_json.get(key)
        wanted = expected.get(key)
        if key == "row_counts" and isinstance(actual, dict):
            actual_without_refunds = dict(actual)
            legacy_refunds = actual_without_refunds.pop("refunds", 0)
            if legacy_refunds != 0:
                mismatches.append(key)
                continue
            actual = actual_without_refunds
        if actual != wanted:
            mismatches.append(key)

    refund_file = current_json.get("files", {}).get("refunds.csv")
    if refund_file and refund_file.get("rows") != 0:
        mismatches.append("files.refunds.csv")
    return mismatches


def _count(session: Session, model: type[Any]) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.dataset_id == DATASET_ID)
        )
        or 0
    )


def _preflight(
    session: Session, manifest: dict[str, Any], rows: list[dict[str, str]]
) -> tuple[DatasetManifest, bool]:
    current = session.scalar(
        select(DatasetManifest)
        .where(DatasetManifest.dataset_id == DATASET_ID)
        .with_for_update()
    )
    if current is None:
        raise SafeUpdateError(
            "Target has no ecommerce Mock manifest; empty/new databases are refused."
        )
    try:
        current_json = json.loads(current.manifest_json)
    except json.JSONDecodeError as error:
        raise SafeUpdateError("Target ecommerce manifest is not valid JSON.") from error
    if current.version != current_json.get("version"):
        raise SafeUpdateError("Target manifest row and embedded version disagree.")

    refund_count = _count(session, Refund)
    if current.version == EXPECTED_VERSION:
        if current_json != manifest or refund_count != len(rows):
            raise SafeUpdateError(
                "Target claims v1.1.0 but does not match the verified refund snapshot."
            )
        return current, True
    metadata_mismatches = _old_snapshot_mismatches(current_json, manifest)
    if current.version != OLD_VERSION or metadata_mismatches:
        raise SafeUpdateError(
            "Target is not the expected ecommerce Mock v1.0.0 snapshot; "
            f"mismatched metadata fields: {', '.join(metadata_mismatches) or 'version'}."
        )
    if refund_count != 0:
        raise SafeUpdateError(
            "Target already contains refund rows; no rows or manifest were changed."
        )

    expected_counts = manifest["row_counts"]
    for table_name, model in CORE_MODELS.items():
        if _count(session, model) != expected_counts[table_name]:
            raise SafeUpdateError(
                f"Target {table_name} row count differs from the v1.0.0 snapshot."
            )
    return current, False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only preflight by default; atomically append only the v1.1.0 refunds."
    )
    parser.add_argument("--expected-project-ref", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Apply after the preflight checks pass."
    )
    args = parser.parse_args()

    url = os.getenv("CHATBI_CLOUD_UPDATE_DATABASE_URL", "").strip()
    if not url:
        parser.error(
            "Set CHATBI_CLOUD_UPDATE_DATABASE_URL in this shell; the URL is never printed."
        )

    try:
        _validate_connection(url, args.expected_project_ref)
        manifest, rows = _load_source()
    except (SafeUpdateError, OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Preflight refused: {error}", file=sys.stderr)
        return 2

    engine = make_engine(url)
    try:
        with Session(engine) as session, session.begin():
            current, already_current = _preflight(session, manifest, rows)
            if already_current:
                print(
                    f"Target {args.expected_project_ref} already matches {EXPECTED_VERSION}; "
                    f"refund rows={len(rows)}. No changes made."
                )
                return 0
            if not args.apply:
                print(
                    f"Preflight passed for project {args.expected_project_ref}: "
                    f"{current.version} -> {EXPECTED_VERSION}; existing ecommerce rows match; "
                    f"refund rows to append={len(rows)}. Dry run only; no changes made."
                )
                return 0

            session.add_all(
                [
                    Refund(
                        dataset_id=DATASET_ID,
                        refund_id=row["refund_id"],
                        order_item_id=row["order_item_id"],
                        refunded_amount_cents=to_cents(row["refunded_amount"]),
                        requested_at=row["requested_at"],
                        completed_at=row["completed_at"] or None,
                        refund_status=row["refund_status"],
                    )
                    for row in rows
                ]
            )
            session.flush()
            status_counts = Counter(
                dict(
                    session.execute(
                        select(Refund.refund_status, func.count())
                        .where(Refund.dataset_id == DATASET_ID)
                        .group_by(Refund.refund_status)
                    ).all()
                )
            )
            expected_status_counts = Counter(row["refund_status"] for row in rows)
            if (
                _count(session, Refund) != len(rows)
                or status_counts != expected_status_counts
            ):
                raise SafeUpdateError(
                    "Inserted refund row counts do not match the verified source."
                )

            current.version = EXPECTED_VERSION
            current.timezone = str(manifest["timezone"])
            current.manifest_json = json.dumps(
                manifest, ensure_ascii=False, sort_keys=True
            )

        print(
            f"Update committed for project {args.expected_project_ref}: "
            f"appended {len(rows)} refund events and set ecommerce Mock version to {EXPECTED_VERSION}. "
            "No existing orders, items, products, or other datasets were replaced."
        )
        return 0
    except SafeUpdateError as error:
        print(f"Update rolled back: {error}", file=sys.stderr)
        return 2
    except SQLAlchemyError as error:
        sqlstate = getattr(getattr(error, "orig", error), "sqlstate", None)
        suffix = f" (SQLSTATE {sqlstate})" if sqlstate else ""
        print(
            f"Database update rolled back due to a database error{suffix}; no URL or password shown.",
            file=sys.stderr,
        )
        return 3
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
