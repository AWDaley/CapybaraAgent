package com.tervoro.tal

import java.security.PublicKey
import java.security.Signature
import java.time.Instant
import java.util.Base64
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Strict parser for signed publisher metadata, not the agent's proposed JSON. */
object SignedModelPackage {
    private val keys = setOf(
        "artifact_hash", "certification_id", "expires_at", "issued_at",
        "minimum_android_api", "model_profile_id", "model_version",
        "package_id", "prompt_profile_id", "publisher_id", "quantization",
        "revoked", "runtime_id", "supported_abis", "tokenizer_hash", "signature",
    )
    private val digest = Regex("sha256:[a-f0-9]{64}")

    fun parse(rawJson: String): ModelPackageDescriptor {
        require(rawJson.length <= 32_768) { "Model descriptor is too large" }
        val obj = StrictJson.parseToJsonElement(rawJson) as? JsonObject
            ?: throw IllegalArgumentException("Signed model descriptor must be an object")
        require(obj.keys == keys) { "Signed descriptor has missing or unknown fields" }

        fun str(key: String): String {
            val value = obj[key] as? JsonPrimitive
            require(value != null && value.isString && value.content.isNotBlank() && value.content.length <= 4096) {
                "Invalid signed field: $key"
            }
            return value.content
        }

        fun integer(key: String): Int {
            val item = obj[key] as? JsonPrimitive
            require(item != null && !item.isString) { "Invalid integer: $key" }
            return item.content.toIntOrNull() ?: throw IllegalArgumentException("Invalid integer: $key")
        }

        val revokedRaw = obj["revoked"] as? JsonPrimitive
        require(revokedRaw != null && !revokedRaw.isString && revokedRaw.content in setOf("true", "false")) {
            "Invalid revoked flag"
        }
        val abisRaw = obj["supported_abis"] as? JsonArray
            ?: throw IllegalArgumentException("supported_abis must be an array")
        val abis = abisRaw.map { value ->
            val item = value as? JsonPrimitive
            require(item != null && item.isString && item.content.isNotBlank()) { "Invalid ABI" }
            item.content
        }
        require(abis.isNotEmpty() && abis.size <= 12 && abis.size == abis.toSet().size) {
            "Invalid supported ABI list"
        }

        val issued = Instant.parse(str("issued_at"))
        val expires = Instant.parse(str("expires_at"))
        val api = integer("minimum_android_api")
        require(api >= 28 && expires.isAfter(issued)) { "Invalid package validity range" }
        val artifact = str("artifact_hash")
        val tokenizer = str("tokenizer_hash")
        require(digest.matches(artifact) && digest.matches(tokenizer)) { "Invalid package hash format" }

        return ModelPackageDescriptor(
            packageId = str("package_id"),
            publisherId = str("publisher_id"),
            artifactHash = artifact,
            modelProfileId = str("model_profile_id"),
            modelVersion = str("model_version"),
            quantization = str("quantization"),
            tokenizerHash = tokenizer,
            runtimeId = str("runtime_id"),
            promptProfileId = str("prompt_profile_id"),
            certificationId = str("certification_id"),
            minimumAndroidApi = api,
            supportedAbis = abis.toSet(),
            issuedAt = issued,
            expiresAt = expires,
            revoked = revokedRaw.content == "true",
            signature = str("signature"),
        )
    }
}

/** Android-supported P-256 / SHA256withECDSA publisher signature verification. */
class P256ModelPackageVerifier(private val trustAnchors: Map<String, PublicKey>) : ModelPackageSignatureVerifier {
    override fun verify(publisherId: String, payload: ByteArray, signature: String): Boolean = runCatching {
        val key = trustAnchors[publisherId] ?: return false
        val verifier = Signature.getInstance("SHA256withECDSA")
        verifier.initVerify(key)
        verifier.update(payload)
        verifier.verify(Base64.getDecoder().decode(signature))
    }.getOrDefault(false)
}
