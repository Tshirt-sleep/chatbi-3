"""Validate semantic catalog version transitions before review or release."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .semantic_catalog import SemanticCatalog, _tuple_json_arrays


class CatalogVersionError(ValueError):
    """Raised when a catalog change does not follow the versioning policy."""


_PATCH_TEXT_FIELDS = {"label", "description", "note", "change_note"}


def _projection(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _projection(item)
            for key, item in value.items()
            if key not in {*_PATCH_TEXT_FIELDS, "aliases", "version", "terms"}
        }
    if isinstance(value, list):
        return [_projection(item) for item in value]
    return value


def _aliases_are_additive(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    for collection in ("metrics", "dimensions"):
        previous_items = {item["id"]: item for item in previous[collection]}
        current_items = {item["id"]: item for item in current[collection]}
        if not previous_items.keys() <= current_items.keys():
            return False
        for item_id, old_item in previous_items.items():
            if not set(old_item.get("aliases", ())) <= set(
                current_items[item_id].get("aliases", ())
            ):
                return False
    return True


def _change_kind(previous: SemanticCatalog, current: SemanticCatalog) -> str:
    old = previous.model_dump(mode="json")
    new = current.model_dump(mode="json")
    old_without_version = {key: value for key, value in old.items() if key != "version"}
    new_without_version = {key: value for key, value in new.items() if key != "version"}
    if old_without_version == new_without_version:
        raise CatalogVersionError("catalog_content_unchanged")
    if _projection(old) != _projection(new):
        return "major"
    if not _aliases_are_additive(old, new):
        return "major"
    old_terms = {item["id"]: item for item in old["terms"]}
    new_terms = {item["id"]: item for item in new["terms"]}
    if not old_terms.keys() <= new_terms.keys():
        return "major"
    if any(_projection(old_terms[key]) != _projection(new_terms[key]) for key in old_terms):
        return "major"
    if new_terms.keys() - old_terms.keys():
        return "minor"
    for collection in ("metrics", "dimensions"):
        old_items = {item["id"]: item for item in old[collection]}
        new_items = {item["id"]: item for item in new[collection]}
        if old_items.keys() != new_items.keys():
            return "major"
        for item_id, old_item in old_items.items():
            if set(old_item.get("aliases", ())) != set(new_items[item_id].get("aliases", ())):
                return "minor"
    return "patch"


def validate_version_transition(previous: SemanticCatalog, current: SemanticCatalog) -> str:
    """Check that content changes use the matching major/minor/patch lane."""
    old = tuple(int(part) for part in previous.version.split("."))
    new = tuple(int(part) for part in current.version.split("."))
    if new <= old:
        raise CatalogVersionError("catalog_version_must_increase")
    change_kind = _change_kind(previous, current)
    if previous.change_note == current.change_note:
        raise CatalogVersionError("change_note_must_describe_transition")
    valid_bump = {
        "major": new[0] > old[0],
        "minor": new[0] == old[0] and new[1] > old[1],
        "patch": new[0] == old[0] and new[1] == old[1] and new[2] > old[2],
    }[change_kind]
    if not valid_bump:
        raise CatalogVersionError(f"{change_kind}_change_requires_matching_version_bump")
    return change_kind


def _read_catalog(path: Path) -> SemanticCatalog:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SemanticCatalog.model_validate(_tuple_json_arrays(raw))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CatalogVersionError(f"invalid_catalog_file:{path.name}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path, help="previously accepted catalog JSON")
    parser.add_argument("current", type=Path, help="catalog JSON to review")
    args = parser.parse_args()
    previous = _read_catalog(args.previous)
    current = _read_catalog(args.current)
    change_kind = validate_version_transition(previous, current)
    print(
        f"Catalog version transition accepted: {previous.version} -> "
        f"{current.version} ({change_kind})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
