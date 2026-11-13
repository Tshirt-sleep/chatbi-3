#!/usr/bin/env python3
"""Generate the versioned synthetic e-commerce dataset and P3 golden results.

This is a standalone data-preparation utility. It does not select the ChatBI
application runtime or database.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = "20260801"
DATA_START = date(2025, 8, 1)
AS_OF = date(2026, 8, 1)
DATA_END_EXCLUSIVE = AS_OF
DATASET_ID = "ecommerce_mock_v1"
EMPTY_FIXTURE_ID = "ecommerce_empty_day_fixture_v1"
UTC_PLUS_8 = timezone(timedelta(hours=8))

CHANNELS = [
    ("chn_01", "web", "自营网页"),
    ("chn_02", "app", "自营App"),
    ("chn_03", "mini_program", "微信小程序"),
    ("chn_04", "marketplace_a", "虚构商城A"),
    ("chn_05", "marketplace_b", "虚构商城B"),
]

CATEGORY_TREE = [
    (
        "家居生活",
        [
            "家纺床品",
            "厨具餐饮",
            "收纳整理",
            "清洁用品",
            "家具家装",
            "灯具照明",
            "卫浴用品",
            "园艺户外",
            "宠物用品",
        ],
    ),
    (
        "服饰鞋包",
        [
            "女装",
            "男装",
            "童装",
            "内衣",
            "鞋靴",
            "箱包",
            "运动服饰",
            "户外服饰",
            "服饰配件",
        ],
    ),
    (
        "数码家电",
        [
            "手机通讯",
            "电脑办公",
            "数码配件",
            "摄影摄像",
            "影音娱乐",
            "智能设备",
            "大家电",
            "小家电",
            "游戏设备",
        ],
    ),
]

TABLE_FIELDS = {
    "categories": ["category_id", "category_name", "parent_category_id", "level"],
    "channels": ["channel_id", "channel_code", "channel_name"],
    "customers": ["customer_id", "created_at", "region_code"],
    "products": [
        "product_id",
        "product_name",
        "primary_leaf_category_id",
        "list_price",
        "is_active",
    ],
    "orders": [
        "order_id",
        "customer_id",
        "channel_id",
        "order_status",
        "created_at",
        "paid_at",
        "currency",
        "gross_amount",
        "discount_amount",
        "paid_amount",
    ],
    "order_items": [
        "order_item_id",
        "order_id",
        "product_id",
        "quantity",
        "unit_price",
        "line_discount",
        "line_amount_after_discount",
    ],
    "refunds": [
        "refund_id",
        "order_item_id",
        "refunded_amount",
        "requested_at",
        "completed_at",
        "refund_status",
    ],
}


def stable_int(*parts: object) -> int:
    """SHA-256 over UTF-8, first 8 bytes interpreted as unsigned big-endian."""
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    absolute_cents = abs(cents)
    return f"{sign}{absolute_cents // 100}.{absolute_cents % 100:02d}"


def cents(value: object) -> int:
    whole, fraction = str(value).split(".")
    return int(whole) * 100 + int(fraction[:2].ljust(2, "0"))


def timestamp(value: datetime | None) -> str:
    return (
        ""
        if value is None
        else value.replace(tzinfo=UTC_PLUS_8).isoformat(timespec="seconds")
    )


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def file_manifest(directory: Path, row_counts: dict[str, int]) -> dict[str, object]:
    files: dict[str, object] = {}
    for table in TABLE_FIELDS:
        path = directory / f"{table}.csv"
        files[path.name] = {
            "rows": row_counts[table],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return files


def build_dimensions() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    categories: list[dict[str, object]] = []
    leaves: list[dict[str, object]] = []
    for root_index, (root_name, leaf_names) in enumerate(CATEGORY_TREE, start=1):
        parent_id = f"cat_{root_index:03d}"
        categories.append(
            {
                "category_id": parent_id,
                "category_name": root_name,
                "parent_category_id": "",
                "level": 1,
            }
        )
        first_leaf_number = 4 + (root_index - 1) * 9
        for leaf_offset, leaf_name in enumerate(leaf_names):
            row = {
                "category_id": f"cat_{first_leaf_number + leaf_offset:03d}",
                "category_name": leaf_name,
                "parent_category_id": parent_id,
                "level": 2,
            }
            categories.append(row)
            leaves.append(row)

    channels = [
        {"channel_id": channel_id, "channel_code": code, "channel_name": name}
        for channel_id, code, name in CHANNELS
    ]

    customers: list[dict[str, object]] = []
    customer_window_days = (DATA_START - date(2025, 2, 1)).days
    for index in range(1, 8_001):
        day = date(2025, 2, 1) + timedelta(
            days=stable_int(SEED, "customers", index, "created_day")
            % customer_window_days
        )
        second = stable_int(SEED, "customers", index, "created_second") % 86_400
        customers.append(
            {
                "customer_id": f"cus_{index:06d}",
                "created_at": timestamp(
                    datetime.combine(day, time()) + timedelta(seconds=second)
                ),
                "region_code": "R-{:02d}".format(
                    1 + stable_int(SEED, "customers", index, "region") % 8
                ),
            }
        )

    products: list[dict[str, object]] = []
    products_by_leaf: dict[str, list[dict[str, object]]] = defaultdict(list)
    for index in range(1, 501):
        leaf = leaves[(index - 1) % len(leaves)]
        leaf_id = str(leaf["category_id"])
        leaf_name = str(leaf["category_name"])
        price_cents = 500 + stable_int(SEED, "products", index, "list_price") % 199_501
        row = {
            "product_id": f"prd_{index:06d}",
            "product_name": f"{leaf_name}-{index:03d}",
            "primary_leaf_category_id": leaf_id,
            "list_price": money(price_cents),
            "is_active": str(
                stable_int(SEED, "products", index, "is_active") % 10 != 0
            ).lower(),
            "_price_cents": price_cents,
        }
        products.append(row)
        products_by_leaf[leaf_id].append(row)
    return categories, channels, customers, products, leaves


def generate_main_dataset(output_dir: Path) -> tuple[dict[str, int], dict[str, object]]:
    categories, channels, customers, products, leaves = build_dimensions()
    channel_ids = [str(row["channel_id"]) for row in channels]
    customer_ids = [str(row["customer_id"]) for row in customers]
    product_ids_by_leaf: dict[str, list[dict[str, object]]] = defaultdict(list)
    for product in products:
        product_ids_by_leaf[str(product["primary_leaf_category_id"])].append(product)

    valid_dates = [
        DATA_START + timedelta(days=offset)
        for offset in range((DATA_END_EXCLUSIVE - DATA_START).days)
    ]
    orders: list[dict[str, object]] = []
    order_items: list[dict[str, object]] = []
    line_by_category: dict[str, int] = defaultdict(int)
    sales_by_date: dict[date, int] = defaultdict(int)
    order_count_by_date: dict[date, int] = defaultdict(int)
    sales_by_product: dict[str, int] = defaultdict(int)
    sales_by_category: dict[str, int] = defaultdict(int)
    category_order_ids: dict[str, set[str]] = defaultdict(set)
    sales_by_channel: dict[str, int] = defaultdict(int)
    channel_order_ids: dict[str, set[str]] = defaultdict(set)
    orders_by_id: dict[str, dict[str, object]] = {}
    product_by_id = {str(row["product_id"]): row for row in products}
    item_sequence = 0

    for order_index in range(1, 20_001):
        order_id = f"ord_{order_index:06d}"
        if order_index <= 17_000:
            status = "paid"
        elif order_index <= 18_000:
            status = "completed"
        elif order_index <= 19_000:
            status = "created"
        elif order_index <= 19_600:
            status = "cancelled"
        else:
            status = "closed"
        is_valid = status in ("paid", "completed")

        if is_valid and order_index <= len(valid_dates):
            order_date = valid_dates[order_index - 1]
        else:
            order_date = valid_dates[
                stable_int(SEED, "order", order_index, "date") % len(valid_dates)
            ]

        channel = channel_ids[(order_index - 1) % len(channel_ids)]
        customer_id = customer_ids[
            stable_int(SEED, "order", order_index, "customer") % len(customer_ids)
        ]
        second = stable_int(SEED, "order", order_index, "event_second") % 86_400
        event_time = datetime.combine(order_date, time()) + timedelta(seconds=second)

        if is_valid:
            paid_at = event_time
            lead_seconds = 3_600 + stable_int(
                SEED, "order", order_index, "created_lead"
            ) % (47 * 3_600 + 1)
            created_at = paid_at - timedelta(seconds=lead_seconds)
        else:
            paid_at = None
            created_at = event_time

        cross_category = is_valid and order_index <= 3_600
        minimum_items = 2 if cross_category else 1
        item_count = minimum_items + stable_int(
            SEED, "order", order_index, "item_count"
        ) % (5 - minimum_items)
        primary_leaf_index = stable_int(SEED, "order", order_index, "category") % len(
            leaves
        )
        gross_cents = 0
        discount_cents = 0
        order_line_rows: list[dict[str, object]] = []
        used_leaf_indices: list[int] = []

        for line_offset in range(item_count):
            if cross_category and line_offset == 0:
                chosen_leaf_index = primary_leaf_index
            elif cross_category and line_offset == 1:
                step = 1 + stable_int(
                    SEED, "order", order_index, "second_category_step"
                ) % (len(leaves) - 1)
                chosen_leaf_index = (primary_leaf_index + step) % len(leaves)
            else:
                chosen_leaf_index = stable_int(
                    SEED, "order", order_index, f"leaf_{line_offset}"
                ) % len(leaves)
            used_leaf_indices.append(chosen_leaf_index)
            leaf_id = str(leaves[chosen_leaf_index]["category_id"])
            candidate_products = product_ids_by_leaf[leaf_id]
            product = candidate_products[
                stable_int(SEED, "order", order_index, f"product_{line_offset}")
                % len(candidate_products)
            ]
            product_id = str(product["product_id"])
            unit_cents = int(product["_price_cents"])
            quantity = (
                1
                + stable_int(SEED, "order", order_index, f"quantity_{line_offset}") % 5
            )
            line_gross = unit_cents * quantity
            maximum_discount = line_gross // 5
            line_discount = stable_int(
                SEED, "order", order_index, f"discount_{line_offset}"
            ) % (maximum_discount + 1)
            line_net = line_gross - line_discount
            item_sequence += 1
            item_row = {
                "order_item_id": f"item_{item_sequence:07d}",
                "order_id": order_id,
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": money(unit_cents),
                "line_discount": money(line_discount),
                "line_amount_after_discount": money(line_net),
            }
            order_line_rows.append(item_row)
            gross_cents += line_gross
            discount_cents += line_discount
            if is_valid:
                category_id = str(product_by_id[product_id]["primary_leaf_category_id"])
                line_by_category[category_id] += 1
                sales_by_product[product_id] += line_net
                sales_by_category[category_id] += line_net
                category_order_ids[category_id].add(order_id)

        paid_cents = gross_cents - discount_cents if is_valid else 0
        order_row = {
            "order_id": order_id,
            "customer_id": customer_id,
            "channel_id": channel,
            "order_status": status,
            "created_at": timestamp(created_at),
            "paid_at": timestamp(paid_at),
            "currency": "CNY",
            "gross_amount": money(gross_cents),
            "discount_amount": money(discount_cents),
            "paid_amount": money(paid_cents),
        }
        orders.append(order_row)
        order_items.extend(order_line_rows)
        orders_by_id[order_id] = {
            **order_row,
            "_paid_date": order_date if is_valid else None,
            "_paid_cents": paid_cents,
        }
        if is_valid:
            sales_by_date[order_date] += paid_cents
            order_count_by_date[order_date] += 1
            sales_by_channel[channel] += paid_cents
            channel_order_ids[channel].add(order_id)

    refunds: list[dict[str, object]] = []
    item_by_id = {str(item["order_item_id"]): item for item in order_items}
    for item in order_items:
        order_id = str(item["order_id"])
        order = orders_by_id[order_id]
        paid_date = order["_paid_date"]
        if (
            paid_date is None
            or stable_int(SEED, "refund", order_id, item["order_item_id"], "select")
            % 12
        ):
            continue
        line_cents = cents(item["line_amount_after_discount"])
        refund_seed = stable_int(
            SEED, "refund", order_id, item["order_item_id"], "shape"
        )
        refund_total = max(1, line_cents * (20 + refund_seed % 81) // 100)
        event_count = 2 if refund_seed % 5 == 0 and refund_total >= 2 else 1
        first_amount = refund_total // 2 if event_count == 2 else refund_total
        amounts = (
            [first_amount, refund_total - first_amount]
            if event_count == 2
            else [refund_total]
        )
        max_offset = max(0, (AS_OF - paid_date).days)
        request_day = paid_date + timedelta(
            days=min(
                max_offset, 1 + stable_int(SEED, "refund", order_id, "request") % 15
            )
        )
        status_roll = refund_seed % 10
        status = (
            "completed"
            if status_roll < 7
            else (
                "requested"
                if status_roll == 7
                else "rejected"
                if status_roll == 8
                else "cancelled"
            )
        )
        for event_index, amount in enumerate(amounts, start=1):
            event_id = f"ref_{len(refunds) + 1:07d}"
            requested_at = datetime.combine(request_day, time(9, 0)) + timedelta(
                seconds=stable_int(SEED, event_id, "request_time") % 32_400
            )
            completed_at = None
            if status == "completed":
                latest_completion = datetime.combine(AS_OF, time(23, 59, 59))
                completion_delay = timedelta(
                    seconds=1
                    + stable_int(SEED, event_id, "complete_delay") % (7 * 86_400)
                )
                completed_at = min(requested_at + completion_delay, latest_completion)
            refunds.append(
                {
                    "refund_id": event_id,
                    "order_item_id": str(item["order_item_id"]),
                    "refunded_amount": money(amount),
                    "requested_at": timestamp(requested_at),
                    "completed_at": timestamp(completed_at),
                    "refund_status": status,
                }
            )
    refund_totals: dict[str, int] = defaultdict(int)
    for refund in refunds:
        refund_totals[str(refund["order_item_id"])] += cents(refund["refunded_amount"])
    for item_id, refunded_cents in refund_totals.items():
        if refunded_cents > cents(item_by_id[item_id]["line_amount_after_discount"]):
            raise RuntimeError(f"Refund amount exceeds paid item amount: {item_id}")
    paid_at_by_item = {
        str(item["order_item_id"]): datetime.fromisoformat(
            str(orders_by_id[str(item["order_id"])]["paid_at"])
        )
        for item in order_items
        if orders_by_id[str(item["order_id"])]["paid_at"]
    }
    for refund in refunds:
        requested_at = datetime.fromisoformat(str(refund["requested_at"]))
        paid_at = paid_at_by_item[str(refund["order_item_id"])]
        if requested_at < paid_at:
            raise RuntimeError(
                f"Refund requested before payment: {refund['refund_id']}"
            )
        if refund["refund_status"] == "completed":
            completed_at = datetime.fromisoformat(str(refund["completed_at"]))
            if completed_at < requested_at:
                raise RuntimeError(
                    f"Refund completed before request: {refund['refund_id']} "
                    f"({completed_at.isoformat()} < {requested_at.isoformat()})"
                )
        elif refund["completed_at"]:
            raise RuntimeError(
                f"Incomplete refund has completed_at: {refund['refund_id']}"
            )
    counts = {
        "categories": write_csv(
            output_dir / "categories.csv", TABLE_FIELDS["categories"], categories
        ),
        "channels": write_csv(
            output_dir / "channels.csv", TABLE_FIELDS["channels"], channels
        ),
        "customers": write_csv(
            output_dir / "customers.csv", TABLE_FIELDS["customers"], customers
        ),
        "products": write_csv(
            output_dir / "products.csv",
            TABLE_FIELDS["products"],
            [
                {key: value for key, value in row.items() if not key.startswith("_")}
                for row in products
            ],
        ),
        "orders": write_csv(output_dir / "orders.csv", TABLE_FIELDS["orders"], orders),
        "order_items": write_csv(
            output_dir / "order_items.csv", TABLE_FIELDS["order_items"], order_items
        ),
        "refunds": write_csv(
            output_dir / "refunds.csv", TABLE_FIELDS["refunds"], refunds
        ),
    }
    if (
        len(orders) != 20_000
        or len([o for o in orders if o["order_status"] in ("paid", "completed")])
        != 18_000
    ):
        raise RuntimeError("Generated order/status quota mismatch")
    if any(order_count_by_date.get(day, 0) < 1 for day in valid_dates):
        raise RuntimeError("Main dataset must contain an eligible order on every date")
    if len(categories) != 30 or sum(int(row["level"]) == 2 for row in categories) != 27:
        raise RuntimeError(
            "Category tree must contain 3 parents and 27 leaf categories"
        )
    leaf_ids = {str(row["category_id"]) for row in categories if int(row["level"]) == 2}
    if len(products) != 500 or any(
        str(product["primary_leaf_category_id"]) not in leaf_ids for product in products
    ):
        raise RuntimeError(
            "Each product must reference exactly one existing leaf category"
        )
    item_totals: dict[str, int] = defaultdict(int)
    for item in order_items:
        item_totals[str(item["order_id"])] += cents(item["line_amount_after_discount"])
        if str(item["product_id"]) not in product_by_id:
            raise RuntimeError("Order item references an unknown product")
    for order in orders:
        order_id = str(order["order_id"])
        if order["order_status"] in ("paid", "completed") and item_totals[
            order_id
        ] != cents(order["paid_amount"]):
            raise RuntimeError(f"Order/item amount mismatch: {order_id}")
        if order["order_status"] in ("paid", "completed") and not order["paid_at"]:
            raise RuntimeError(f"Eligible order missing paid_at: {order_id}")
        if order["order_status"] not in ("paid", "completed") and (
            order["paid_at"] or cents(order["paid_amount"]) != 0
        ):
            raise RuntimeError(f"Ineligible order has payment values: {order_id}")
    if len(channels) != 5 or len(customers) != 8_000:
        raise RuntimeError("Dimension row count mismatch")

    manifest: dict[str, object] = {
        "dataset_id": DATASET_ID,
        "version": "1.1.0",
        "seed": SEED,
        "as_of_date": AS_OF.isoformat(),
        "timezone": "Asia/Shanghai",
        "date_window": {
            "start_inclusive": DATA_START.isoformat(),
            "end_exclusive": DATA_END_EXCLUSIVE.isoformat(),
        },
        "hash_algorithm": "SHA-256 over UTF-8 pipe-joined values; first 8 bytes unsigned big-endian",
        "row_counts": counts,
        "valid_order_statuses": ["paid", "completed"],
        "valid_orders_per_date_min": min(order_count_by_date.values()),
        "valid_orders_per_date_max": max(order_count_by_date.values()),
        "files": file_manifest(output_dir, counts),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    computed = {
        "categories": categories,
        "channels": channels,
        "products": products,
        "orders_by_id": orders_by_id,
        "order_items": order_items,
        "refunds": refunds,
        "sales_by_date": sales_by_date,
        "order_count_by_date": order_count_by_date,
        "sales_by_product": sales_by_product,
        "sales_by_category": sales_by_category,
        "category_order_ids": category_order_ids,
        "sales_by_channel": sales_by_channel,
        "channel_order_ids": channel_order_ids,
        "product_by_id": product_by_id,
    }
    return counts, computed


def generate_empty_day_fixture(
    output_dir: Path,
    categories: list[dict[str, object]],
    channels: list[dict[str, object]],
    customers: list[dict[str, object]],
    products: list[dict[str, object]],
) -> None:
    target_day = date(2025, 8, 10)
    categories_out = [{k: v for k, v in row.items()} for row in categories]
    channels_out = [{k: v for k, v in row.items()} for row in channels]
    customers_out = [dict(row) for row in customers[:1]]
    products_out = [
        {k: v for k, v in row.items() if not k.startswith("_")} for row in products[:2]
    ]
    orders: list[dict[str, object]] = []
    items: list[dict[str, object]] = []
    # Adjacent-day points demonstrate a three-day trend with a zero in the middle.
    for index, (day, amount_cents, product) in enumerate(
        [
            (target_day - timedelta(days=1), 10_000, products[0]),
            (target_day + timedelta(days=1), 20_000, products[1]),
        ],
        start=1,
    ):
        order_id = f"fx_ord_{index:03d}"
        item_id = f"fx_item_{index:03d}"
        event = datetime.combine(day, time(12, 0))
        product_id = str(product["product_id"])
        orders.append(
            {
                "order_id": order_id,
                "customer_id": str(customers_out[0]["customer_id"]),
                "channel_id": str(channels_out[0]["channel_id"]),
                "order_status": "paid",
                "created_at": timestamp(event - timedelta(hours=1)),
                "paid_at": timestamp(event),
                "currency": "CNY",
                "gross_amount": money(amount_cents),
                "discount_amount": "0.00",
                "paid_amount": money(amount_cents),
            }
        )
        items.append(
            {
                "order_item_id": item_id,
                "order_id": order_id,
                "product_id": product_id,
                "quantity": 1,
                "unit_price": money(amount_cents),
                "line_discount": "0.00",
                "line_amount_after_discount": money(amount_cents),
            }
        )
    counts = {
        "categories": write_csv(
            output_dir / "categories.csv", TABLE_FIELDS["categories"], categories_out
        ),
        "channels": write_csv(
            output_dir / "channels.csv", TABLE_FIELDS["channels"], channels_out
        ),
        "customers": write_csv(
            output_dir / "customers.csv", TABLE_FIELDS["customers"], customers_out
        ),
        "products": write_csv(
            output_dir / "products.csv", TABLE_FIELDS["products"], products_out
        ),
        "orders": write_csv(output_dir / "orders.csv", TABLE_FIELDS["orders"], orders),
        "order_items": write_csv(
            output_dir / "order_items.csv", TABLE_FIELDS["order_items"], items
        ),
        "refunds": write_csv(output_dir / "refunds.csv", TABLE_FIELDS["refunds"], []),
    }
    expected_days = {
        (target_day - timedelta(days=1)).isoformat(): {
            "valid_order_count": 1,
            "sales_amount": "100.00",
        },
        target_day.isoformat(): {"valid_order_count": 0, "sales_amount": "0.00"},
        (target_day + timedelta(days=1)).isoformat(): {
            "valid_order_count": 1,
            "sales_amount": "200.00",
        },
    }
    observed_valid_orders: dict[str, list[dict[str, object]]] = defaultdict(list)
    for order in orders:
        if order["order_status"] in ("paid", "completed") and order["paid_at"]:
            observed_valid_orders[str(order["paid_at"])[:10]].append(order)
    for day_text, expected in expected_days.items():
        observed = observed_valid_orders.get(day_text, [])
        observed_sales = sum(cents(order["paid_amount"]) for order in observed)
        if (
            len(observed) != expected["valid_order_count"]
            or money(observed_sales) != expected["sales_amount"]
        ):
            raise RuntimeError(f"Empty-day fixture expectation mismatch: {day_text}")
    manifest = {
        "dataset_id": EMPTY_FIXTURE_ID,
        "version": "1.0.0",
        "fixture_kind": "empty_day_and_trend_zero_fill",
        "target_date": target_day.isoformat(),
        "timezone": "Asia/Shanghai",
        "expected_valid_order_count_on_target_date": 0,
        "expected_sales_amount_on_target_date": "0.00",
        "expected_three_day_trend": expected_days,
        "row_counts": counts,
        "files": file_manifest(output_dir, counts),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def calculate_golden_results(data: dict[str, object]) -> str:
    orders_by_id = data["orders_by_id"]
    items = data["order_items"]
    channels = data["channels"]
    categories = data["categories"]
    products = data["product_by_id"]
    valid_orders = [
        row for row in orders_by_id.values() if row["_paid_date"] is not None
    ]
    valid_order_ids_by_day: dict[date, list[str]] = defaultdict(list)
    sales_by_day: dict[date, int] = defaultdict(int)
    for order in valid_orders:
        day = order["_paid_date"]
        valid_order_ids_by_day[day].append(str(order["order_id"]))
        sales_by_day[day] += cents(order["paid_amount"])

    item_sales: dict[str, int] = defaultdict(int)
    category_sales: dict[str, int] = defaultdict(int)
    category_order_ids: dict[str, set[str]] = defaultdict(set)
    channel_order_ids: dict[str, set[str]] = defaultdict(set)
    recent30_start = date(2026, 7, 2)
    recent30_end = date(2026, 8, 1)
    recent30_product_sales: dict[str, int] = defaultdict(int)
    recent30_category_sales: dict[str, int] = defaultdict(int)
    recent30_category_orders: dict[str, set[str]] = defaultdict(set)
    recent30_channel_sales: dict[str, int] = defaultdict(int)
    recent30_channel_orders: dict[str, set[str]] = defaultdict(set)
    order_category_membership: dict[str, set[str]] = defaultdict(set)
    item_by_id = {str(item["order_item_id"]): item for item in items}
    recent30_product_orders: dict[str, set[str]] = defaultdict(set)
    recent30_refund_orders: dict[str, set[str]] = defaultdict(set)

    for item in items:
        order = orders_by_id[str(item["order_id"])]
        day = order["_paid_date"]
        if day is None:
            continue
        line_cents = cents(item["line_amount_after_discount"])
        product_id = str(item["product_id"])
        category_id = str(products[product_id]["primary_leaf_category_id"])
        channel_id = str(order["channel_id"])
        item_sales[product_id] += line_cents
        category_sales[category_id] += line_cents
        category_order_ids[category_id].add(str(order["order_id"]))
        channel_order_ids[channel_id].add(str(order["order_id"]))
        order_category_membership[str(order["order_id"])].add(category_id)
        if recent30_start <= day < recent30_end:
            recent30_product_sales[product_id] += line_cents
            recent30_category_sales[category_id] += line_cents
            recent30_category_orders[category_id].add(str(order["order_id"]))
            recent30_channel_orders[channel_id].add(str(order["order_id"]))
            recent30_product_orders[product_id].add(str(order["order_id"]))

    for refund in data["refunds"]:
        if refund["refund_status"] != "completed":
            continue
        item = item_by_id[str(refund["order_item_id"])]
        order = orders_by_id[str(item["order_id"])]
        day = order["_paid_date"]
        if day is not None and recent30_start <= day < recent30_end:
            recent30_refund_orders[str(item["product_id"])].add(str(order["order_id"]))

    for order in valid_orders:
        day = order["_paid_date"]
        if recent30_start <= day < recent30_end:
            channel_id = str(order["channel_id"])
            recent30_channel_sales[channel_id] += cents(order["paid_amount"])

    def sum_period(start: date, end: date) -> tuple[int, int]:
        ids = [
            order_id
            for day, day_ids in valid_order_ids_by_day.items()
            if start <= day < end
            for order_id in day_ids
        ]
        sales = sum(cents(orders_by_id[order_id]["paid_amount"]) for order_id in ids)
        return sales, len(set(ids))

    def money_text(cents: int) -> str:
        return money(cents)

    def average_text(sales_cents: int, order_count: int) -> str:
        if order_count == 0:
            return "N/A"
        amount = (Decimal(sales_cents) / Decimal(order_count) / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"{amount:.2f}"

    def percent_text(numerator: int, denominator: int) -> str:
        if denominator == 0:
            return "N/A"
        rate = (Decimal(numerator) * 100 / Decimal(denominator)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"{rate:.2f}%"

    lines: list[str] = [
        "# 电商 ChatBI 黄金预期结果（ecommerce_mock_v1）",
        "",
        "- 数据集：`ecommerce_mock_v1` v1.1.0；参考日期：2026-08-01；时区：Asia/Shanghai。",
        "- 金额单位：CNY；订单范围：`paid`/`completed`；销售额不扣退款。",
        "- 由 `scripts/generate_mock_data.py` 根据固定种子生成；重新生成后结果应保持一致。",
        "",
    ]

    day = date(2026, 7, 31)
    sales, count = sum_period(day, day + timedelta(days=1))
    lines += [
        "## UQ-01 昨日汇总",
        "",
        "| 日期 | 销售额 | 订单数 |",
        "|---|---:|---:|",
        f"| {day.isoformat()} | {money_text(sales)} | {count} |",
        "",
    ]

    lines += ["## UQ-02 最近 7 天每日销售额", "", "| 日期 | 销售额 |", "|---|---:|"]
    for offset in range(7, 0, -1):
        current_day = date(2026, 8, 1) - timedelta(days=offset)
        lines.append(
            f"| {current_day.isoformat()} | {money_text(sales_by_day[current_day])} |"
        )
    lines.append("")

    july_sales, _ = sum_period(date(2026, 7, 1), date(2026, 8, 1))
    june_sales, _ = sum_period(date(2026, 6, 1), date(2026, 7, 1))
    change = july_sales - june_sales
    lines += [
        "## UQ-03 7 月与 6 月销售额比较",
        "",
        "| 本期销售额 | 上期销售额 | 变化额 | 变化率 |",
        "|---:|---:|---:|---:|",
        f"| {money_text(july_sales)} | {money_text(june_sales)} | {money_text(change)} | {percent_text(change, june_sales)} |",
        "",
    ]

    top_products = sorted(
        (
            (product_id, value)
            for product_id, value in recent30_product_sales.items()
            if value > 0
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )[:10]
    lines += [
        "## UQ-04 最近 30 天商品销售额 Top 10",
        "",
        "| 排名 | 商品 ID | 商品名称 | 销售额 |",
        "|---:|---|---|---:|",
    ]
    for rank, (product_id, value) in enumerate(top_products, start=1):
        lines.append(
            f"| {rank} | {product_id} | {products[product_id]['product_name']} | {money_text(value)} |"
        )
    lines.append("")

    lines += [
        "## UQ-05 最近 30 天叶子类目汇总",
        "",
        "| 类目 | 订单数（类目内去重） | 销售额 |",
        "|---|---:|---:|",
    ]
    leaf_categories = [row for row in categories if int(row["level"]) == 2]
    for category in leaf_categories:
        category_id = str(category["category_id"])
        lines.append(
            f"| {category['category_name']} | {len(recent30_category_orders[category_id])} | {money_text(recent30_category_sales[category_id])} |"
        )
    lines += [
        "",
        "> 类目订单数按订单是否涉及该类目分别计数，跨类目订单会在多个类目各计一次。",
        "",
    ]

    lines += [
        "## UQ-06 最近 30 天渠道客单价",
        "",
        "| 渠道 | 有效订单数 | 销售额 | 客单价 |",
        "|---|---:|---:|---:|",
    ]
    for channel in channels:
        channel_id = str(channel["channel_id"])
        channel_orders = len(recent30_channel_orders[channel_id])
        channel_amount = recent30_channel_sales[channel_id]
        lines.append(
            f"| {channel['channel_name']} | {channel_orders} | {money_text(channel_amount)} | {average_text(channel_amount, channel_orders)} |"
        )
    lines.append("")

    refund_rate_rows: list[tuple[Decimal, str, int, int]] = []
    for product_id, order_ids in recent30_product_orders.items():
        numerator = len(recent30_refund_orders[product_id])
        denominator = len(order_ids)
        if denominator:
            refund_rate_rows.append(
                (
                    Decimal(numerator) / Decimal(denominator),
                    product_id,
                    numerator,
                    denominator,
                )
            )
    refund_rate_rows.sort(key=lambda row: (-row[0], row[1]))
    lines += [
        "## UQ-07 最近 30 天商品退款订单率 Top 10",
        "",
        "| 排名 | 商品 ID | 商品名称 | 退款订单数 | 有效订单数 | 退款订单率 |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for rank, (rate, product_id, numerator, denominator) in enumerate(
        refund_rate_rows[:10], start=1
    ):
        rounded = (rate * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lines.append(
            f"| {rank} | {product_id} | {products[product_id]['product_name']} | "
            f"{numerator} | {denominator} | {rounded:.2f}% |"
        )
    lines += [
        "",
        "> 分母按订单支付日期筛选；分子为该商品 cohort 中截至数据集快照有 completed 退款的去重订单数。",
        "",
    ]

    lines += [
        "## UQ-08 本周与上周同期类目销售额",
        "",
        "| 类目 | 本周销售额 | 上周同期销售额 | 变化额 |",
        "|---|---:|---:|---:|",
    ]
    category_changes: list[tuple[int, str, int, int]] = []
    for category in leaf_categories:
        category_id = str(category["category_id"])
        current = sum(
            cents(item["line_amount_after_discount"])
            for item in items
            if str(item["order_id"]) in orders_by_id
            and orders_by_id[str(item["order_id"])]["_paid_date"] is not None
            and date(2026, 7, 27)
            <= orders_by_id[str(item["order_id"])]["_paid_date"]
            < date(2026, 8, 1)
            and str(products[str(item["product_id"])]["primary_leaf_category_id"])
            == category_id
        )
        previous = sum(
            cents(item["line_amount_after_discount"])
            for item in items
            if str(item["order_id"]) in orders_by_id
            and orders_by_id[str(item["order_id"])]["_paid_date"] is not None
            and date(2026, 7, 20)
            <= orders_by_id[str(item["order_id"])]["_paid_date"]
            < date(2026, 7, 25)
            and str(products[str(item["product_id"])]["primary_leaf_category_id"])
            == category_id
        )
        category_changes.append(
            (current - previous, str(category["category_name"]), current, previous)
        )
    for delta, name, current, previous in sorted(category_changes):
        lines.append(
            f"| {name} | {money_text(current)} | {money_text(previous)} | {money_text(delta)} |"
        )
    lines.append("")

    # This fixed pair exercises the stated UQ-09 premise: orders increase while
    # sales decrease, allowing the golden case to inspect both contributions.
    previous_period = sum_period(date(2025, 8, 21), date(2025, 8, 28))
    current_period = sum_period(date(2025, 8, 28), date(2025, 9, 4))
    current_sales, current_orders = current_period
    previous_sales, previous_orders = previous_period
    previous_aov = (
        Decimal(previous_sales) / previous_orders if previous_orders else Decimal(0)
    )
    delta_sales = current_sales - previous_sales
    order_impact_raw = Decimal(current_orders - previous_orders) * previous_aov
    order_impact = int(order_impact_raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    aov_impact = delta_sales - order_impact
    lines += [
        "## UQ-09 相邻 7 天期间的数值分解",
        "",
        "| 周期 | 订单数 | 销售额 | 客单价 |",
        "|---|---:|---:|---:|",
        f"| 当前期 2025-08-28 至 2025-09-03 | {current_orders} | {money_text(current_sales)} | {average_text(current_sales, current_orders)} |",
        f"| 对比期 2025-08-21 至 2025-08-27 | {previous_orders} | {money_text(previous_sales)} | {average_text(previous_sales, previous_orders)} |",
        "",
        f"销售额变化：{money_text(delta_sales)}；订单数变化：{current_orders - previous_orders}；订单数变化贡献：{money_text(order_impact)}；客单价变化贡献：{money_text(aov_impact)}。两项贡献按分币舍入后相加等于销售额变化。此为恒等数值分解，不作因果结论。",
        "",
        "## UQ-10 术语处理",
        "",
        "`销售额`解释为有效订单按 `paid_at` 归属日统计的折后实付金额，退款不扣减；`收入`无默认映射，澄清前不执行查询。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    data_dir = ROOT / "data" / "generated" / DATASET_ID
    fixture_dir = ROOT / "data" / "generated" / EMPTY_FIXTURE_ID
    counts, computed = generate_main_dataset(data_dir)
    categories, channels, customers, products, _ = build_dimensions()
    generate_empty_day_fixture(fixture_dir, categories, channels, customers, products)
    golden_path = ROOT / "docs" / "acceptance" / "GOLDEN_RESULTS.md"
    golden_path.write_text(calculate_golden_results(computed), encoding="utf-8")
    print(
        f"Generated {DATASET_ID}: {counts['orders']} orders, {counts['order_items']} order items."
    )
    print(f"Generated isolated fixture: {EMPTY_FIXTURE_ID}.")
    print(f"Wrote exact expected outputs: {golden_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
