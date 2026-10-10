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

    fun installedPath(): String? = modelFile.takeIf(File::isFile)?.absolutePath

    fun stage(uri: Uri): StagedModel {
        val displayName = queryDisplayName(uri)
        require(displayName.endsWith(".litertlm", ignoreCase = true)) {
            "Select a LiteRT-LM .litertlm model package"
        }
        val temporary = File(modelDirectory, "staged-${UUID.randomUUID()}.litertlm")
        val digest = MessageDigest.getInstance("SHA-256")
        var total = 0L
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
        val hash = digest.digest().joinToString("") { byte -> "%02x".format(byte) }
        return StagedModel(InstalledModel(temporary.absolutePath, hash, total))
    }

    /** Atomically publishes a model that the caller has already initialized successfully. */
    fun promote(staged: StagedModel): InstalledModel {
        val source = File(staged.model.path)
        require(source.parentFile == modelDirectory && source.isFile) { "Staged model is unavailable" }
        val rollback = File(modelDirectory, "rollback.litertlm")
        if (modelFile.isFile) {
            java.nio.file.Files.move(modelFile.toPath(), rollback.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        }
        try {
            java.nio.file.Files.move(source.toPath(), modelFile.toPath(), java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        } catch (error: Exception) {
            if (rollback.isFile) java.nio.file.Files.move(rollback.toPath(), modelFile.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
            throw error
        }
        return staged.model.copy(path = modelFile.absolutePath)
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
