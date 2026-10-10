package com.tervoro.tal

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

class MobileProfileValidationException(
    val stableErrorCode: String,
    message: String,
) : IllegalArgumentException(message)

/**
 * The minimal Kotlin enforcement surface for tal.mobile.secure_assistant-0.1.0.
 *
 * Rich schemas live in the checked-in contracts directory. This class keeps the
 * Android runtime fail-closed while the full generated schema bindings are added.
 */
object MobileProfileContract {
    const val PROFILE_ID = "tal.mobile.secure_assistant-0.1.0"
    const val DOMAIN_PACK_ID = "tal.mobile.private_assistant-0.1.0"
    const val TAL_VERSION = "0.3.0"
    const val GRAMMAR_ID = "tal-core-0.3.0"
    const val MANIFEST_SCHEMA_ID = "tal-manifest-0.3.0"
    const val CANONICALIZATION_ID = "tal-json-c14n-0.2"
    const val COMPILER_VERSION = "tal-mobile-compiler-0.1.0"

    private val requiredFields = setOf(
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
    )
    private val optionalFields = setOf("reported_facts", "preferences")
    private val integrityFields = setOf(
        "canonicalization",
        "compiler_version",
        "manifest_version",
        "manifest_hash",
    )

    fun manifestContract(manifest: JsonObject): JsonObject {
        val integrity = manifest["integrity"] as? JsonObject
            ?: throw invalid("MANIFEST_INTEGRITY", "Manifest integrity must be an object")
        return JsonObject(
            manifest.toMutableMap().also { root ->
                root["integrity"] = JsonObject(integrity.toMutableMap().also { it.remove("manifest_hash") })
            },
        )
    }

    fun manifestHash(manifest: JsonObject): String =
        "sha256:${TaskManifest.sha256(CanonicalJson.encode(manifestContract(manifest)).toByteArray(Charsets.UTF_8))}"

    fun validateManifest(manifest: JsonObject) {
        val missing = requiredFields - manifest.keys
        if (missing.isNotEmpty()) throw invalid("UNKNOWN_FIELD", "Manifest is missing fields: ${missing.sorted().joinToString()}")
        val unknown = manifest.keys - requiredFields - optionalFields
        if (unknown.isNotEmpty()) throw invalid("UNKNOWN_FIELD", "Manifest has unknown fields: ${unknown.sorted().joinToString()}")

        requireString(manifest, "tal_version", TAL_VERSION)
        requireString(manifest, "grammar_id", GRAMMAR_ID)
        requireString(manifest, "schema_id", MANIFEST_SCHEMA_ID)
        requireString(manifest, "domain_pack", DOMAIN_PACK_ID)

        val integrity = manifest["integrity"] as? JsonObject
            ?: throw invalid("MANIFEST_INTEGRITY", "Manifest integrity must be an object")
        if (integrity.keys != integrityFields) {
            throw invalid("UNKNOWN_FIELD", "Manifest integrity must use the fixed field set")
        }
        requireString(integrity, "canonicalization", CANONICALIZATION_ID)
        requireString(integrity, "compiler_version", COMPILER_VERSION)
        val version = (integrity["manifest_version"] as? JsonPrimitive)?.content?.toIntOrNull()
        if (version != 1) throw invalid("UNSUPPORTED_VERSION", "Unsupported manifest version")
        val stored = (integrity["manifest_hash"] as? JsonPrimitive)?.content
            ?: throw invalid("MANIFEST_INTEGRITY", "Manifest hash is missing")
        if (stored != manifestHash(manifest)) {
            throw invalid("MANIFEST_INTEGRITY", "Manifest hash does not match canonical contract")
        }
    }

    private fun requireString(objectValue: JsonObject, field: String, expected: String) {
        val actual = (objectValue[field] as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (actual != expected) {
            throw invalid("UNSUPPORTED_VERSION", "Unsupported $field: ${actual.orEmpty()}")
        }
    }

    private fun invalid(code: String, message: String) = MobileProfileValidationException(code, message)
}
