#!/usr/bin/env python3
"""Generate deterministic synthetic SaaS subscription data for P8-4."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "saas_subscription_mock_v1"
SEED = "20260801-saas-v1"
START = date(2025, 8, 1)
AS_OF = date(2026, 8, 1)
TZ = timezone(timedelta(hours=8))
FIELDS = {
    "accounts.csv": ["account_id", "account_name", "region", "created_at"],
    "plans.csv": ["plan_id", "plan_name", "monthly_fee_cents", "status"],
    "subscriptions.csv": [
        "subscription_id",
        "account_id",
        "plan_id",
        "acquisition_channel_id",
        "started_at",
        "canceled_at",
        "status",
    ],
    "acquisition_channels.csv": ["channel_id", "channel_name"],
}
PLANS = [
    ("plan_01", "基础版", 9900),
    ("plan_02", "成长版", 29900),
    ("plan_03", "专业版", 89900),
    ("plan_04", "企业版", 199900),
]
CHANNELS = [
    ("channel_01", "官网"),
    ("channel_02", "合作伙伴"),
    ("channel_03", "内容营销"),
    ("channel_04", "销售拓展"),
]


def stable_int(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def iso(day: date, salt: object) -> str:
    seconds = stable_int(SEED, salt) % 86400
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=TZ)
        + timedelta(seconds=seconds)
    ).isoformat(timespec="seconds")


def write_csv(
    path: Path, fields: list[str], rows: list[dict[str, object]]
) -> dict[str, object]:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    content = path.read_bytes()
    return {"rows": len(rows), "sha256": hashlib.sha256(content).hexdigest()}


def build() -> tuple[dict[str, list[dict[str, object]]], dict[str, int]]:
    accounts = [
        {
            "account_id": f"acct_{i:05d}",
            "account_name": f"合成企业客户{i:05d}",
            "region": ("华东", "华南", "华北", "西南")[
                stable_int(SEED, "region", i) % 4
            ],
            "created_at": iso(
                START
                + timedelta(
                    days=stable_int(SEED, "acctdate", i) % (AS_OF - START).days
                ),
                i,
            ),
        }
        for i in range(1, 2401)
    ]
    plans = [
        {
            "plan_id": plan_id,
            "plan_name": name,
            "monthly_fee_cents": cents,
            "status": "active",
        }
        for plan_id, name, cents in PLANS
    ]
    channels = [
        {"channel_id": channel_id, "channel_name": name}
        for channel_id, name in CHANNELS
    ]
    subscriptions: list[dict[str, object]] = []
    span = (AS_OF - START).days
    for i in range(1, 6001):
        offset = stable_int(SEED, "start", i) % span
        start = START + timedelta(days=offset)
        is_canceled = stable_int(SEED, "canceled", i) % 100 < 22
        cancel = ""
        if is_canceled:
            cancel_offset = stable_int(SEED, "cancel-date", i) % max(
                1, (AS_OF - start).days
            )
            cancel_day = start + timedelta(days=cancel_offset)
            cancel = iso(cancel_day, f"cancel-{i}")
        account_index = 1 + stable_int(SEED, "account", i) % len(accounts)
        subscriptions.append(
            {
                "subscription_id": f"sub_{i:06d}",
                "account_id": f"acct_{account_index:05d}",
                "plan_id": PLANS[stable_int(SEED, "plan", i) % len(PLANS)][0],
                "acquisition_channel_id": CHANNELS[
                    stable_int(SEED, "channel", i) % len(CHANNELS)
                ][0],
                "started_at": iso(start, f"start-{i}"),
                "canceled_at": cancel,
                "status": "canceled" if cancel else "active",
            }
        )
    return {
        "accounts.csv": accounts,
        "plans.csv": plans,
        "subscriptions.csv": subscriptions,
        "acquisition_channels.csv": channels,
    }, {
        "accounts": len(accounts),
        "plans": len(plans),
        "subscriptions": len(subscriptions),
        "acquisition_channels": len(channels),
    }


def main() -> None:
    files, counts = build()
    output = ROOT / "data" / "generated" / DATASET_ID
    output.mkdir(parents=True, exist_ok=True)
    file_meta = {
        name: write_csv(output / name, FIELDS[name], rows)
        for name, rows in files.items()
    }
    manifest = {
        "dataset_id": DATASET_ID,
        "version": "1.0.0",
        "seed": SEED,
        "as_of_date": AS_OF.isoformat(),
        "timezone": "Asia/Shanghai",
        "date_window": {
            "start_inclusive": START.isoformat(),
            "end_exclusive": AS_OF.isoformat(),
        },
        "valid_subscription_statuses": ["active", "canceled"],
        "row_counts": counts,
        "files": file_meta,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Generated {DATASET_ID}: {counts['subscriptions']} subscriptions")


if __name__ == "__main__":
    main()
