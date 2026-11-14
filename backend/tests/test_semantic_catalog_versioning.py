from __future__ import annotations

import json

import pytest
from backend.chatbi.catalog_versioning import (
    CatalogVersionError,
    validate_version_transition,
)
from backend.chatbi.semantic_catalog import (
    ACTIVE_CATALOG,
    CATALOG_PATH,
    SemanticCatalog,
    _tuple_json_arrays,
)


def _catalog_with(**updates):
    catalog = ACTIVE_CATALOG.catalog
    return catalog.model_copy(update=updates)


def test_additive_alias_requires_minor_version_bump() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.metrics[0]
    current = _catalog_with(
        version="1.2.0",
        change_note="Add approved alias",
        metrics=(first.model_copy(update={"aliases": (*first.aliases, "成交总额")}),)
        + previous.metrics[1:],
    )

    assert validate_version_transition(previous, current) == "minor"


def test_copy_only_change_requires_patch_version_bump() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.capabilities[0]
    current = _catalog_with(
        version="1.1.1",
        change_note="Clarify capability text",
        capabilities=(first.model_copy(update={"description": "昨日销售额和订单数"}),)
        + previous.capabilities[1:],
    )

    assert validate_version_transition(previous, current) == "patch"


def test_metric_definition_change_requires_major_bump() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.metrics[0]
    current = _catalog_with(
        version="1.2.0",
        change_note="Change sales definition",
        metrics=(first.model_copy(update={"definition": "Changed metric meaning"}),)
        + previous.metrics[1:],
    )

    with pytest.raises(CatalogVersionError, match="major_change_requires_matching_version_bump"):
        validate_version_transition(previous, current)


def test_metric_definition_change_accepts_major_bump() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.metrics[0]
    current = _catalog_with(
        version="2.0.0",
        change_note="Change sales definition",
        metrics=(first.model_copy(update={"definition": "Changed metric meaning"}),)
        + previous.metrics[1:],
    )

    assert validate_version_transition(previous, current) == "major"


def test_version_must_change_when_catalog_content_changes() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.metrics[0]
    current = _catalog_with(
        metrics=(first.model_copy(update={"label": "店铺销售额"}),) + previous.metrics[1:]
    )

    with pytest.raises(CatalogVersionError, match="catalog_version_must_increase"):
        validate_version_transition(previous, current)


def test_version_bump_without_catalog_change_is_rejected() -> None:
    previous = ACTIVE_CATALOG.catalog
    current = _catalog_with(version="1.1.1")

    with pytest.raises(CatalogVersionError, match="catalog_content_unchanged"):
        validate_version_transition(previous, current)


def test_catalog_change_requires_a_change_note() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.capabilities[0]
    current = _catalog_with(
        version="1.1.1",
        capabilities=(first.model_copy(update={"description": "Changed description"}),)
        + previous.capabilities[1:],
    )

    with pytest.raises(CatalogVersionError, match="change_note_must_describe_transition"):
        validate_version_transition(previous, current)


def test_archived_release_records_the_prior_major_transition() -> None:
    previous_path = CATALOG_PATH.parent / "releases" / "ecommerce_mock_semantics_0.1.4.json"
    previous = SemanticCatalog.model_validate(
        _tuple_json_arrays(json.loads(previous_path.read_text(encoding="utf-8")))
    )

    assert previous.version == "0.1.4"
    assert "uq07" not in {capability.id for capability in previous.capabilities}
    assert validate_version_transition(previous, ACTIVE_CATALOG.catalog) == "major"
