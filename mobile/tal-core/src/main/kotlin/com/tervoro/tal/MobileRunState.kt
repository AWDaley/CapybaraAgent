package com.tervoro.tal

data class MobileRunEvent(
    val eventId: String,
    val runId: String,
    val sequence: Long,
    val stateVersion: Long,
    val eventType: String,
    val payload: Map<String, String> = emptyMap(),
)

data class MobileRunState(
    val runId: String,
    val manifestHash: String,
    val ledgerSequence: Long = 0,
    val stateVersion: Long = 0,
    val phase: MobileRunPhase = MobileRunPhase.CREATED,
    val pendingApprovalId: String? = null,
    val pendingEffectKey: String? = null,
    val observations: List<String> = emptyList(),
    val terminalOutcome: String? = null,
)

enum class MobileRunPhase {
    CREATED,
    VALIDATING,
    READY,
    REASONING,
    WAITING_FOR_TOOL,
    WAITING_FOR_INFORMATION,
    WAITING_FOR_APPROVAL,
    VERIFYING,
    COMPLETED,
    ESCALATED,
    CANCELLED,
    FAILED,
}

class MobileRuntimeException(
    val stableErrorCode: String,
    message: String,
) : IllegalStateException(message)

object MobileRunReducer {
    private val terminalPhases = setOf(
        MobileRunPhase.COMPLETED,
        MobileRunPhase.ESCALATED,
        MobileRunPhase.CANCELLED,
        MobileRunPhase.FAILED,
    )
    val stateMutatingEvents = setOf(
        "manifest.created",
        "manifest.validated",
        "capability.computed",
        "model.proposal_received",
        "proposal.rejected",
        "tool.intent_recorded",
        "tool.succeeded",
        "tool.failed",
        "tool.reconciled",
        "observation.recorded",
        "approval.requested",
        "approval.granted",
        "approval.denied",
        "lifecycle.process_restored",
        "lifecycle.permission_revoked",
        "completion.proposed",
        "completion.verified",
        "run.completed",
        "run.escalated",
        "run.cancelled",
    )

    fun reduce(state: MobileRunState, event: MobileRunEvent): MobileRunState {
        if (event.runId != state.runId) error("UNRESOLVED_REFERENCE", "Event belongs to another run")
        if (event.sequence != state.ledgerSequence + 1) error("STALE_STATE_VERSION", "Event sequence is not contiguous")
        if (state.phase in terminalPhases && !(state.phase == MobileRunPhase.COMPLETED && event.eventType == "run.completed")) {
            error("INVALID_STATE_TRANSITION", "Terminal mobile run cannot become active")
        }

        var phase = state.phase
        var pendingApproval = state.pendingApprovalId
        var pendingEffect = state.pendingEffectKey
        var observations = state.observations
        var outcome = state.terminalOutcome

        when (event.eventType) {
            "manifest.created" -> {
                if (phase != MobileRunPhase.CREATED) error("INVALID_STATE_TRANSITION", "Manifest may be created only once")
                phase = MobileRunPhase.VALIDATING
            }

            "manifest.validated" -> {
                if (phase != MobileRunPhase.VALIDATING) error("INVALID_STATE_TRANSITION", "Manifest validation requires validating phase")
                phase = MobileRunPhase.READY
            }

            "capability.computed" -> {
                if (phase != MobileRunPhase.READY) error("INVALID_STATE_TRANSITION", "Capabilities require ready phase")
            }

            "model.proposal_received" -> {
                if (phase != MobileRunPhase.READY) error("INVALID_STATE_TRANSITION", "Proposal requires ready phase")
                phase = MobileRunPhase.REASONING
            }

            "proposal.rejected" -> {
                if (phase !in setOf(MobileRunPhase.READY, MobileRunPhase.REASONING)) {
                    error("INVALID_STATE_TRANSITION", "Rejection requires active proposal phase")
                }
                phase = MobileRunPhase.READY
            }

            "tool.intent_recorded" -> {
                if (phase !in setOf(MobileRunPhase.READY, MobileRunPhase.REASONING)) {
                    error("INVALID_STATE_TRANSITION", "Tool intent requires ready or reasoning phase")
                }
                pendingEffect = event.payload["idempotency_key"]
                    ?: error("IDEMPOTENCY_CONFLICT", "Tool intent needs a semantic idempotency key")
                phase = MobileRunPhase.WAITING_FOR_TOOL
            }

            "tool.succeeded", "tool.failed", "tool.reconciled" -> {
                if (phase != MobileRunPhase.WAITING_FOR_TOOL || pendingEffect == null) {
                    error("INVALID_STATE_TRANSITION", "Tool result requires a pending effect")
                }
                if (event.payload["idempotency_key"] != pendingEffect) {
                    error("IDEMPOTENCY_CONFLICT", "Tool result does not match pending effect")
                }
                pendingEffect = null
                phase = MobileRunPhase.READY
            }

            "observation.recorded" -> {
                val observation = event.payload["observation_id"]
                    ?: error("TOOL_OUTPUT_INVALID", "Observation must have an ID")
                if (observation !in observations) observations = observations + observation
                phase = MobileRunPhase.READY
            }

            "approval.requested" -> {
                if (phase !in setOf(MobileRunPhase.READY, MobileRunPhase.REASONING)) {
                    error("INVALID_STATE_TRANSITION", "Approval requires active run")
                }
                pendingApproval = event.payload["approval_id"]
                    ?: error("APPROVAL_REQUIRED", "Approval request needs an ID")
                phase = MobileRunPhase.WAITING_FOR_APPROVAL
            }

            "approval.granted", "approval.denied" -> {
                if (phase != MobileRunPhase.WAITING_FOR_APPROVAL || pendingApproval == null) {
                    error("APPROVAL_STALE", "No approval is pending")
                }
                if (event.payload["approval_id"] != pendingApproval) {
                    error("APPROVAL_STALE", "Approval does not match pending request")
                }
                pendingApproval = null
                phase = if (event.eventType == "approval.granted") {
                    MobileRunPhase.READY
                } else {
                    MobileRunPhase.WAITING_FOR_INFORMATION
                }
            }

            "lifecycle.process_restored" -> {
                phase = when {
                    pendingEffect != null -> MobileRunPhase.WAITING_FOR_TOOL
                    pendingApproval != null -> MobileRunPhase.WAITING_FOR_APPROVAL
                    else -> phase
                }
            }

            "lifecycle.permission_revoked" -> {
                if (phase in setOf(MobileRunPhase.WAITING_FOR_TOOL, MobileRunPhase.WAITING_FOR_APPROVAL, MobileRunPhase.REASONING, MobileRunPhase.READY)) {
                    phase = MobileRunPhase.WAITING_FOR_INFORMATION
                }
            }

            "completion.proposed" -> {
                if (phase != MobileRunPhase.READY) error("INVALID_STATE_TRANSITION", "Completion proposal requires ready phase")
                phase = MobileRunPhase.VERIFYING
            }

            "completion.verified" -> {
                if (phase != MobileRunPhase.VERIFYING) error("INVALID_STATE_TRANSITION", "Completion verification requires verifying phase")
                outcome = event.payload["outcome"]
                    ?: error("COMPLETION_EVIDENCE_INSUFFICIENT", "Completion needs terminal outcome")
                phase = MobileRunPhase.COMPLETED
            }

            "run.completed" -> {
                if (phase !in setOf(MobileRunPhase.VERIFYING, MobileRunPhase.COMPLETED)) {
                    error("INVALID_STATE_TRANSITION", "Run completion requires verified completion")
                }
                outcome = event.payload["outcome"] ?: outcome
                    ?: error("COMPLETION_EVIDENCE_INSUFFICIENT", "Run completion needs terminal outcome")
                phase = MobileRunPhase.COMPLETED
            }

            "run.escalated" -> {
                phase = MobileRunPhase.ESCALATED
                outcome = "escalated"
            }

            "run.cancelled" -> {
                phase = MobileRunPhase.CANCELLED
                outcome = "cancelled"
            }

            else -> error("UNKNOWN_FIELD", "Unsupported mobile event: ${event.eventType}")
        }

        val expectedStateVersion = state.stateVersion + if (event.eventType in stateMutatingEvents) 1 else 0
        if (event.stateVersion != expectedStateVersion) error("STALE_STATE_VERSION", "Event state version is invalid")
        return state.copy(
            ledgerSequence = event.sequence,
            stateVersion = event.stateVersion,
            phase = phase,
            pendingApprovalId = pendingApproval,
            pendingEffectKey = pendingEffect,
            observations = observations,
            terminalOutcome = outcome,
        )
    }

    private fun error(code: String, message: String): Nothing = throw MobileRuntimeException(code, message)
}

class MobileRunLedger(
    runId: String,
    manifestHash: String,
) {
    private var currentState = MobileRunState(runId = runId, manifestHash = manifestHash)
    private val mutableEvents = mutableListOf<MobileRunEvent>()
    private val effectFingerprints = mutableMapOf<String, String>()

    val state: MobileRunState get() = currentState
    val events: List<MobileRunEvent> get() = mutableEvents.toList()

    fun append(
        eventType: String,
        payload: Map<String, String>,
        expectedStateVersion: Long,
        expectedLedgerSequence: Long,
    ): MobileRunEvent {
        if (expectedStateVersion != currentState.stateVersion || expectedLedgerSequence != currentState.ledgerSequence) {
            throw MobileRuntimeException("STALE_STATE_VERSION", "Append uses obsolete state or ledger version")
        }
        if (eventType == "tool.intent_recorded") recordEffectIntent(payload)
        val sequence = currentState.ledgerSequence + 1
        val stateVersion = currentState.stateVersion + if (eventType in MobileRunReducer.stateMutatingEvents) 1 else 0
        val event = MobileRunEvent(
            eventId = "event:${sequence.toString().padStart(6, '0')}",
            runId = currentState.runId,
            sequence = sequence,
            stateVersion = stateVersion,
            eventType = eventType,
            payload = payload.toMap(),
        )
        currentState = MobileRunReducer.reduce(currentState, event)
        mutableEvents += event
        return event
    }

    fun replay(): MobileRunState = mutableEvents.fold(
        MobileRunState(runId = currentState.runId, manifestHash = currentState.manifestHash),
    ) { state, event -> MobileRunReducer.reduce(state, event) }

    /** Rebuilds a run only through the same reducer and idempotency checks as live appends. */
    companion object {
        fun restore(
            runId: String,
            manifestHash: String,
            persistedEvents: List<MobileRunEvent>,
        ): MobileRunLedger {
            require(runId.matches(Regex("[A-Za-z0-9:_-]{3,160}"))) { "Invalid run ID" }
            require(manifestHash.matches(Regex("(?:sha256:)?[a-f0-9]{64}"))) { "Invalid manifest hash" }
            val ledger = MobileRunLedger(runId, manifestHash)
            persistedEvents.forEach { event ->
                val expectedId = "event:${event.sequence.toString().padStart(6, '0')}"
                if (event.eventId != expectedId) {
                    throw MobileRuntimeException("CORRUPT_EVENT", "Event ID does not match its sequence")
                }
                if (event.runId != runId) {
                    throw MobileRuntimeException("UNRESOLVED_REFERENCE", "Recovered event belongs to another run")
                }
                val rebuilt = ledger.append(
                    eventType = event.eventType,
                    payload = event.payload,
                    expectedStateVersion = ledger.state.stateVersion,
                    expectedLedgerSequence = ledger.state.ledgerSequence,
                )
                if (rebuilt != event) {
                    throw MobileRuntimeException("CORRUPT_EVENT", "Persisted event does not match deterministic reconstruction")
                }
            }
            return ledger
        }
    }

    private fun recordEffectIntent(payload: Map<String, String>) {
        val key = payload["idempotency_key"]
            ?: throw MobileRuntimeException("IDEMPOTENCY_CONFLICT", "Effect intent needs idempotency key")
        val fingerprint = payload["semantic_fingerprint"]
            ?: throw MobileRuntimeException("IDEMPOTENCY_CONFLICT", "Effect intent needs semantic fingerprint")
        val prior = effectFingerprints[key]
        if (prior != null && prior != fingerprint) {
            throw MobileRuntimeException("IDEMPOTENCY_CONFLICT", "Effect key was reused with different semantics")
        }
        if (prior != null) throw MobileRuntimeException("IDEMPOTENCY_CONFLICT", "Effect intent was already recorded")
        effectFingerprints[key] = fingerprint
    }
}
