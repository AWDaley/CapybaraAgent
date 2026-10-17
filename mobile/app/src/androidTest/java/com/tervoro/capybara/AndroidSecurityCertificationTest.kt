package com.tervoro.capybara

import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.tervoro.capybara.security.AndroidKeyStoreSecrets
import com.tervoro.capybara.security.EncryptedAuditSink
import com.tervoro.capybara.security.EncryptedNoteStore
import com.tervoro.tal.AuditTrail
import com.tervoro.tal.DeviceReadiness
import com.tervoro.tal.ModelResourceRequirements
import java.io.File
import java.util.UUID
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Hardware certification gates. Compiled in CI but MUST run on actual ARM64
 * Android hardware for a release. Uses isolated test IDs and synthetic data.
 */
@RunWith(AndroidJUnit4::class)
class AndroidSecurityCertificationTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun demoAppIsLocalOnlyAndDisablesBackup() {
        val info = context.packageManager.getPackageInfo(
            context.packageName, PackageManager.GET_PERMISSIONS,
        )
        assertFalse(info.requestedPermissions.orEmpty().contains("android.permission.INTERNET"))
        val appInfo = context.packageManager.getApplicationInfo(context.packageName, 0)
        assertEquals(0, appInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP)
    }

    @Test fun environmentProbeProvidesActualResourceSignalsAndFailClosedPolicy() {
        val profile = AndroidDeviceProbe.capture(context)
        assertTrue(profile.androidApi >= 28)
        assertTrue(profile.availableRamBytes >= 0)
        assertTrue(profile.availableStorageBytes > 0)
        assertTrue(profile.abi.isNotBlank())
        assertTrue(profile.batteryPercent in -1..100)
        val blockers = DeviceReadiness.evaluate(profile, ModelResourceRequirements(
            minimumRamBytes = 0,
            minimumStorageBytes = 0,
            minimumBatteryPercent = 0,
        ))
        assertEquals(profile.abi != "arm64-v8a", "DEVICE_ABI_UNSUPPORTED" in blockers)
        assertEquals(profile.batteryPercent == -1, "DEVICE_BATTERY_INSUFFICIENT" in blockers)
        assertEquals(profile.thermalStatus >= 4, "DEVICE_THERMAL_UNSAFE" in blockers)
    }

    @Test fun hardwareKeystoreEncryptsAuthenticatesAndBindsAssociatedData() {
        val secrets = AndroidKeyStoreSecrets()
        val plaintext = "synthetic device certification value".toByteArray()
        val aad = "run:correct".toByteArray()
        val ciphertext = secrets.encrypt(plaintext, aad)
        assertFalse(ciphertext.contentEquals(plaintext))
        assertArrayEquals(plaintext, secrets.decrypt(ciphertext, aad))
        val sameMessageDifferentNonce = secrets.encrypt(plaintext, aad)
        assertFalse(ciphertext.contentEquals(sameMessageDifferentNonce))
        assertRejected { secrets.decrypt(ciphertext, "run:wrong".toByteArray()) }
        val tampered = ciphertext.clone()
        tampered[tampered.lastIndex] = (tampered.last().toInt() xor 1).toByte()
        assertRejected { secrets.decrypt(tampered, aad) }
        val tag = secrets.sign(plaintext)
        assertTrue(secrets.verify(plaintext, tag))
        assertFalse(secrets.verify("different".toByteArray(), tag))
    }

    @Test fun encryptedAuditDetectsTamperingAndReplay() {
        val secrets = AndroidKeyStoreSecrets()
        val sessionId = "cert_${UUID.randomUUID().toString().replace("-", "")}"
        val folder = File(context.noBackupFilesDir, "audit/$sessionId")
        try {
            val sink = EncryptedAuditSink(context, sessionId, secrets)
            val trail = AuditTrail(signer = secrets, sink = sink)
            trail.append("task_started")
            trail.append("task_completed")
            assertEquals(2, sink.loadVerified().size)
            assertRejected { sink.persist(trail.events.first()) } // sequence collision
            val second = File(folder, "event_000002.tal")
            assertTrue(second.isFile)
            val tampered = second.readBytes()
            tampered[tampered.lastIndex] = (tampered.last().toInt() xor 1).toByte()
            second.writeBytes(tampered)
            assertRejected { sink.loadVerified() }
        } finally {
            folder.deleteRecursively()
        }
    }

    @Test fun encryptedNotesEnforceIdempotencyAndReadback() {
        val store = EncryptedNoteStore(context, AndroidKeyStoreSecrets())
        val key = "cert-${UUID.randomUUID()}"
        val token = "effect:cert-${UUID.randomUUID()}"
        val value = "synthetic note, no user data"
        assertTrue(store.saveOnce(token, key, value))
        assertEquals(value, store.read(key))
        assertTrue(store.saveOnce(token, key, value))
        assertRejected { store.saveOnce(token, key, "unapproved different value") }
        assertEquals(value, store.read(key))
    }

    private inline fun assertRejected(action: () -> Unit) {
        var rejected = false
        try {
            action()
        } catch (_: Exception) {
            rejected = true
        }
        assertTrue("Security operation unexpectedly succeeded", rejected)
    }
}
