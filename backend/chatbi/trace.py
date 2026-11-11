"""Redacted trace shape shared by query processing and future model calls."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .semantic_catalog import ACTIVE_CATALOG


class QueryTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    session_id: str | None = None
    turn_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    semantic_catalog_id: str | None = None
    semantic_catalog_version: str | None = None
    resolver: Literal["rules", "llm", "none"] = "none"
    prompt_template_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    validation_status: Literal["not_run", "passed", "clarification", "rejected"] = "not_run"
    validation_code: str | None = None
    query_template_id: str | None = None
    query_executed: bool = False
    query_duration_ms: int | None = None
    result_row_count: int | None = None
    outcome: Literal["pending", "completed", "clarification", "rejected", "failed"] = "pending"
    error_code: str | None = None


def trace_record(request_id: str, **values: object) -> QueryTrace:
    """Build a metadata-only trace stamped with the active dataset/catalog snapshot."""
    values.update(
        dataset_id=ACTIVE_CATALOG.catalog.dataset_id,
        dataset_version=ACTIVE_CATALOG.dataset_version,
        semantic_catalog_id=ACTIVE_CATALOG.catalog.catalog_id,
        semantic_catalog_version=ACTIVE_CATALOG.catalog.version,
    )
    return QueryTrace(request_id=request_id, **values)  # type: ignore[arg-type]
