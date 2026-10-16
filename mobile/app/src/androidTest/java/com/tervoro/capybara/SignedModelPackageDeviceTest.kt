package com.tervoro.capybara

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.tervoro.tal.ModelPackageDescriptor
import com.tervoro.tal.ModelPackageTrustPolicy
import com.tervoro.tal.P256ModelPackageVerifier
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.time.Instant
import java.util.Base64
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Compiled in CI; execute on real devices before hardware sign-off. */
@RunWith(AndroidJUnit4::class)
class SignedModelPackageDeviceTest {
    @Test fun platformP256ProviderValidatesAndRejectsTamperedDescriptors() {
        val pair = KeyPairGenerator.getInstance("EC").apply {
            initialize(ECGenParameterSpec("secp256r1"))
        }.generateKeyPair()
        val descriptor = ModelPackageDescriptor(
            packageId = "instrumented", publisherId = "tervoro",
            artifactHash = "sha256:" + "a".repeat(64), modelProfileId = "android",
            modelVersion = "1", quantization = "int4",
            tokenizerHash = "sha256:" + "b".repeat(64), runtimeId = "litert",
            promptProfileId = "tal-mobile-v1", certificationId = "instrumented-only",
            minimumAndroidApi = 28, supportedAbis = setOf(Build.SUPPORTED_ABIS.first()),
            issuedAt = Instant.parse("2026-01-01T00:00:00Z"),
            expiresAt = Instant.parse("2035-01-01T00:00:00Z"), signature = "unsigned",
        )
        val payload = descriptor.canonicalUnsignedPayload().toByteArray()
        val signature = Signature.getInstance("SHA256withECDSA").apply {
            initSign(pair.private)
            update(payload)
        }.sign()
        val signed = descriptor.copy(signature = Base64.getEncoder().encodeToString(signature))
        val verifier = P256ModelPackageVerifier(mapOf("tervoro" to pair.public))
        assertTrue(verifier.verify("tervoro", payload, signed.signature))
        assertFalse(verifier.verify("tervoro", payload + 1.toByte(), signed.signature))
        val policy = ModelPackageTrustPolicy(
            verifier, "litert", Build.VERSION.SDK_INT, Build.SUPPORTED_ABIS.first(),
        )
        policy.verify(signed, signed.artifactHash)
    }
}
