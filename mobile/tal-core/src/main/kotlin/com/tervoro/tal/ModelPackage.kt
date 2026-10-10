package com.tervoro.tal

import java.time.Instant
import java.security.PublicKey
import java.security.Signature
import java.util.Base64
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

data class ModelPackageDescriptor(
    val packageId: String,
    val publisherId: String,
    val artifactHash: String,
    val modelProfileId: String,
    val modelVersion: String,
    val quantization: String,
    val tokenizerHash: String,
    val runtimeId: String,
    val promptProfileId: String,
    val certificationId: String,
    val minimumAndroidApi: Int,
    val supportedAbis: Set<String>,
    val issuedAt: Instant,
    val expiresAt: Instant,
    val revoked: Boolean = false,
    val signature: String,
) {
    fun canonicalUnsignedPayload(): String = CanonicalJson.encode(CanonicalJson.objectOf(
        "artifact_hash" to JsonPrimitive(artifactHash), "certification_id" to JsonPrimitive(certificationId),
        "expires_at" to JsonPrimitive(expiresAt.toString()), "issued_at" to JsonPrimitive(issuedAt.toString()),
        "minimum_android_api" to JsonPrimitive(minimumAndroidApi), "model_profile_id" to JsonPrimitive(modelProfileId),
        "model_version" to JsonPrimitive(modelVersion), "package_id" to JsonPrimitive(packageId), "prompt_profile_id" to JsonPrimitive(promptProfileId),
        "publisher_id" to JsonPrimitive(publisherId), "quantization" to JsonPrimitive(quantization),
        "revoked" to JsonPrimitive(revoked), "runtime_id" to JsonPrimitive(runtimeId),
        "supported_abis" to kotlinx.serialization.json.JsonArray(supportedAbis.sorted().map(::JsonPrimitive)),
        "tokenizer_hash" to JsonPrimitive(tokenizerHash),
    ))
}

fun interface ModelPackageSignatureVerifier { fun verify(publisherId: String, payload: ByteArray, signature: String): Boolean }

/** Production verifier for descriptors signed by a configured publisher trust anchor. */
class Ed25519ModelPackageVerifier(private val trustAnchors: Map<String, PublicKey>) : ModelPackageSignatureVerifier {
    override fun verify(publisherId: String, payload: ByteArray, signature: String): Boolean = runCatching {
        val key = trustAnchors[publisherId] ?: return false
        val verifier = Signature.getInstance("Ed25519")
        verifier.initVerify(key)
        verifier.update(payload)
        verifier.verify(Base64.getDecoder().decode(signature))
    }.getOrDefault(false)
}

class ModelPackageTrustPolicy(
    private val verifier: ModelPackageSignatureVerifier,
    private val expectedRuntimeId: String,
    private val androidApi: Int,
    private val abi: String,
    private val now: () -> Instant = Instant::now,
) {
    fun verify(descriptor: ModelPackageDescriptor, artifactHash: String) {
        fun invalid(code: String, message: String): Nothing = throw MobileRuntimeException(code, message)
        if (descriptor.revoked) invalid("PACKAGE_REVOKED", "Model package is revoked")
        if (now() !in descriptor.issuedAt..descriptor.expiresAt) invalid("PACKAGE_EXPIRED", "Model package is not currently valid")
        if (descriptor.minimumAndroidApi > androidApi || abi !in descriptor.supportedAbis || descriptor.runtimeId != expectedRuntimeId) {
            invalid("PACKAGE_INCOMPATIBLE", "Model package is incompatible with this device/runtime")
        }
        if (descriptor.artifactHash != artifactHash) invalid("PACKAGE_DIGEST_MISMATCH", "Model artifact digest does not match descriptor")
        if (!verifier.verify(descriptor.publisherId, descriptor.canonicalUnsignedPayload().toByteArray(Charsets.UTF_8), descriptor.signature)) {
            invalid("PACKAGE_SIGNATURE_INVALID", "Model package signature is not trusted")
        }
    }
}
