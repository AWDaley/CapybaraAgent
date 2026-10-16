package com.tervoro.tal

import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.time.Instant
import java.util.Base64
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class SignedModelPackageTest {
    private fun descriptor(signature: String = "signed") = ModelPackageDescriptor(
        packageId = "package:test", publisherId = "tervoro",
        artifactHash = "sha256:" + "a".repeat(64), modelProfileId = "local-test",
        modelVersion = "1", quantization = "int4",
        tokenizerHash = "sha256:" + "b".repeat(64), runtimeId = "litert",
        promptProfileId = "tal-mobile-v1", certificationId = "test-not-certified",
        minimumAndroidApi = 28, supportedAbis = setOf("arm64-v8a"),
        issuedAt = Instant.parse("2026-01-01T00:00:00Z"),
        expiresAt = Instant.parse("2027-01-01T00:00:00Z"), signature = signature,
    )

    private fun signedJson(value: ModelPackageDescriptor) =
        value.canonicalUnsignedPayload().dropLast(1) + ",\"signature\":\"" + value.signature + "\"}"

    private fun pair() = KeyPairGenerator.getInstance("EC").apply {
        initialize(ECGenParameterSpec("secp256r1"))
    }.generateKeyPair()

    private fun sign(value: ModelPackageDescriptor, privateKey: java.security.PrivateKey): ModelPackageDescriptor {
        val signature = Signature.getInstance("SHA256withECDSA").apply {
            initSign(privateKey)
            update(value.canonicalUnsignedPayload().toByteArray(Charsets.UTF_8))
        }
        return value.copy(signature = Base64.getEncoder().encodeToString(signature.sign()))
    }

    private fun policy(pair: java.security.KeyPair, current: Instant =
        Instant.parse("2026-10-16T00:00:00Z")
    ) = ModelPackageTrustPolicy(
        verifier = P256ModelPackageVerifier(mapOf("tervoro" to pair.public)),
        expectedRuntimeId = "litert", androidApi = 36, abi = "arm64-v8a",
        now = { current },
    )

    @Test fun signedDescriptorRoundTripsAndAuthenticates() {
        val keys = pair()
        val value = sign(descriptor(), keys.private)
        val parsed = SignedModelPackage.parse(signedJson(value))
        assertEquals(value, parsed)
        policy(keys).verify(parsed, value.artifactHash)
    }

    @Test fun modifiedDescriptorDigestAndUntrustedKeyFailClosed() {
        val keys = pair()
        val value = sign(descriptor(), keys.private)
        assertFailsWith<MobileRuntimeException> {
            policy(keys).verify(value.copy(modelVersion = "malicious"), value.artifactHash)
        }
        assertFailsWith<MobileRuntimeException> {
            policy(keys).verify(value, "sha256:" + "0".repeat(64))
        }
        assertFailsWith<MobileRuntimeException> {
            policy(pair()).verify(value, value.artifactHash)
        }
    }

    @Test fun expiryRevocationAndIncompatibleDeviceFailClosed() {
        val keys = pair()
        val value = sign(descriptor(), keys.private)
        assertFailsWith<MobileRuntimeException> {
            policy(keys, Instant.parse("2027-01-02T00:00:00Z")).verify(value, value.artifactHash)
        }
        assertFailsWith<MobileRuntimeException> {
            policy(keys).verify(value.copy(revoked = true), value.artifactHash)
        }
        val badDevice = ModelPackageTrustPolicy(
            P256ModelPackageVerifier(mapOf("tervoro" to keys.public)), "litert",
            androidApi = 28, abi = "x86_64",
            now = { Instant.parse("2026-10-16T00:00:00Z") },
        )
        assertFailsWith<MobileRuntimeException> {
            badDevice.verify(value, value.artifactHash)
        }
    }

    @Test fun malformedOrExtraMetadataIsRejected() {
        val valid = signedJson(descriptor())
        assertFailsWith<IllegalArgumentException> {
            SignedModelPackage.parse(valid.replace("\"signature\"", "\"unknown_field\""))
        }
        assertFailsWith<IllegalArgumentException> {
            SignedModelPackage.parse(valid.replace("sha256:" + "a".repeat(64), "sha256:wrong"))
        }
        assertFailsWith<IllegalArgumentException> {
            SignedModelPackage.parse(valid.replace("\"revoked\":false", "\"revoked\":\"false\""))
        }
        assertFailsWith<IllegalArgumentException> { SignedModelPackage.parse("{}") }
    }

    @Test fun signerDoesNotAcceptWrongPublisherOrModifiedPayload() {
        val keys = pair()
        val signed = sign(descriptor(), keys.private)
        val verifier = P256ModelPackageVerifier(mapOf("tervoro" to keys.public))
        val bytes = signed.canonicalUnsignedPayload().toByteArray(Charsets.UTF_8)
        assertTrue(verifier.verify("tervoro", bytes, signed.signature))
        assertFalse(verifier.verify("unknown", bytes, signed.signature))
        assertFalse(verifier.verify("tervoro", bytes + 0x20.toByte(), signed.signature))
        assertFalse(verifier.verify("tervoro", bytes, "invalid-base64"))
    }
}
