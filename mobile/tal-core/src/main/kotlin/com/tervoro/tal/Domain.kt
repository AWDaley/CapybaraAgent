package com.tervoro.tal

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.time.Instant

enum class ExecutionPhase {
    DISCOVERY,
    PLANNING,
    EXECUTION,
    VERIFICATION,
    RECOVERY,
}

enum class EffectClass {
    READ,
    WRITE,
    EXECUTION,
    NETWORK,
    DESTRUCTIVE,
}

enum class ApprovalPolicy {
    AUTO,
    LOG,
    CONFIRM,
}

enum class ValueType {
    STRING,
    INTEGER,
    BOOLEAN,
}

data class ParamRule(
    val type: ValueType,
    val required: Boolean = true,
    val maxLength: Int = 4_096,
)

data class ToolDefinition(
    val name: String,
    val description: String,
    val effect: EffectClass,
    val approvalPolicy: ApprovalPolicy,
    val allowedPhases: Set<ExecutionPhase>,
    val schema: Map<String, ParamRule>,
)

data class ToolResult(
    val success: Boolean,
    val output: String,
    val independentlyVerified: Boolean = false,
    val stableErrorCode: String? = null,
)

interface TalTool {
    val definition: ToolDefinition
    suspend fun execute(arguments: Map<String, JsonElement>): ToolResult
}

data class BudgetLimits(
    val maxSteps: Int = 8,
    val maxTimeMillis: Long = 120_000,
    val maxToolErrors: Int = 2,
    val maxRepairAttempts: Int = 2,
) {
    init {
        require(maxSteps in 1..32)
        require(maxTimeMillis in 1_000..900_000)
        require(maxToolErrors in 0..8)
        require(maxRepairAttempts in 0..8)
    }
}

data class CapabilityEnvelope(
    val requested: Set<String>,
    val effective: Set<String>,
    val denied: Map<String, String>,
) {
    fun permits(toolName: String): Boolean = toolName in effective
}

sealed interface VerificationCriterion {
    data object NonEmptyFinalAnswer : VerificationCriterion
    data object VerifiedWritesOnly : VerificationCriterion
}

sealed interface Proposal {
    val thought: String

    data class Action(
        override val thought: String,
        val toolName: String,
        val arguments: Map<String, JsonElement>,
    ) : Proposal

    data class Complete(
        override val thought: String,
        val finalAnswer: String,
    ) : Proposal

    data class Query(
        override val thought: String,
        val question: String,
    ) : Proposal

    data class Escalate(
        override val thought: String,
        val reason: String,
        val context: String = "",
    ) : Proposal
}

data class GateResult(
    val allowed: Boolean,
    val stage: String,
    val stableErrorCode: String? = null,
    val reason: String,
    val requiresApproval: Boolean = false,
    val sanitizedArguments: Map<String, JsonElement> = emptyMap(),
)

data class ApprovalRequest(
    val requestId: String,
    val manifestId: String,
    val manifestHash: String,
    val stateVersion: Long,
    val tool: ToolDefinition,
    val arguments: Map<String, JsonElement>,
    val canonicalArguments: String,
    val expiresAt: Instant,
)

/** Immutable, exact authorization boundary for a single protected operation. */
fun ApprovalRequest.matches(
    manifestHash: String,
    stateVersion: Long,
    toolName: String,
    arguments: Map<String, JsonElement>,
    now: Instant = Instant.now(),
): Boolean =
    this.manifestHash == manifestHash &&
        this.stateVersion == stateVersion &&
        tool.name == toolName &&
        canonicalArguments == CanonicalJson.encode(JsonObject(arguments.toSortedMap())) &&
        now.isBefore(expiresAt)

enum class ApprovalDecision {
    APPROVED,
    DENIED,
}

fun interface ApprovalHandler {
    suspend fun requestApproval(request: ApprovalRequest): ApprovalDecision
}

sealed interface EngineResult {
    val manifest: TaskManifest

    data class Completed(
        override val manifest: TaskManifest,
        val answer: String,
    ) : EngineResult

    data class WaitingForUser(
        override val manifest: TaskManifest,
        val question: String,
    ) : EngineResult

    data class Escalated(
        override val manifest: TaskManifest,
        val stableErrorCode: String,
        val reason: String,
    ) : EngineResult
}

interface LocalSlmRuntime : AutoCloseable {
    val displayName: String
    val isReady: Boolean
    suspend fun initialize(modelPath: String? = null)
    suspend fun generate(prompt: String): String
    override fun close() = Unit
}
