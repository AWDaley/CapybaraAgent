import json
from pathlib import Path

import pytest

from tal.mobile_profile import (
    MOBILE_FIXTURE_DIR,
    MOBILE_PROFILE_DIR,
    MobileProfileValidationError,
    assert_golden_manifests,
    load_strict_json,
    validate_manifest_shape,
)


def _assert_objects_are_closed(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False, f"{path} is not closed"
        for key, child in value.items():
            _assert_objects_are_closed(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_objects_are_closed(child, f"{path}[{index}]")


def test_profile_artifacts_are_present_and_closed() -> None:
    profile = load_strict_json(MOBILE_PROFILE_DIR / "profile.json")
    catalog = load_strict_json(MOBILE_PROFILE_DIR / "catalog.json")
    errors = load_strict_json(MOBILE_PROFILE_DIR.parent / "errors" / "mobile-error-catalog.json")

    assert profile["profile_id"] == "tal.mobile.secure_assistant-0.1.0"
    assert profile["default_network_mode"] == "local_only"
    assert profile["production_constraints"]["allows_dynamic_extensions"] is False
    assert {entry["tool_id"] for entry in catalog["tools"]} >= {
        "document.selected.read",
        "vault.search",
        "draft.create",
        "note.create",
        "task.create_local",
    }
    assert "UNKNOWN_FIELD" in errors["errors"]
    assert "STALE_STATE_VERSION" in errors["errors"]

    schemas = sorted((MOBILE_PROFILE_DIR / "schemas").glob("*.schema.json"))
    assert len(schemas) >= 10
    for schema_path in schemas:
        schema = load_strict_json(schema_path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        _assert_objects_are_closed(schema, schema_path.name)


def test_golden_manifest_is_hash_stable() -> None:
    assert_golden_manifests()


def test_unknown_manifest_field_fails_closed() -> None:
    manifest = load_strict_json(MOBILE_FIXTURE_DIR / "document-answer-manifest.unknown-field.json")
    with pytest.raises(MobileProfileValidationError, match="unknown fields"):
        validate_manifest_shape(manifest)


def test_fixture_json_has_no_duplicate_keys() -> None:
    paths = sorted(MOBILE_FIXTURE_DIR.glob("*.json"))
    assert paths
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            json.load(handle)
