package com.tervoro.capybara.security

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import android.util.Base64
import com.tervoro.tal.AuditSigner
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.Mac
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class AndroidKeyStoreSecrets : AuditSigner {
    private val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }

    fun encrypt(plainText: ByteArray, associatedData: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(AES_TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, encryptionKey())
        cipher.updateAAD(associatedData)
        val encrypted = cipher.doFinal(plainText)
        return ByteBuffer.allocate(2 + cipher.iv.size + encrypted.size)
            .put(FORMAT_VERSION)
            .put(cipher.iv.size.toByte())
            .put(cipher.iv)
            .put(encrypted)
            .array()
    }

    fun decrypt(blob: ByteArray, associatedData: ByteArray): ByteArray {
        require(blob.size > 14) { "Encrypted record is truncated" }
        val buffer = ByteBuffer.wrap(blob)
        require(buffer.get() == FORMAT_VERSION) { "Unsupported encrypted record version" }
        val ivLength = buffer.get().toInt() and 0xff
        require(ivLength in 12..16 && buffer.remaining() > ivLength) { "Invalid encrypted record IV" }
        val iv = ByteArray(ivLength).also(buffer::get)
        val encrypted = ByteArray(buffer.remaining()).also(buffer::get)
        val cipher = Cipher.getInstance(AES_TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, encryptionKey(), GCMParameterSpec(128, iv))
        cipher.updateAAD(associatedData)
        return cipher.doFinal(encrypted)
    }

    override fun sign(payload: ByteArray): String {
        val mac = Mac.getInstance(HMAC_ALGORITHM)
        mac.init(authenticationKey())
        return Base64.encodeToString(mac.doFinal(payload), Base64.NO_WRAP)
    }

    fun verify(payload: ByteArray, expectedTag: String): Boolean {
        val actual = Base64.decode(sign(payload), Base64.NO_WRAP)
        val expected = try {
            Base64.decode(expectedTag, Base64.NO_WRAP)
        } catch (_: IllegalArgumentException) {
            return false
        }
        return java.security.MessageDigest.isEqual(actual, expected)
    }

    private fun encryptionKey(): SecretKey = getOrCreate(AES_ALIAS) {
        runCatching { generateEncryptionKey(strongBox = true) }
            .recoverCatching { exception ->
                if (exception !is StrongBoxUnavailableException) throw exception
                generateEncryptionKey(strongBox = false)
            }
            .getOrThrow()
    }

    private fun generateEncryptionKey(strongBox: Boolean): SecretKey {
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        val builder = KeyGenParameterSpec.Builder(
                AES_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
        if (strongBox) builder.setIsStrongBoxBacked(true)
        generator.init(builder.build())
        return generator.generateKey()
    }

    private fun authenticationKey(): SecretKey = getOrCreate(HMAC_ALIAS) {
        runCatching { generateAuthenticationKey(strongBox = true) }
            .recoverCatching { exception ->
                if (exception !is StrongBoxUnavailableException) throw exception
                generateAuthenticationKey(strongBox = false)
            }
            .getOrThrow()
    }

    private fun generateAuthenticationKey(strongBox: Boolean): SecretKey {
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_HMAC_SHA256, KEYSTORE)
        val builder = KeyGenParameterSpec.Builder(
            HMAC_ALIAS,
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
        )
                .setKeySize(256)
                .setDigests(KeyProperties.DIGEST_SHA256)
        if (strongBox) builder.setIsStrongBoxBacked(true)
        generator.init(builder.build())
        return generator.generateKey()
    }

    private inline fun getOrCreate(alias: String, create: () -> SecretKey): SecretKey =
        (keyStore.getKey(alias, null) as? SecretKey) ?: create()

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val AES_ALIAS = "tervoro.local.aes.v1"
        const val HMAC_ALIAS = "tervoro.audit.hmac.v1"
        const val AES_TRANSFORMATION = "AES/GCM/NoPadding"
        const val HMAC_ALGORITHM = "HmacSHA256"
        const val FORMAT_VERSION: Byte = 1
    }
}
