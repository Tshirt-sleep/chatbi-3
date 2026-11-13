from datetime import date
from types import SimpleNamespace

from backend.chatbi.main import create_session
from backend.chatbi.query_schemas import CreateSessionRequest
from backend.chatbi.query_service import _evidence
from backend.chatbi.semantic_catalog import ACTIVE_CATALOG
from backend.chatbi.time_periods import completed_month_comparison, completed_week_comparison
from backend.chatbi.trace import trace_record


def test_dataset_manifest_version_is_captured_in_snapshot_and_evidence() -> None:
    assert ACTIVE_CATALOG.dataset_version == "1.1.0"

    evidence = _evidence(["测试指标口径"])
    assert evidence.dataset_id == ACTIVE_CATALOG.catalog.dataset_id
    assert evidence.dataset_version == ACTIVE_CATALOG.dataset_version
    assert evidence.semantic_catalog_id == ACTIVE_CATALOG.catalog.catalog_id
    assert evidence.semantic_catalog_version == ACTIVE_CATALOG.catalog.version


def test_session_response_uses_active_catalog_snapshot() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(request_id="test-request"), headers={"x-mock-user": "analyst"}
    )

    response = create_session(CreateSessionRequest(), request)

    assert response.dataset_version == ACTIVE_CATALOG.dataset_version
    assert response.semantic_catalog_id == ACTIVE_CATALOG.catalog.catalog_id
    assert response.semantic_catalog_version == ACTIVE_CATALOG.catalog.version


def test_trace_metadata_is_stamped_from_active_snapshot() -> None:
    trace = trace_record(
        "test-request",
        semantic_catalog_id="stale-catalog",
        semantic_catalog_version="9.9.9",
    )

    assert trace.dataset_id == ACTIVE_CATALOG.catalog.dataset_id
    assert trace.dataset_version == ACTIVE_CATALOG.dataset_version
    assert trace.semantic_catalog_id == ACTIVE_CATALOG.catalog.catalog_id
    assert trace.semantic_catalog_version == ACTIVE_CATALOG.catalog.version


def test_calendar_periods_come_from_manifest_reference_and_policy() -> None:
    assert completed_month_comparison() == (
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 6, 1),
        date(2026, 7, 1),
    )
    assert completed_week_comparison() == (
        date(2026, 7, 27),
        date(2026, 8, 1),
        date(2026, 7, 20),
        date(2026, 7, 25),
    )
