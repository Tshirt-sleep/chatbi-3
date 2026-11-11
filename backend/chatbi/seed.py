"""Seed the local SQLite database from versioned generated CSV datasets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .database import database_url, make_engine
from .models import (
    Category,
    Channel,
    Customer,
    DatasetManifest,
    Order,
    OrderItem,
    Product,
    Refund,
    SaaSAccount,
    SaaSAcquisitionChannel,
    SaaSPlan,
    SaaSSubscription,
)

ROOT = Path(__file__).resolve().parents[2]
GENERATED_ROOT = ROOT / "data" / "generated"
DATASET_IDS = (
    "ecommerce_mock_v1",
    "ecommerce_empty_day_fixture_v1",
    "saas_subscription_mock_v1",
)
TABLE_MODELS = (
    Refund,
    OrderItem,
    Order,
    Product,
    Customer,
    Channel,
    Category,
    SaaSSubscription,
    SaaSAcquisitionChannel,
    SaaSPlan,
    SaaSAccount,
    DatasetManifest,
)


def to_cents(value: str | None) -> int:
    if value in (None, ""):
        return 0
    amount = Decimal(value)
    scaled = amount * 100
    if amount < 0 or scaled != scaled.to_integral_value():
        raise ValueError(
            "Monetary CSV values must be non-negative with at most two decimal places."
        )
    return int(scaled)


def validate_local_database_url(url: str) -> Path:
    parsed_url = make_url(url)
    local_db = (ROOT / "data" / "local" / "chatbi.sqlite").resolve()
    if parsed_url.get_backend_name() != "sqlite":
        raise ValueError(
            "The P5 seeder supports local SQLite only; cloud databases are out of scope here."
        )
    database_path = Path(parsed_url.database or "").resolve()
    if database_path != local_db:
        raise ValueError(f"Seeder is restricted to the local Mock database at {local_db}")
    return local_db


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def stamped(dataset_id: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [{"dataset_id": dataset_id, **row} for row in rows]


def prepare_dataset(session: Session, dataset_id: str) -> None:
    directory = GENERATED_ROOT / dataset_id
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing generated dataset manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared_id = manifest.get("dataset_id")
    if declared_id != dataset_id:
        raise ValueError(f"Manifest dataset_id mismatch for {directory}")

    for filename, metadata in manifest["files"].items():
        file_path = directory / filename
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if digest != metadata["sha256"]:
            raise ValueError(f"Checksum mismatch: {file_path}")

    for model in TABLE_MODELS:
        session.execute(delete(model).where(model.dataset_id == dataset_id))

    session.add(
        DatasetManifest(
            dataset_id=dataset_id,
            version=str(manifest["version"]),
            timezone=str(manifest["timezone"]),
            manifest_json=json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        )
    )

    if dataset_id == "saas_subscription_mock_v1":
        records = {name: read_rows(directory / name) for name in manifest["files"]}
        session.add_all(
            [
                SaaSAccount(
                    dataset_id=dataset_id,
                    account_id=row["account_id"],
                    account_name=row["account_name"],
                    region=row["region"],
                    created_at=row["created_at"],
                )
                for row in records["accounts.csv"]
            ]
        )
        session.add_all(
            [
                SaaSPlan(
                    dataset_id=dataset_id,
                    plan_id=row["plan_id"],
                    plan_name=row["plan_name"],
                    monthly_fee_cents=int(row["monthly_fee_cents"]),
                    status=row["status"],
                )
                for row in records["plans.csv"]
            ]
        )
        session.add_all(
            [
                SaaSAcquisitionChannel(
                    dataset_id=dataset_id,
                    channel_id=row["channel_id"],
                    channel_name=row["channel_name"],
                )
                for row in records["acquisition_channels.csv"]
            ]
        )
        session.flush()
        session.add_all(
            [
                SaaSSubscription(
                    dataset_id=dataset_id,
                    subscription_id=row["subscription_id"],
                    account_id=row["account_id"],
                    plan_id=row["plan_id"],
                    acquisition_channel_id=row["acquisition_channel_id"],
                    started_at=row["started_at"],
                    canceled_at=row["canceled_at"] or None,
                    status=row["status"],
                )
                for row in records["subscriptions.csv"]
            ]
        )
        session.flush()
        return

    categories = stamped(dataset_id, read_rows(directory / "categories.csv"))
    channels = stamped(dataset_id, read_rows(directory / "channels.csv"))
    customers = stamped(dataset_id, read_rows(directory / "customers.csv"))
    products = stamped(dataset_id, read_rows(directory / "products.csv"))
    orders = stamped(dataset_id, read_rows(directory / "orders.csv"))
    items = stamped(dataset_id, read_rows(directory / "order_items.csv"))
    refunds = stamped(dataset_id, read_rows(directory / "refunds.csv"))

    parent_rows = [row for row in categories if row["parent_category_id"] == ""]
    leaf_rows = [row for row in categories if row["parent_category_id"] != ""]
    session.add_all(
        [
            Category(**{**row, "level": int(row["level"]), "parent_category_id": None})
            for row in parent_rows
        ]
    )
    session.flush()
    session.add_all([Category(**{**row, "level": int(row["level"])}) for row in leaf_rows])
    session.flush()
    session.add_all([Channel(**row) for row in channels])
    session.add_all([Customer(**row) for row in customers])
    session.flush()
    session.add_all(
        [
            Product(
                dataset_id=dataset_id,
                product_id=row["product_id"],
                product_name=row["product_name"],
                primary_leaf_category_id=row["primary_leaf_category_id"],
                list_price_cents=to_cents(row["list_price"]),
                is_active=row["is_active"].lower() == "true",
            )
            for row in products
        ]
    )
    session.flush()
    session.add_all(
        [
            Order(
                dataset_id=dataset_id,
                order_id=row["order_id"],
                customer_id=row["customer_id"],
                channel_id=row["channel_id"],
                order_status=row["order_status"],
                created_at=row["created_at"],
                paid_at=row["paid_at"] or None,
                currency=row["currency"],
                gross_amount_cents=to_cents(row["gross_amount"]),
                discount_amount_cents=to_cents(row["discount_amount"]),
                paid_amount_cents=to_cents(row["paid_amount"]),
            )
            for row in orders
        ]
    )
    session.flush()
    session.add_all(
        [
            OrderItem(
                dataset_id=dataset_id,
                order_item_id=row["order_item_id"],
                order_id=row["order_id"],
                product_id=row["product_id"],
                quantity=int(row["quantity"]),
                unit_price_cents=to_cents(row["unit_price"]),
                line_discount_cents=to_cents(row["line_discount"]),
                line_amount_after_discount_cents=to_cents(row["line_amount_after_discount"]),
            )
            for row in items
        ]
    )
    session.flush()
    session.add_all(
        [
            Refund(
                dataset_id=dataset_id,
                refund_id=row["refund_id"],
                order_item_id=row["order_item_id"],
                refunded_amount_cents=to_cents(row["refunded_amount"]),
                requested_at=row["requested_at"],
                completed_at=row["completed_at"] or None,
                refund_status=row["refund_status"],
            )
            for row in refunds
        ]
    )
    session.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load generated Mock datasets into local SQLite.")
    parser.add_argument(
        "--reset", action="store_true", help="Replace the local Mock dataset snapshots."
    )
    args = parser.parse_args()

    url = database_url()
    try:
        database_path = validate_local_database_url(url)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = make_engine(url)
    try:
        with Session(engine) as session, session.begin():
            if not args.reset and any(
                session.get(DatasetManifest, dataset_id) for dataset_id in DATASET_IDS
            ):
                raise SystemExit(
                    "Datasets already exist; pass --reset to replace the local Mock snapshots."
                )
            for dataset_id in DATASET_IDS:
                prepare_dataset(session, dataset_id)
    except Exception:
        engine.dispose()
        raise
    engine.dispose()
    print(f"Loaded {', '.join(DATASET_IDS)} into {database_path}")


if __name__ == "__main__":
    main()
