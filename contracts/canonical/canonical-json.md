# TAL Canonical JSON 0.2

Canonical JSON is UTF-8 encoded, has no insignificant whitespace, preserves array order, and
orders every object key by Unicode code point. Strings use JSON escaping; booleans are lowercase;
`null` is lowercase; numbers are forbidden from mobile profile fixtures unless represented as an
integer JSON value without exponent notation or leading zeroes.

The mobile profile rejects duplicate object keys before canonicalization. No canonicalizer may
silently discard an unknown property or normalize a value into a different semantic type.

For manifest integrity, remove exactly `integrity.manifest_hash`, canonicalize the remaining
object recursively, encode it as UTF-8, and SHA-256 hash the bytes. The stored representation is
`sha256:` followed by lowercase hexadecimal digest.
