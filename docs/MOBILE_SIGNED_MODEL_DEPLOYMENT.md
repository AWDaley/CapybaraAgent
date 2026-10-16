# Offline signed mobile model packages

CapybaraAndroid already contained a `ModelPackageTrustPolicy` abstraction but
did not call it when importing or activating LiteRT-LM models. The installer now
enforces signed publisher identity in non-debug builds.

## Build-time trust anchors

Set Gradle properties via a trusted release pipeline or local non-versioned
Gradle properties:

- `tervoroSignedModelDescriptorBase64`: Base64 of the **UTF-8 JSON** signed descriptor.
- `tervoroTrustedPublisherSpkiBase64`: Base64 of a Tervoro-controlled P-256
  **X.509 SubjectPublicKeyInfo DER** public key (never a private key).
- `tervoroApprovedModelSha256` (optional): hexadecimal digest for an extra
  narrow allowlist of one binary.

The signed descriptor must include exactly these fields:
`artifact_hash` (format `sha256:<64 lowercase hex>`),
`tokenizer_hash` (same format), `publisher_id` = `tervoro`,
`runtime_id` = `litert`, `prompt_profile_id` = `tal-mobile-v1`,
`package_id`, `model_profile_id`, `model_version`, `quantization`,
`certification_id`, `minimum_android_api`, `supported_abis` (array),
`issued_at` and `expires_at` (ISO 8601 UTC), `revoked` (boolean),
and `signature` (Base64 of SHA256withECDSA/P-256 signature).

The signature covers the canonical unsigned JSON payload produced by
`ModelPackageDescriptor.canonicalUnsignedPayload()`: JSON keys sorted
lexicographically, no spaces, and ABIs sorted. Use an offline signer/test
harness to generate exactly those bytes, then sign with P-256 SHA-256.
A descriptor's `signature` is NOT included in its signed payload.
Rotate/revoke compromised public keys through trusted application updates.
Signing keys and release property values must be protected by access controls
outside the repository.

Model activation fails closed if the signature, digest, API, ABI, expiry,
publisher identity, runtime, or prompt profile is invalid. The trusted key
is embedded in the signed application at build time and cannot be substituted
through user model input. No private key is included.

**What this does NOT prove:** signed metadata alone cannot establish the
model's license compliance, memory fit, prompt-template behavior, or device
certification, even if the signed descriptor claims a certification ID.
Those checks must be backed by issuer review and external validation.
Offline revocation flags embedded in a release cannot catch later revocation;
shipping a trusted application update or signed new policy is necessary.

## Device test gate

CI builds and runs JVM TAL tests, compiles Android instrumentation tests, and
assembles `demoDebug` without device hardware. A release candidate must also
pass the instrumented signed-package test on representative ARM64 phones,
plus manual tests for biometric acceptance, denial, cancelled prompt, timeout,
process death during staged/model rollback, low disk space, encrypted session
restore, and LiteRT GPU/CPU fallback. Verify no INTERNET permission.
Do not treat compilation as physical-device validation.
