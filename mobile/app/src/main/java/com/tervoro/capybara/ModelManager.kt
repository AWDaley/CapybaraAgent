package com.tervoro.capybara

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID

data class InstalledModel(
    val path: String,
    val sha256: String,
    val sizeBytes: Long,
)

data class StagedModel(val model: InstalledModel)

class ModelManager(
    private val context: Context,
) {
    private val modelDirectory = File(context.noBackupFilesDir, "models").apply {
        check(mkdirs() || isDirectory)
    }
    private val modelFile = File(modelDirectory, "active.litertlm")
    private val rollbackFile = File(modelDirectory, "rollback.litertlm")

    fun installedPath(): String? {
        // A rollback file means a previous install was interrupted between
        // promotion and commit. Recover the old package before activation.
        if (rollbackFile.isFile) rollbackPromotion()
        if (!modelFile.isFile) return null
        if (BuildConfig.DEBUG && BuildConfig.APPROVED_MODEL_SHA256.isEmpty()) {
            return modelFile.absolutePath
        }
        val expected = BuildConfig.APPROVED_MODEL_SHA256
        if (expected.isBlank()) return null // release without a pin fails closed
        val actual = sha256File(modelFile)
        return modelFile.takeIf { actual == expected }?.absolutePath
    }

    private fun isApproved(digest: String): Boolean =
        (BuildConfig.DEBUG && BuildConfig.APPROVED_MODEL_SHA256.isEmpty()) ||
            digest.equals(BuildConfig.APPROVED_MODEL_SHA256, ignoreCase = true)

    private fun sha256File(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { stream ->
            val bytes = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = stream.read(bytes)
                if (read < 0) break
                digest.update(bytes, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    fun stage(uri: Uri): StagedModel {
        val displayName = queryDisplayName(uri)
        require(displayName.endsWith(".litertlm", ignoreCase = true)) {
            "Select a LiteRT-LM .litertlm model package"
        }
        val temporary = File(modelDirectory, "staged-${UUID.randomUUID()}.litertlm")
        val digest = MessageDigest.getInstance("SHA-256")
        var total = 0L
        var completed = false
        try {
            context.contentResolver.openInputStream(uri).use { input ->
                requireNotNull(input) { "Unable to open selected model" }
                FileOutputStream(temporary).use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        total += read
                        require(total <= MAX_MODEL_BYTES) { "Model exceeds the 8 GiB mobile import limit" }
                        digest.update(buffer, 0, read)
                        output.write(buffer, 0, read)
                    }
                    output.fd.sync()
                }
            }
            require(total > 1_024) { "Selected model package is empty or truncated" }
            val hash = digest.digest().joinToString("") { "%02x".format(it) }
            require(isApproved(hash)) {
                "Model SHA-256 is not on the approved package list"
            }
            completed = true
            return StagedModel(InstalledModel(temporary.absolutePath, hash, total))
        } finally {
            if (!completed) temporary.delete()
        }
    }

    /** Atomically publishes a model that the caller has already initialized successfully. */
    fun promote(staged: StagedModel): InstalledModel {
        val source = File(staged.model.path)
        require(source.parentFile == modelDirectory && source.isFile) { "Staged model is unavailable" }
        check(!rollbackFile.exists()) { "Unresolved previous model promotion; recover before importing" }
        if (modelFile.isFile) {
            java.nio.file.Files.move(
                modelFile.toPath(), rollbackFile.toPath(),
                java.nio.file.StandardCopyOption.REPLACE_EXISTING,
            )
        }
        try {
            java.nio.file.Files.move(
                source.toPath(), modelFile.toPath(),
                java.nio.file.StandardCopyOption.ATOMIC_MOVE,
            )
        } catch (error: Exception) {
            if (rollbackFile.isFile) {
                java.nio.file.Files.move(
                    rollbackFile.toPath(), modelFile.toPath(),
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING,
                )
            }
            throw error
        }
        return staged.model.copy(path = modelFile.absolutePath)
    }

    /** Publish only after the runtime successfully initializes the promoted bytes. */
    fun completePromotion() {
        java.nio.file.Files.deleteIfExists(rollbackFile.toPath())
    }

    /** If initialization fails, restore the previous active package (if any). */
    fun rollbackPromotion() {
        if (rollbackFile.isFile) {
            java.nio.file.Files.move(
                rollbackFile.toPath(), modelFile.toPath(),
                java.nio.file.StandardCopyOption.REPLACE_EXISTING,
            )
        } else {
            modelFile.delete()
        }
    }

    fun discard(staged: StagedModel) {
        val source = File(staged.model.path)
        if (source.parentFile == modelDirectory) source.delete()
    }

    private fun queryDisplayName(uri: Uri): String {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) return cursor.getString(0).orEmpty()
        }
        return uri.lastPathSegment.orEmpty()
    }

    private companion object {
        const val MAX_MODEL_BYTES = 8L * 1_024 * 1_024 * 1_024
    }
}
