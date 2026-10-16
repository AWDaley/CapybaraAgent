import hashlib
import json

import pytest

from scripts.sign_mobile_model_package import (
    canonical_unsigned_bytes,
    hash_model_file,
    prepare_unsigned_metadata,
)


def metadata():
    return {
        "package_id": "package:sample",
        "publisher_id": "tervoro",
        "model_profile_id": "mobile-v1",
        "model_version": "1",
        "quantization": "int4",
        "tokenizer_hash": "sha256:" + "b" * 64,
        "runtime_id": "litert",
        "prompt_profile_id": "tal-mobile-v1",
        "certification_id": "demo-not-certified",
        "minimum_android_api": 28,
        "supported_abis": ["x86_64", "arm64-v8a"],
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
        "revoked": False,
    }


def test_offline_package_signer_uses_real_binary_digest_and_sorted_json(tmp_path):
    binary = tmp_path / "test.litertlm"
    binary.write_bytes(b"not a real model")
    digest = hash_model_file(binary)
    assert digest == hashlib.sha256(b"not a real model").hexdigest()
    value = prepare_unsigned_metadata(metadata(), digest)
    assert value["artifact_hash"] == "sha256:" + digest
    assert value["supported_abis"] == ["arm64-v8a", "x86_64"]
    canonical = canonical_unsigned_bytes(value)
    assert canonical == json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    assert b" \"" not in canonical


@pytest.mark.parametrize("change", [
    {"publisher_id": "untrusted"},
    {"prompt_profile_id": "wrong"},
    {"revoked": "false"},
    {"tokenizer_hash": "not sha256"},
    {"minimum_android_api": True},
    {"supported_abis": ["arm64-v8a", "arm64-v8a"]},
    {"issued_at": "2026-01-01"},
    {"unknown_field": "injected"},
    {"artifact_hash": "sha256:" + "a" * 64},
])
def test_offline_signer_rejects_incompatible_or_misleading_metadata(change):
    candidate = metadata()
    candidate.update(change)
    with pytest.raises(ValueError):
        prepare_unsigned_metadata(candidate, "0" * 64)
