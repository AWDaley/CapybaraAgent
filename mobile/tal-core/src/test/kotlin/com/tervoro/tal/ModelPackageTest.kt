package com.tervoro.tal

import java.time.Instant
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64
import kotlin.test.Test
import kotlin.test.assertFailsWith

class ModelPackageTest {
    private val descriptor = ModelPackageDescriptor(
        "package:demo", "tervoro", "sha256:" + "c".repeat(64), "profile", "1", "int4",
        "sha256:" + "d".repeat(64), "litert", "mobile", "cert", 28, setOf("arm64-v8a"),
        Instant.parse("2026-01-01T00:00:00Z"), Instant.parse("2027-01-01T00:00:00Z"), signature = "test-signature",
    )
    @Test fun `trust policy fails closed for bad signature and digest`() {
        val policy = ModelPackageTrustPolicy(ModelPackageSignatureVerifier { _, _, _ -> false }, "litert", 36, "arm64-v8a") { Instant.parse("2026-08-30T00:00:00Z") }
        assertFailsWith<MobileRuntimeException> { policy.verify(descriptor, descriptor.artifactHash) }
        val trusted = ModelPackageTrustPolicy(ModelPackageSignatureVerifier { _, _, _ -> true }, "litert", 36, "arm64-v8a") { Instant.parse("2026-08-30T00:00:00Z") }
        assertFailsWith<MobileRuntimeException> { trusted.verify(descriptor, "sha256:" + "0".repeat(64)) }
    }

    @Test fun `ed25519 publisher anchor verifies only its signed payload`() {
        val pair = KeyPairGenerator.getInstance("Ed25519").generateKeyPair()
        val payload = descriptor.canonicalUnsignedPayload().toByteArray()
        val signer = Signature.getInstance("Ed25519").also { it.initSign(pair.private); it.update(payload) }
        val signature = Base64.getEncoder().encodeToString(signer.sign())
        val verifier = Ed25519ModelPackageVerifier(mapOf("tervoro" to pair.public))
        kotlin.test.assertTrue(verifier.verify("tervoro", payload, signature))
        kotlin.test.assertFalse(verifier.verify("other", payload, signature))
    }
}
