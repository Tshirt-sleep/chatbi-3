import json
from pathlib import Path

import pytest
from backend.chatbi.saas_catalog import (
    ACTIVE_SAAS_CATALOG,
    CATALOG_PATH,
    MANIFEST_PATH,
    load_saas_catalog,
)
from harness.run_saas_eval import run


def test_saas_catalog_loads_a_fixed_snapshot() -> None:
    assert ACTIVE_SAAS_CATALOG.catalog.dataset_id == "saas_subscription_mock_v1"
    assert ACTIVE_SAAS_CATALOG.catalog.catalog_id == "saas_subscription_mock_semantics"
    assert ACTIVE_SAAS_CATALOG.as_of_date.isoformat() == "2026-08-01"
    assert ACTIVE_SAAS_CATALOG.start_date.isoformat() == "2025-08-01"


def test_saas_catalog_schema_rejects_unknown_properties(tmp_path: Path) -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog["unreviewed_property"] = True
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid SaaS semantic catalog"):
        load_saas_catalog(catalog_path, MANIFEST_PATH)


def test_saas_catalog_rejects_manifest_for_another_dataset(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["dataset_id"] = "ecommerce_mock_v1"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="dataset_id mismatch"):
        load_saas_catalog(CATALOG_PATH, manifest_path)


def test_saas_api_route_and_sql_golden_acceptance() -> None:
    report = run()
    assert report["status"] == "passed"
    assert report["passed_case_count"] == 14
