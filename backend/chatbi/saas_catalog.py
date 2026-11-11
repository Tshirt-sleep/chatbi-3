"""Strict startup validation for the independently implemented SaaS catalog."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import ROOT

CATALOG_PATH = ROOT / "backend" / "chatbi" / "catalogs" / "saas_subscription_mock_semantics.json"
MANIFEST_PATH = ROOT / "data" / "generated" / "saas_subscription_mock_v1" / "manifest.json"
DATASET_ID = "saas_subscription_mock_v1"
CATALOG_ID = "saas_subscription_mock_semantics"
SUPPORTED_QUERIES = frozenset(
    {
        "active_snapshot",
        "mrr_snapshot",
        "new_subscriptions_period",
        "new_subscriptions_trend",
        "active_subscriptions_by_plan",
        "mrr_by_plan",
    }
)
METRIC_IMPLEMENTATIONS = frozenset({"active_subscriptions", "mrr", "new_subscriptions"})
DIMENSION_IMPLEMENTATIONS = frozenset({"plan", "subscription_date"})
FIELD_REFS = frozenset(
    {
        "saas_subscriptions.plan_id",
        "saas_plans.plan_name",
        "saas_subscriptions.started_at",
    }
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class Metric(FrozenModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    aliases: tuple[str, ...]
    allowed_dimension_ids: tuple[str, ...]
    implementation_id: str
    status: Literal["active"]


class Dimension(FrozenModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    aliases: tuple[str, ...]
    allowed_metric_ids: tuple[str, ...]
    field_refs: tuple[str, ...]
    implementation_id: str
    status: Literal["active"]


class Term(FrozenModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    text: str = Field(min_length=1)
    resolution: Literal["ambiguous", "unsupported"]
    target_id: str | None
    candidate_ids: tuple[str, ...]
    note: str = Field(min_length=1)


class Catalog(FrozenModel):
    schema_version: Literal["1"]
    catalog_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    status: Literal["active"]
    dataset_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    timezone: Literal["Asia/Shanghai"]
    change_note: str = Field(min_length=1)
    metrics: tuple[Metric, ...] = Field(min_length=1)
    dimensions: tuple[Dimension, ...] = Field(min_length=1)
    terms: tuple[Term, ...]
    supported_queries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SaaSSnapshot:
    catalog: Catalog
    dataset_version: str
    start_date: date
    end_date: date
    as_of_date: date


def _arrays_to_tuples(value: object) -> object:
    if isinstance(value, list):
        return tuple(_arrays_to_tuples(item) for item in value)
    if isinstance(value, dict):
        return {key: _arrays_to_tuples(item) for key, item in value.items()}
    return value


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def load_saas_catalog(
    catalog_path: Path = CATALOG_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> SaaSSnapshot:
    try:
        raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        catalog = Catalog.model_validate(_arrays_to_tuples(raw_catalog))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError(f"Invalid SaaS semantic catalog or dataset manifest: {error}") from error
    if catalog.catalog_id != CATALOG_ID or catalog.dataset_id != DATASET_ID:
        raise ValueError("SaaS catalog ID or dataset ID mismatch")
    if raw_manifest.get("dataset_id") != DATASET_ID:
        raise ValueError("SaaS manifest dataset_id mismatch")
    if raw_manifest.get("timezone") != catalog.timezone:
        raise ValueError("SaaS manifest timezone mismatch")
    date_window = raw_manifest.get("date_window", {})
    try:
        start = date.fromisoformat(date_window["start_inclusive"])
        end = date.fromisoformat(date_window["end_exclusive"])
        as_of = date.fromisoformat(raw_manifest["as_of_date"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("SaaS manifest has invalid date bounds") from error
    if (
        start >= end
        or end != as_of
        or raw_manifest.get("valid_subscription_statuses") != ["active", "canceled"]
    ):
        raise ValueError("SaaS manifest date/status policy mismatch")
    metrics = {metric.id: metric for metric in catalog.metrics}
    dimensions = {dimension.id: dimension for dimension in catalog.dimensions}
    if len(metrics) != len(catalog.metrics) or len(dimensions) != len(catalog.dimensions):
        raise ValueError("SaaS catalog contains duplicate IDs")
    term_ids = {term.id for term in catalog.terms}
    if len(term_ids) != len(catalog.terms):
        raise ValueError("SaaS catalog contains duplicate term IDs")
    if {metric.implementation_id for metric in catalog.metrics} != METRIC_IMPLEMENTATIONS:
        raise ValueError("SaaS metric implementation allowlist mismatch")
    if {
        dimension.implementation_id for dimension in catalog.dimensions
    } != DIMENSION_IMPLEMENTATIONS:
        raise ValueError("SaaS dimension implementation allowlist mismatch")
    for dimension in catalog.dimensions:
        if not set(dimension.field_refs) <= FIELD_REFS:
            raise ValueError(f"SaaS field ref not allowlisted: {dimension.id}")
        if any(metric_id not in metrics for metric_id in dimension.allowed_metric_ids):
            raise ValueError(f"SaaS unknown metric reference: {dimension.id}")
    for metric in catalog.metrics:
        if any(dimension_id not in dimensions for dimension_id in metric.allowed_dimension_ids):
            raise ValueError(f"SaaS unknown dimension reference: {metric.id}")
        if any(
            metric.id not in dimensions[dimension_id].allowed_metric_ids
            for dimension_id in metric.allowed_dimension_ids
        ):
            raise ValueError(f"SaaS metric/dimension relationship mismatch: {metric.id}")
    aliases: dict[str, str] = {}
    for item_id, label, item_aliases in (
        (item.id, item.label, item.aliases) for item in catalog.metrics
    ):
        for alias in (label, *item_aliases):
            normalized = _normalize(alias)
            owner = aliases.setdefault(normalized, item_id)
            if owner != item_id:
                raise ValueError(f"SaaS alias collision: {alias}")
    for item_id, label, item_aliases in (
        (item.id, item.label, item.aliases) for item in catalog.dimensions
    ):
        for alias in (label, *item_aliases):
            normalized = _normalize(alias)
            owner = aliases.setdefault(normalized, item_id)
            if owner != item_id:
                raise ValueError(f"SaaS alias collision: {alias}")
    normalized_terms: set[str] = set()
    for term in catalog.terms:
        normalized = _normalize(term.text)
        if normalized in normalized_terms or normalized in aliases:
            raise ValueError(f"SaaS term conflicts with alias: {term.text}")
        normalized_terms.add(normalized)
        if any(
            candidate not in metrics or metrics[candidate].status != "active"
            for candidate in term.candidate_ids
        ):
            raise ValueError(f"SaaS term candidate is not an active metric: {term.id}")
        if term.target_id is not None:
            raise ValueError(f"SaaS clarification terms must not map directly: {term.id}")
    if set(catalog.supported_queries) != SUPPORTED_QUERIES:
        raise ValueError("SaaS supported query list differs from code allowlist")
    return SaaSSnapshot(
        catalog=catalog,
        dataset_version=str(raw_manifest.get("version", "")),
        start_date=start,
        end_date=end,
        as_of_date=as_of,
    )


ACTIVE_SAAS_CATALOG = load_saas_catalog()
