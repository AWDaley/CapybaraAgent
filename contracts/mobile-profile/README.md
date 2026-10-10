# Tervoro Mobile Profile Contracts

These artifacts define the closed TAL profile used by the Android-first private assistant.
They are normative inputs to the Python simulator, Kotlin implementation, test fixtures, and
future shared core. Runtime code must not invent fields, tools, success conditions, or policy
identifiers outside this directory.

## Version identifiers

- TAL compatibility: `0.3.x`
- Grammar: `tal-core-0.3.0`
- Manifest schema: `tal-manifest-0.3.0`
- Canonical JSON: `tal-json-c14n-0.2`
- Mobile profile: `tal.mobile.secure_assistant-0.1.0`
- Context profile: `tal-mobile-context-0.1.0`
- Policy bundle: `tal-mobile-policy-bundle-0.1.0`
- Tool catalog: `tal-mobile-tools-0.1.0`
- Conformance suite: `tal-mobile-conformance-0.1.0`

## Closed-world rule

Every object described by these schemas has a fixed property set. Unknown properties,
unsupported versions, dynamic metadata, and unregistered extensions are rejected. Registered
maps are represented as arrays of typed records rather than arbitrary JSON objects.

## Manifest integrity

The manifest hash is the SHA-256 digest of the UTF-8 canonical JSON representation of the
manifest after removing only `integrity.manifest_hash`. The serialized hash is prefixed with
`sha256:`. Run bindings are separate immutable records and are not part of the portable manifest.

The canonical format is defined in `../canonical/canonical-json.md`; golden fixtures live in
`../../fixtures/mobile/`.
