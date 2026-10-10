"""Versioned TAL mobile-profile fixtures and canonicalization helpers.

This module is deliberately dependency-free so the Python simulator can remain the
conformance oracle for Android and later shared-core implementations.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MOBILE_PROFILE_DIR = REPOSITORY_ROOT / "contracts" / "mobile-profile"
MOBILE_FIXTURE_DIR = REPOSITORY_ROOT / "fixtures" / "mobile"

MANIFEST_REQUIRED_FIELDS = frozenset(
    {
        "tal_version",
        "grammar_id",
        "schema_id",
        "domain_pack",
        "request",
        "scope",
        "goal",
        "unknowns",
        "requirements",
        "constraints",
        "requested_capabilities",
        "prohibited_actions",
        "success_conditions",
        "fallbacks",
        "output_contract",
        "integrity",
    }
)
MANIFEST_OPTIONAL_FIELDS = frozenset({"reported_facts", "preferences"})
INTEGRITY_FIELDS = frozenset(
    {"canonicalization", "compiler_version", "manifest_version", "manifest_hash"}
)


class MobileProfileValidationError(ValueError):
    """Raised when a mobile profile artifact violates a closed contract."""


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise MobileProfileValidationError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def load_strict_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise MobileProfileValidationError(f"Unable to load JSON artifact {path}") from exc


def _reject_floating_values(value: Any) -> None:
    if isinstance(value, float):
        raise MobileProfileValidationError("Floating-point values are not permitted in mobile canonical JSON")
    if isinstance(value, dict):
        for child in value.values():
            _reject_floating_values(child)
    elif isinstance(value, list):
        for child in value:
            _reject_floating_values(child)


def canonical_json(value: Any) -> str:
    """Return `tal-json-c14n-0.2` JSON text for supported profile values."""
    _reject_floating_values(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MobileProfileValidationError("Value is not canonical JSON") from exc


def manifest_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Copy a manifest and remove only its self-referential integrity hash."""
    if not isinstance(manifest, dict):
        raise MobileProfileValidationError("Manifest must be a JSON object")
    contract = copy.deepcopy(manifest)
    integrity = contract.get("integrity")
    if not isinstance(integrity, dict):
        raise MobileProfileValidationError("Manifest integrity must be an object")
    integrity.pop("manifest_hash", None)
    return contract


def manifest_hash(manifest: dict[str, Any]) -> str:
    canonical = canonical_json(manifest_contract(manifest))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def validate_manifest_shape(manifest: dict[str, Any]) -> None:
    """Validate immutable top-level profile invariants before schema-level validation."""
    if not isinstance(manifest, dict):
        raise MobileProfileValidationError("Manifest must be an object")
    present = frozenset(manifest)
    missing = MANIFEST_REQUIRED_FIELDS - present
    unexpected = present - MANIFEST_REQUIRED_FIELDS - MANIFEST_OPTIONAL_FIELDS
    if missing:
        raise MobileProfileValidationError(f"Manifest is missing required fields: {sorted(missing)}")
    if unexpected:
        raise MobileProfileValidationError(f"Manifest contains unknown fields: {sorted(unexpected)}")
    expected_versions = {
        "tal_version": "0.3.0",
        "grammar_id": "tal-core-0.3.0",
        "schema_id": "tal-manifest-0.3.0",
        "domain_pack": "tal.mobile.private_assistant-0.1.0",
    }
    for name, expected in expected_versions.items():
        if manifest.get(name) != expected:
            raise MobileProfileValidationError(f"Unsupported {name}: {manifest.get(name)!r}")
    integrity = manifest["integrity"]
    if not isinstance(integrity, dict):
        raise MobileProfileValidationError("Manifest integrity must be an object")
    if frozenset(integrity) != INTEGRITY_FIELDS:
        raise MobileProfileValidationError("Manifest integrity must use the fixed integrity field set")
    if integrity["canonicalization"] != "tal-json-c14n-0.2":
        raise MobileProfileValidationError("Unsupported canonicalization")
    if integrity["compiler_version"] != "tal-mobile-compiler-0.1.0":
        raise MobileProfileValidationError("Unsupported compiler version")
    if integrity["manifest_version"] != 1:
        raise MobileProfileValidationError("Unsupported manifest version")
    computed = manifest_hash(manifest)
    stored = integrity["manifest_hash"]
    if stored != computed:
        raise MobileProfileValidationError("Manifest hash does not match canonical contract")


def golden_manifest_records() -> list[dict[str, Any]]:
    index = load_strict_json(MOBILE_FIXTURE_DIR / "golden-manifests.json")
    if not isinstance(index, dict) or index.get("suite_id") != "tal-mobile-conformance-0.1.0":
        raise MobileProfileValidationError("Invalid mobile golden fixture index")
    records = index.get("fixtures")
    if not isinstance(records, list) or not records:
        raise MobileProfileValidationError("Golden fixture index is empty")
    return records


def assert_golden_manifests() -> None:
    """Check the frozen canonical bytes and digest for every checked-in golden manifest."""
    for record in golden_manifest_records():
        if not isinstance(record, dict):
            raise MobileProfileValidationError("Golden fixture record must be an object")
        fixture_name = record.get("manifest_file")
        if not isinstance(fixture_name, str) or not fixture_name:
            raise MobileProfileValidationError("Golden fixture is missing manifest_file")
        manifest = load_strict_json(MOBILE_FIXTURE_DIR / fixture_name)
        if not isinstance(manifest, dict):
            raise MobileProfileValidationError("Golden manifest must be an object")
        canonical = canonical_json(manifest_contract(manifest))
        digest = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        if record.get("expected_canonical") != canonical:
            raise MobileProfileValidationError(f"Canonical bytes drifted for {fixture_name}")
        if record.get("expected_sha256") != digest:
            raise MobileProfileValidationError(f"Digest drifted for {fixture_name}")
        validate_manifest_shape(manifest)
