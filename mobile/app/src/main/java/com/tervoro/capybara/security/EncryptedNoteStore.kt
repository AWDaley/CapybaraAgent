package com.tervoro.capybara.security

import android.content.Context
import com.tervoro.tal.TaskManifest
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.Locale

class EncryptedNoteStore(
    context: Context,
    private val secrets: AndroidKeyStoreSecrets,
) {
    private val directory = File(context.noBackupFilesDir, "notes").apply {
        check(mkdirs() || isDirectory) { "Unable to create private note directory" }
    }
    private val effectsDirectory = File(context.noBackupFilesDir, "note-effects").apply {
        check(mkdirs() || isDirectory) { "Unable to create private effect directory" }
    }

    @Synchronized
    fun save(key: String, value: String): Boolean {
        val normalizedKey = normalizeKey(key)
        val destination = fileFor(normalizedKey)
        val temporary = File(directory, "${destination.name}.tmp")
        val payload = "$normalizedKey\n$value".toByteArray(Charsets.UTF_8)
        val encrypted = secrets.encrypt(payload, destination.nameWithoutExtension.toByteArray(Charsets.UTF_8))
        FileOutputStream(temporary).use { stream ->
            stream.write(encrypted)
            stream.fd.sync()
        }
        Files.move(
            temporary.toPath(),
            destination.toPath(),
            StandardCopyOption.ATOMIC_MOVE,
            StandardCopyOption.REPLACE_EXISTING,
        )
        return read(normalizedKey) == value
    }

    /** Reconciles a retry with the same semantic local write. */
    @Synchronized
    fun saveOnce(idempotencyKey: String, key: String, value: String): Boolean {
        require(idempotencyKey.matches(Regex("effect:[A-Za-z0-9._-]{1,120}"))) { "Invalid idempotency key" }
        val normalizedKey = normalizeKey(key)
        val fingerprint = TaskManifest.sha256("$normalizedKey\n$value".toByteArray(Charsets.UTF_8))
        val marker = File(effectsDirectory, "${TaskManifest.sha256(idempotencyKey.toByteArray(Charsets.UTF_8))}.effect")
        if (marker.isFile) {
            val recorded = secrets.decrypt(marker.readBytes(), marker.nameWithoutExtension.toByteArray(Charsets.UTF_8)).toString(Charsets.UTF_8)
            check(recorded == fingerprint) { "Idempotency key was reused with different note semantics" }
            return read(normalizedKey) == value
        }
        if (!save(normalizedKey, value)) return false
        val temporary = File(effectsDirectory, "${marker.name}.tmp")
        FileOutputStream(temporary).use { stream ->
            stream.write(secrets.encrypt(fingerprint.toByteArray(Charsets.UTF_8), marker.nameWithoutExtension.toByteArray(Charsets.UTF_8)))
            stream.fd.sync()
        }
        Files.move(temporary.toPath(), marker.toPath(), StandardCopyOption.ATOMIC_MOVE)
        return read(normalizedKey) == value
    }

    @Synchronized
    fun read(key: String): String? {
        val normalizedKey = normalizeKey(key)
        val file = fileFor(normalizedKey)
        if (!file.isFile) return null
        val plain = secrets.decrypt(file.readBytes(), file.nameWithoutExtension.toByteArray(Charsets.UTF_8))
            .toString(Charsets.UTF_8)
        val separator = plain.indexOf('\n')
        check(separator >= 0 && plain.substring(0, separator) == normalizedKey) { "Encrypted note identity mismatch" }
        return plain.substring(separator + 1)
    }

    @Synchronized
    fun keys(): List<String> = directory.listFiles { file -> file.extension == "note" }
        .orEmpty()
        .mapNotNull { file ->
            runCatching {
                val plain = secrets.decrypt(
                    file.readBytes(),
                    file.nameWithoutExtension.toByteArray(Charsets.UTF_8),
                ).toString(Charsets.UTF_8)
                plain.substringBefore('\n').takeIf { it.isNotBlank() }
            }.getOrNull()
        }
        .sorted()

    private fun fileFor(normalizedKey: String): File {
        val digest = TaskManifest.sha256(normalizedKey.toByteArray(Charsets.UTF_8))
        return File(directory, "$digest.note")
    }

    private fun normalizeKey(key: String): String = key.trim().lowercase(Locale.ROOT).also {
        require(it.isNotEmpty() && it.length <= 80) { "Note key must contain 1-80 characters" }
        require(!it.contains('\n') && !it.contains('\r')) { "Note key contains a forbidden control character" }
    }
}
