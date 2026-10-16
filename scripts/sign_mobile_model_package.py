"""Offline packager for Tervoro's P-256 signed LiteRT-LM model descriptors.

Private keys are read only by the trusted local OpenSSL process; never commit
private keys, Gradle release secrets, or production model signing material.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

MODEL_KEYS = frozenset({
    "artifact_hash", "certification_id", "expires_at", "issued_at",
    "minimum_android_api", "model_profile_id", "model_version",
    "package_id", "prompt_profile_id", "publisher_id", "quantization",
    "revoked", "runtime_id", "supported_abis", "tokenizer_hash",
})
HEX_DIGEST = re.compile(r"sha256:[0-9a-f]{64}$")
SIMPLE_ID = re.compile(r"[-a-zA-Z0-9._:]{1,128}$")
UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


def hash_model_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def prepare_unsigned_metadata(metadata: dict[str, Any], model_hash: str) -> dict[str, Any]:
    """Validate the exact signed fields and derive the digest from actual bytes."""
    if type(metadata) is not dict or set(metadata) - MODEL_KEYS:
        raise ValueError("Unknown or malformed signed model descriptor field")
    result = dict(metadata)
    expected_hash = "sha256:" + model_hash
    if result.get("artifact_hash", expected_hash) != expected_hash:
        raise ValueError("Descriptor artifact digest differs from model bytes")
    result["artifact_hash"] = expected_hash
    if set(result) != MODEL_KEYS:
        raise ValueError("Descriptor is missing mandatory signed fields")
    for key in MODEL_KEYS - {"artifact_hash", "tokenizer_hash", "minimum_android_api",
                             "supported_abis", "issued_at", "expires_at", "revoked"}:
        if type(result[key]) is not str or not SIMPLE_ID.fullmatch(result[key]):
            raise ValueError(f"Invalid signed identifier: {key}")
    if result["publisher_id"] != "tervoro" or result["runtime_id"] != "litert":
        raise ValueError("Unsupported publisher or runtime")
    if result["prompt_profile_id"] != "tal-mobile-v1":
        raise ValueError("The signed prompt profile does not match the TAL mobile runtime")
    if not HEX_DIGEST.fullmatch(result["tokenizer_hash"]):
        raise ValueError("tokenizer_hash must be sha256:<64 lowercase hex>")
    if type(result["minimum_android_api"]) is not int or result["minimum_android_api"] < 28:
        raise ValueError("minimum_android_api must be an integer of at least 28")
    abis = result["supported_abis"]
    if (type(abis) is not list or not 1 <= len(abis) <= 12 or
            any(type(a) is not str or not SIMPLE_ID.fullmatch(a) for a in abis) or
            len(set(abis)) != len(abis)):
        raise ValueError("Invalid supported_abis list")
    result["supported_abis"] = sorted(abis)
    if type(result["revoked"]) is not bool:
        raise ValueError("revoked must be boolean")
    if any(type(result[key]) is not str or not UTC_TIMESTAMP.fullmatch(result[key])
           for key in ("issued_at", "expires_at")):
        raise ValueError("Dates must use canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    return result


def canonical_unsigned_bytes(fields: dict[str, Any]) -> bytes:
    """Matches Kotlin ModelPackageDescriptor.canonicalUnsignedPayload for safe metadata."""
    return json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"Duplicate signed metadata field: {key}")
        data[key] = value
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign one vetted mobile model package")
    parser.add_argument("--model", type=Path, required=True, help="Actual .litertlm model binary")
    parser.add_argument("--metadata", type=Path, required=True, help="Unsigned metadata JSON")
    parser.add_argument("--key", type=Path, required=True, help="Offline P-256 PEM private key")
    parser.add_argument("--output", type=Path, required=True, help="Signed descriptor output JSON")
    args = parser.parse_args()

    if args.model.suffix.lower() != ".litertlm":
        parser.error("Model must use the .litertlm extension")
    metadata = json.loads(
        args.metadata.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    fields = prepare_unsigned_metadata(metadata, hash_model_file(args.model))
    payload = canonical_unsigned_bytes(fields)

    signed = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(args.key)],
        input=payload, capture_output=True, check=True, timeout=30,
    ).stdout
    public_der = subprocess.run(
        ["openssl", "pkey", "-in", str(args.key), "-pubout", "-outform", "DER"],
        capture_output=True, check=True, timeout=30,
    ).stdout
    encoded = dict(fields)
    encoded["signature"] = base64.b64encode(signed).decode("ascii")
    descriptor = json.dumps(encoded, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    args.output.write_text(descriptor, encoding="utf-8")

    print("Signed descriptor written:", args.output)
    print("Model SHA-256:", fields["artifact_hash"])
    print("Gradle tervoroSignedModelDescriptorBase64=" +
          base64.b64encode(descriptor.encode("utf-8")).decode("ascii"))
    print("Gradle tervoroTrustedPublisherSpkiBase64=" +
          base64.b64encode(public_der).decode("ascii"))


if __name__ == "__main__":
    main()
