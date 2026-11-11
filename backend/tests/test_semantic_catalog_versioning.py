from __future__ import annotations

import pytest
from backend.chatbi.catalog_versioning import (
    CatalogVersionError,
    validate_version_transition,
)
from backend.chatbi.semantic_catalog import ACTIVE_CATALOG, CATALOG_PATH, load_catalog


def _catalog_with(**updates):
    catalog = ACTIVE_CATALOG.catalog
    return catalog.model_copy(update=updates)


def test_additive_alias_requires_minor_version_bump() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.metrics[0]
    current = _catalog_with(
        version="0.2.0",
        change_note="Add approved alias",
        metrics=(first.model_copy(update={"aliases": (*first.aliases, "成交总额")}),)
        + previous.metrics[1:],
    )

    assert validate_version_transition(previous, current) == "minor"


def test_copy_only_change_requires_patch_version_bump() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.capabilities[0]
    current = _catalog_with(
        version="0.1.5",
        change_note="Clarify capability text",
        capabilities=(first.model_copy(update={"description": "昨日销售额和订单数"}),)
        + previous.capabilities[1:],
    )

    assert validate_version_transition(previous, current) == "patch"


def test_metric_definition_change_requires_major_bump() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.metrics[0]
    current = _catalog_with(
        version="0.2.0",
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
        version="1.0.0",
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
    current = _catalog_with(version="0.1.5")

    with pytest.raises(CatalogVersionError, match="catalog_content_unchanged"):
        validate_version_transition(previous, current)


def test_catalog_change_requires_a_change_note() -> None:
    previous = ACTIVE_CATALOG.catalog
    first = previous.capabilities[0]
    current = _catalog_with(
        version="0.1.5",
        capabilities=(first.model_copy(update={"description": "Changed description"}),)
        + previous.capabilities[1:],
    )

    with pytest.raises(CatalogVersionError, match="change_note_must_describe_transition"):
        validate_version_transition(previous, current)


def test_archived_release_is_loadable_for_rollback() -> None:
    previous_path = CATALOG_PATH.parent / "releases" / "ecommerce_mock_semantics_0.1.3.json"
    previous = load_catalog(previous_path)

    assert previous.catalog.version == "0.1.3"
    assert previous.dataset_version == ACTIVE_CATALOG.dataset_version
    assert validate_version_transition(previous.catalog, ACTIVE_CATALOG.catalog) == "patch"
