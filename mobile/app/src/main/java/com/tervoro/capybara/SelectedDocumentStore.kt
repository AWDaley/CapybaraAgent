package com.tervoro.capybara

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.tervoro.tal.ApprovalPolicy
import com.tervoro.tal.DocumentProvenance
import com.tervoro.tal.EffectClass
import com.tervoro.tal.ExecutionPhase
import com.tervoro.tal.TalTool
import com.tervoro.tal.ToolDefinition
import com.tervoro.tal.ToolResult
import com.tervoro.tal.VaultSource
import kotlinx.serialization.json.JsonElement
import java.io.ByteArrayOutputStream

data class SelectedDocument(val uri: Uri, val displayName: String, val sizeBytes: Long?)

class SelectedDocumentStore(private val context: Context) {
    @Volatile private var selection: SelectedDocument? = null

    fun select(uri: Uri): SelectedDocument {
        val flags = android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION
        runCatching { context.contentResolver.takePersistableUriPermission(uri, flags) }
        val selected = context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)
            ?.use { cursor ->
                if (cursor.moveToFirst()) SelectedDocument(
                    uri,
                    cursor.getString(0).orEmpty().ifBlank { "selected-document" },
                    cursor.getLong(1).takeIf { !cursor.isNull(1) },
                ) else null
            } ?: SelectedDocument(uri, "selected-document", null)
        require(selected.sizeBytes == null || selected.sizeBytes <= MAX_DOCUMENT_BYTES) { "TAL_DOCUMENT_TOO_LARGE" }
        selection = selected
        return selected
    }

    fun current(): SelectedDocument? = selection

    fun readText(): String {
        return readSource().text
    }

    fun readSource(): VaultSource {
        val document = checkNotNull(selection) { "TAL_DOCUMENT_NOT_SELECTED" }
        val bytes = context.contentResolver.openInputStream(document.uri).use { input ->
            requireNotNull(input) { "TAL_DOCUMENT_UNAVAILABLE" }
            ByteArrayOutputStream().use { output ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                var total = 0L
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= MAX_DOCUMENT_BYTES) { "TAL_DOCUMENT_TOO_LARGE" }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
        }
        return DocumentProvenance.ingest("source:selected-document", bytes)
    }

    private companion object { const val MAX_DOCUMENT_BYTES = 512L * 1024L }
}

class SelectedDocumentReadTool(private val store: SelectedDocumentStore) : TalTool {
    override val definition = ToolDefinition(
        name = "document.selected.read", description = "Read the exact text document selected by the user.",
        effect = EffectClass.READ, approvalPolicy = ApprovalPolicy.AUTO,
        allowedPhases = setOf(ExecutionPhase.DISCOVERY, ExecutionPhase.EXECUTION, ExecutionPhase.RECOVERY), schema = emptyMap(),
    )
    override suspend fun execute(arguments: Map<String, JsonElement>): ToolResult = try {
        val document = store.current() ?: return ToolResult(false, "No document is selected", stableErrorCode = "TAL_DOCUMENT_NOT_SELECTED")
        val source = store.readSource()
        ToolResult(true, "source=${document.displayName}; ref=${source.sourceRef}; hash=${source.contentHash}\n${source.text}", independentlyVerified = true)
    } catch (exception: IllegalArgumentException) {
        ToolResult(false, exception.message ?: "Document unavailable", stableErrorCode = exception.message)
    }
}
