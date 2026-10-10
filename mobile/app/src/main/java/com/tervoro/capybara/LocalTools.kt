package com.tervoro.capybara

import com.tervoro.capybara.security.EncryptedNoteStore
import com.tervoro.tal.ApprovalPolicy
import com.tervoro.tal.EffectClass
import com.tervoro.tal.ExecutionPhase
import com.tervoro.tal.ParamRule
import com.tervoro.tal.TalTool
import com.tervoro.tal.ToolDefinition
import com.tervoro.tal.ToolResult
import com.tervoro.tal.ValueType
import com.tervoro.tal.string
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import kotlinx.serialization.json.JsonElement

private val actionPhases = setOf(ExecutionPhase.EXECUTION, ExecutionPhase.RECOVERY)
private val readPhases = actionPhases + ExecutionPhase.DISCOVERY + ExecutionPhase.VERIFICATION

class CurrentTimeTool : TalTool {
    override val definition = ToolDefinition(
        name = "current_time",
        description = "Read the phone's current local date, time, and time zone.",
        effect = EffectClass.READ,
        approvalPolicy = ApprovalPolicy.AUTO,
        allowedPhases = readPhases,
        schema = emptyMap(),
    )

    override suspend fun execute(arguments: Map<String, JsonElement>): ToolResult = ToolResult(
        success = true,
        output = ZonedDateTime.now().format(DateTimeFormatter.ISO_ZONED_DATE_TIME),
        independentlyVerified = true,
    )
}

class ListNotesTool(
    private val store: EncryptedNoteStore,
) : TalTool {
    override val definition = ToolDefinition(
        name = "list_notes",
        description = "List keys for encrypted notes stored only inside this app.",
        effect = EffectClass.READ,
        approvalPolicy = ApprovalPolicy.AUTO,
        allowedPhases = readPhases,
        schema = emptyMap(),
    )

    override suspend fun execute(arguments: Map<String, JsonElement>): ToolResult = ToolResult(
        success = true,
        output = store.keys().joinToString(prefix = "[", postfix = "]"),
        independentlyVerified = true,
    )
}

class ReadNoteTool(
    private val store: EncryptedNoteStore,
) : TalTool {
    override val definition = ToolDefinition(
        name = "read_note",
        description = "Read one encrypted local note by its exact key.",
        effect = EffectClass.READ,
        approvalPolicy = ApprovalPolicy.AUTO,
        allowedPhases = readPhases,
        schema = mapOf("key" to ParamRule(ValueType.STRING, maxLength = 80)),
    )

    override suspend fun execute(arguments: Map<String, JsonElement>): ToolResult {
        val key = arguments.string("key") ?: return ToolResult(false, "Missing note key", stableErrorCode = "TAL_SCHEMA_REQUIRED")
        val value = store.read(key)
            ?: return ToolResult(false, "No encrypted note exists for '$key'", stableErrorCode = "TAL_NOTE_NOT_FOUND")
        return ToolResult(true, value, independentlyVerified = true)
    }
}

class SaveNoteTool(
    private val store: EncryptedNoteStore,
) : TalTool {
    override val definition = ToolDefinition(
        name = "note.create",
        description = "Create or replace one encrypted app-private note. Requires explicit user authentication.",
        effect = EffectClass.WRITE,
        approvalPolicy = ApprovalPolicy.CONFIRM,
        allowedPhases = actionPhases,
        schema = mapOf(
            "idempotency_key" to ParamRule(ValueType.STRING, maxLength = 128),
            "key" to ParamRule(ValueType.STRING, maxLength = 80),
            "value" to ParamRule(ValueType.STRING, maxLength = 4_096),
        ),
    )

    override suspend fun execute(arguments: Map<String, JsonElement>): ToolResult {
        val key = arguments.string("key") ?: return ToolResult(false, "Missing note key", stableErrorCode = "TAL_SCHEMA_REQUIRED")
        val value = arguments.string("value") ?: return ToolResult(false, "Missing note value", stableErrorCode = "TAL_SCHEMA_REQUIRED")
        val idempotencyKey = arguments.string("idempotency_key") ?: return ToolResult(false, "Missing idempotency key", stableErrorCode = "TAL_SCHEMA_REQUIRED")
        val verified = store.saveOnce(idempotencyKey, key, value)
        return ToolResult(
            success = verified,
            output = if (verified) "Encrypted note '$key' was written and read back successfully" else "Note read-back failed",
            independentlyVerified = verified,
            stableErrorCode = if (verified) null else "TAL_WRITE_VERIFICATION_FAILED",
        )
    }
}
