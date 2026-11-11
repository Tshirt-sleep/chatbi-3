"""Strict, immutable semantic catalog loading and startup validation."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import ROOT
from .query_capabilities import (
    SUPPORTED_CAPABILITIES,
    SUPPORTED_DIMENSION_IMPLEMENTATIONS,
    SUPPORTED_FIELD_REFS,
    SUPPORTED_METRIC_IMPLEMENTATIONS,
)

CATALOG_PATH = ROOT / "backend" / "chatbi" / "catalogs" / "ecommerce_mock_semantics.json"
_ID_PATTERN = r"^[a-z][a-z0-9_]*$"
_SEMVER_PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"


class CatalogLoadError(ValueError):
    """Safe error with a configuration path and stable reason code."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class MetricDefinition(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    label: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    allowed_dimension_ids: tuple[str, ...] = ()
    implementation_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    status: Literal["active", "inactive", "unsupported"]


class DimensionDefinition(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    label: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    allowed_metric_ids: tuple[str, ...] = ()
    field_refs: tuple[str, ...] = ()
    implementation_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    status: Literal["active", "inactive"]


class RelationshipDefinition(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    from_ref: str = Field(min_length=1)
    to_ref: str = Field(min_length=1)
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    aggregation_rule: str = Field(min_length=1)


class TermDefinition(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    text: str = Field(min_length=1)
    resolution: Literal["metric", "dimension", "ambiguous", "unsupported"]
    target_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    candidate_ids: tuple[str, ...] = ()
    note: str = Field(min_length=1)


class CatalogPolicies(_FrozenModel):
    valid_order_statuses: tuple[str, ...] = Field(min_length=1)
    paid_at_required: bool
    sales_amount_basis: str = Field(min_length=1)
    order_count_basis: str = Field(min_length=1)
    category_order_count_basis: str = Field(min_length=1)
    timezone: Literal["Asia/Shanghai"]
    time_interval: Literal["half_open"]
    reference_date_source: Literal["dataset_manifest.as_of_date"]
    dataset_window_source: Literal["dataset_manifest.date_window"]
    week_start_day: int = Field(ge=0, le=6)


class CapabilityDefinition(_FrozenModel):
    id: str = Field(pattern=r"^uq\d{2}$")
    description: str = Field(min_length=1)
    requires_explicit_time_range: bool
    requires_comparison_period: bool
    metric_ids: tuple[str, ...] = ()
    dimension_ids: tuple[str, ...] = ()
    template_id: str = Field(pattern=_ID_PATTERN)


class SemanticCatalog(_FrozenModel):
    schema_version: Literal["1"]
    catalog_id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(pattern=_SEMVER_PATTERN)
    status: Literal["active", "inactive"]
    dataset_id: str = Field(pattern=_ID_PATTERN)
    timezone: Literal["Asia/Shanghai"]
    change_note: str = Field(min_length=1)
    metrics: tuple[MetricDefinition, ...] = Field(min_length=1)
    dimensions: tuple[DimensionDefinition, ...] = Field(min_length=1)
    relationships: tuple[RelationshipDefinition, ...] = ()
    terms: tuple[TermDefinition, ...] = ()
    policies: CatalogPolicies
    capabilities: tuple[CapabilityDefinition, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class SemanticCatalogSnapshot:
    catalog: SemanticCatalog
    dataset_version: str
    dataset_start_date: date
    dataset_end_exclusive: date
    as_of_date: date


def _fail(path: str, reason: str) -> NoReturn:
    raise CatalogLoadError(f"{path}: {reason}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogLoadError("$json: duplicate_object_key")
        result[key] = value
    return result


def _error_path(location: tuple[object, ...]) -> str:
    parts = [str(part) for part in location]
    return ".".join(parts) if parts else "$"


def _normalize_alias(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _parse_manifest_dates(manifest: dict[str, object]) -> tuple[date, date, date, str]:
    dataset_id = manifest.get("dataset_id")
    if not isinstance(dataset_id, str):
        _fail("manifest.dataset_id", "string_required")
    dataset_version = manifest.get("version")
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        _fail("manifest.version", "non_empty_string_required")
    as_of_raw = manifest.get("as_of_date")
    timezone = manifest.get("timezone")
    date_window = manifest.get("date_window")
    if not isinstance(as_of_raw, str):
        _fail("manifest.as_of_date", "string_required")
    if not isinstance(timezone, str):
        _fail("manifest.timezone", "string_required")
    if not isinstance(date_window, dict):
        _fail("manifest.date_window", "object_required")
    start_raw = date_window.get("start_inclusive")
    end_raw = date_window.get("end_exclusive")
    if not isinstance(start_raw, str):
        _fail("manifest.date_window.start_inclusive", "string_required")
    if not isinstance(end_raw, str):
        _fail("manifest.date_window.end_exclusive", "string_required")
    try:
        as_of = date.fromisoformat(as_of_raw)
        start = date.fromisoformat(start_raw)
        end = date.fromisoformat(end_raw)
    except ValueError as error:
        _fail("manifest.date_window", "invalid_iso_date")
        raise AssertionError from error
    if start >= end or end != as_of:
        _fail("manifest.date_window", "inconsistent_date_bounds")
    return start, end, as_of, dataset_version


def validate_catalog(
    catalog: SemanticCatalog,
    manifest: dict[str, object],
) -> tuple[date, date, date, str]:
    """Validate cross references, dataset compatibility, and code-owned capability gates."""
    start, end, as_of, dataset_version = _parse_manifest_dates(manifest)
    if catalog.status != "active":
        _fail("status", "active_catalog_required")
    if catalog.dataset_id != manifest.get("dataset_id"):
        _fail("dataset_id", "manifest_dataset_mismatch")
    if catalog.timezone != manifest.get("timezone"):
        _fail("timezone", "manifest_timezone_mismatch")
    if catalog.policies.timezone != catalog.timezone:
        _fail("policies.timezone", "catalog_timezone_mismatch")
    if catalog.policies.week_start_day != 1:
        _fail("policies.week_start_day", "p3_requires_monday")
    manifest_statuses = manifest.get("valid_order_statuses")
    if not isinstance(manifest_statuses, list) or not all(
        isinstance(status, str) for status in manifest_statuses
    ):
        _fail("manifest.valid_order_statuses", "string_list_required")
    if set(catalog.policies.valid_order_statuses) != set(manifest_statuses):
        _fail("policies.valid_order_statuses", "manifest_status_mismatch")

    entity_ids: dict[str, str] = {}
    metrics = {item.id: item for item in catalog.metrics}
    dimensions = {item.id: item for item in catalog.dimensions}
    all_ids = (
        ("metrics", tuple(item.id for item in catalog.metrics)),
        ("dimensions", tuple(item.id for item in catalog.dimensions)),
        ("relationships", tuple(item.id for item in catalog.relationships)),
        ("terms", tuple(item.id for item in catalog.terms)),
        ("capabilities", tuple(item.id for item in catalog.capabilities)),
    )
    for section, item_ids in all_ids:
        for index, item_id in enumerate(item_ids):
            if item_id in entity_ids:
                _fail(f"{section}[{index}].id", "duplicate_global_id")
            entity_ids[item_id] = section

    for index, metric in enumerate(catalog.metrics):
        path = f"metrics[{index}]"
        if metric.status == "active":
            if metric.implementation_id not in SUPPORTED_METRIC_IMPLEMENTATIONS:
                _fail(f"{path}.implementation_id", "metric_implementation_not_allowlisted")
        elif metric.implementation_id is not None:
            _fail(f"{path}.implementation_id", "inactive_metric_has_implementation")
        for dimension_id in metric.allowed_dimension_ids:
            target = dimensions.get(dimension_id)
            if target is None:
                _fail(f"{path}.allowed_dimension_ids", "unknown_or_inactive_dimension")
            if target.status != "active":
                _fail(f"{path}.allowed_dimension_ids", "unknown_or_inactive_dimension")
            if metric.id not in target.allowed_metric_ids:
                _fail(f"{path}.allowed_dimension_ids", "dimension_metric_reference_mismatch")

    for index, dimension in enumerate(catalog.dimensions):
        path = f"dimensions[{index}]"
        if dimension.status == "active":
            if dimension.implementation_id not in SUPPORTED_DIMENSION_IMPLEMENTATIONS:
                _fail(f"{path}.implementation_id", "dimension_implementation_not_allowlisted")
            if not dimension.field_refs:
                _fail(f"{path}.field_refs", "active_dimension_requires_field_ref")
        elif dimension.implementation_id is not None:
            _fail(f"{path}.implementation_id", "inactive_dimension_has_implementation")
        if any(field_ref not in SUPPORTED_FIELD_REFS for field_ref in dimension.field_refs):
            _fail(f"{path}.field_refs", "field_ref_not_allowlisted")
        for metric_id in dimension.allowed_metric_ids:
            metric_target = metrics.get(metric_id)
            if metric_target is None:
                _fail(f"{path}.allowed_metric_ids", "unknown_or_inactive_metric")
            if metric_target.status != "active":
                _fail(f"{path}.allowed_metric_ids", "unknown_or_inactive_metric")

    for index, relationship in enumerate(catalog.relationships):
        path = f"relationships[{index}]"
        if relationship.from_ref not in SUPPORTED_FIELD_REFS:
            _fail(f"{path}.from_ref", "field_ref_not_allowlisted")
        if relationship.to_ref not in SUPPORTED_FIELD_REFS:
            _fail(f"{path}.to_ref", "field_ref_not_allowlisted")

    for index, term in enumerate(catalog.terms):
        path = f"terms[{index}]"
        target_id = term.target_id
        if term.resolution == "metric":
            if target_id not in metrics or term.candidate_ids:
                _fail(path, "invalid_metric_term_target")
        elif term.resolution == "dimension":
            if target_id not in dimensions or term.candidate_ids:
                _fail(path, "invalid_dimension_term_target")
        elif term.resolution == "unsupported":
            if target_id not in entity_ids or term.candidate_ids:
                _fail(path, "invalid_unsupported_term_target")
            target_metric = metrics.get(target_id or "")
            if target_metric is not None and target_metric.status == "active":
                _fail(f"{path}.target_id", "unsupported_term_targets_active_metric")
        elif target_id is not None:
            _fail(f"{path}.target_id", "ambiguous_term_must_not_have_target")
        for candidate_id in term.candidate_ids:
            if candidate_id not in metrics and candidate_id not in dimensions:
                _fail(f"{path}.candidate_ids", "unknown_candidate")

    alias_targets: dict[str, str] = {}

    def register_aliases(
        section: str,
        entries: Sequence[MetricDefinition | DimensionDefinition],
    ) -> None:
        for index, item in enumerate(entries):
            if item.status != "active":
                continue
            for value_index, value in enumerate((item.label, *item.aliases)):
                normalized = _normalize_alias(value)
                previous = alias_targets.get(normalized)
                if previous is not None and previous != item.id:
                    _fail(f"{section}[{index}].aliases[{value_index}]", "alias_collision")
                alias_targets[normalized] = item.id

    register_aliases("metrics", catalog.metrics)
    register_aliases("dimensions", catalog.dimensions)

    term_ids: set[str] = set()
    for index, term in enumerate(catalog.terms):
        normalized = _normalize_alias(term.text)
        if normalized in term_ids:
            _fail(f"terms[{index}].text", "duplicate_term")
        term_ids.add(normalized)
        existing_target = alias_targets.get(normalized)
        if term.resolution in {"ambiguous", "unsupported"} and existing_target is not None:
            _fail(f"terms[{index}].text", "term_conflicts_with_active_alias")
        if term.resolution in {"metric", "dimension"}:
            assert term.target_id is not None
            previous = alias_targets.get(normalized)
            if previous is not None and previous != term.target_id:
                _fail(f"terms[{index}].text", "alias_collision")
            alias_targets[normalized] = term.target_id

    code_capability_ids = set(SUPPORTED_CAPABILITIES)
    config_capabilities = {item.id: item for item in catalog.capabilities}
    if set(config_capabilities) != code_capability_ids:
        _fail("capabilities", "code_capability_set_mismatch")
    for index, capability in enumerate(catalog.capabilities):
        path = f"capabilities[{index}]"
        registered = SUPPORTED_CAPABILITIES.get(capability.id)
        if registered is None:
            _fail(f"{path}.id", "capability_not_allowlisted")
        if capability.template_id != registered.template_id:
            _fail(f"{path}.template_id", "template_mapping_mismatch")
        if set(capability.metric_ids) != registered.metric_ids:
            _fail(f"{path}.metric_ids", "metric_mapping_mismatch")
        if set(capability.dimension_ids) != registered.dimension_ids:
            _fail(f"{path}.dimension_ids", "dimension_mapping_mismatch")
        for metric_id in capability.metric_ids:
            if metric_id not in metrics or metrics[metric_id].status != "active":
                _fail(f"{path}.metric_ids", "unknown_or_inactive_metric")
        for dimension_id in capability.dimension_ids:
            if dimension_id not in dimensions or dimensions[dimension_id].status != "active":
                _fail(f"{path}.dimension_ids", "unknown_or_inactive_dimension")
            if any(
                metric_id not in dimensions[dimension_id].allowed_metric_ids
                for metric_id in capability.metric_ids
            ):
                _fail(f"{path}.dimension_ids", "metric_dimension_incompatible")

    return start, end, as_of, dataset_version


def _read_json(path: Path) -> object:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CatalogLoadError(f"{path}: file_unavailable") from error
    try:
        return json.loads(content, object_pairs_hook=_reject_duplicate_json_keys)
    except CatalogLoadError:
        raise
    except json.JSONDecodeError as error:
        raise CatalogLoadError(
            f"{path}: invalid_json_line_{error.lineno}_column_{error.colno}"
        ) from error
    except ValueError as error:
        raise CatalogLoadError(f"{path}: invalid_json_value") from error


def _tuple_json_arrays(value: object) -> object:
    """Keep JSON array syntax while satisfying strict immutable tuple fields."""
    if isinstance(value, list):
        return tuple(_tuple_json_arrays(item) for item in value)
    if isinstance(value, dict):
        return {key: _tuple_json_arrays(item) for key, item in value.items()}
    return value


def load_catalog(
    catalog_path: Path = CATALOG_PATH,
    manifest_path: Path | None = None,
) -> SemanticCatalogSnapshot:
    """Load, cross-validate, and freeze one catalog snapshot."""
    raw_catalog = _read_json(catalog_path)
    try:
        catalog = SemanticCatalog.model_validate(_tuple_json_arrays(raw_catalog))
    except ValidationError as error:
        locations = [
            f"{_error_path(tuple(issue['loc']))}:{issue['type']}" for issue in error.errors()[:8]
        ]
        raise CatalogLoadError(f"{catalog_path}: schema_invalid: {'; '.join(locations)}") from error

    actual_manifest_path = manifest_path or (
        ROOT / "data" / "generated" / catalog.dataset_id / "manifest.json"
    )
    raw_manifest = _read_json(actual_manifest_path)
    if not isinstance(raw_manifest, dict):
        _fail("manifest", "object_required")
    try:
        start, end, as_of, dataset_version = validate_catalog(catalog, raw_manifest)
    except CatalogLoadError as error:
        raise CatalogLoadError(f"{catalog_path}: {error}") from error
    return SemanticCatalogSnapshot(
        catalog=catalog,
        dataset_version=dataset_version,
        dataset_start_date=start,
        dataset_end_exclusive=end,
        as_of_date=as_of,
    )


# Imported with the application service so an invalid catalog prevents service startup.
ACTIVE_CATALOG = load_catalog()


def main() -> int:
    """Validate the active catalog and print a concise, non-sensitive summary."""
    catalog = ACTIVE_CATALOG.catalog
    print(
        f"Valid semantic catalog {catalog.catalog_id}@{catalog.version} "
        f"for dataset {catalog.dataset_id}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
