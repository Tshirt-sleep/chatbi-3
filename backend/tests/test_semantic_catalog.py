"""Catalog load and cross-reference validation tests."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from backend.chatbi.semantic_catalog import (
    ACTIVE_CATALOG,
    CATALOG_PATH,
    CatalogLoadError,
    load_catalog,
)
from pydantic import ValidationError

MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "generated"
    / "ecommerce_mock_v1"
    / "manifest.json"
)


def _catalog_data() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _write_case(tmp_path: Path, catalog: dict[str, Any]) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return path


def test_active_catalog_is_loaded_once_as_an_immutable_snapshot() -> None:
    assert ACTIVE_CATALOG.catalog.catalog_id == "ecommerce_mock_semantics"
    assert ACTIVE_CATALOG.catalog.version == "1.1.0"
    assert ACTIVE_CATALOG.dataset_start_date.isoformat() == "2025-08-01"
    assert ACTIVE_CATALOG.dataset_end_exclusive.isoformat() == "2026-08-01"
    assert isinstance(ACTIVE_CATALOG.catalog.metrics, tuple)
    with pytest.raises(ValidationError):
        ACTIVE_CATALOG.catalog.version = "9.9.9"  # type: ignore[misc]

    from backend.chatbi.query_service import ACTIVE_CATALOG as service_catalog

    assert service_catalog is ACTIVE_CATALOG


@pytest.mark.parametrize(
    ("mutate", "expected_path", "reason"),
    [
        (
            lambda data: data["metrics"][0].update({"definition": None}),
            "metrics.0.definition",
            "string_type",
        ),
        (
            lambda data: data["metrics"][0].update({"label": 123}),
            "metrics.0.label",
            "string_type",
        ),
        (
            lambda data: data["capabilities"][0].update({"template_id": "arbitrary_sql"}),
            "capabilities",
            "template_mapping_mismatch",
        ),
        (
            lambda data: data["metrics"][0].update({"allowed_dimension_ids": ["missing_dim"]}),
            "metrics[0].allowed_dimension_ids",
            "unknown_or_inactive_dimension",
        ),
        (
            lambda data: data["metrics"][1].update({"aliases": ["GMV"]}),
            "metrics[1].aliases",
            "alias_collision",
        ),
    ],
)
def test_invalid_catalog_reports_location_and_reason(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    expected_path: str,
    reason: str,
) -> None:
    data = _catalog_data()
    mutate(data)
    with pytest.raises(CatalogLoadError) as error:
        load_catalog(_write_case(tmp_path, data), MANIFEST_PATH)
    assert expected_path in str(error.value)
    assert reason in str(error.value)


def test_manifest_dataset_mismatch_prevents_loading(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["dataset_id"] = "another_dataset"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CatalogLoadError, match="dataset_id: manifest_dataset_mismatch"):
        load_catalog(_write_case(tmp_path, _catalog_data()), manifest_path)


def test_invalid_json_reports_line_and_column(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"catalog_id": }', encoding="utf-8")

    with pytest.raises(CatalogLoadError, match="invalid_json_line_1_column_"):
        load_catalog(path, MANIFEST_PATH)


def test_invalid_active_catalog_prevents_api_import() -> None:
    script = f"""
from pathlib import Path
catalog_path = Path({str(CATALOG_PATH)!r}).resolve()
read_text = Path.read_text
def broken_catalog(self, *args, **kwargs):
    if self.resolve() == catalog_path:
        return '{{"schema_version":"invalid"}}'
    return read_text(self, *args, **kwargs)
Path.read_text = broken_catalog
try:
    import backend.chatbi.main
except Exception as error:
    assert type(error).__name__ == "CatalogLoadError"
else:
    raise AssertionError("API imported with an invalid active semantic catalog")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=CATALOG_PATH.parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, "invalid active catalog unexpectedly allowed API startup"
