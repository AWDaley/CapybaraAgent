package com.tervoro.tal

import java.time.Instant
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class ProfileRun(val runId: String, val manifestHash: String, val manifest: kotlinx.serialization.json.JsonObject, val state: MobileRunState)

/** Profile-native orchestration boundary; tool adapters never mutate the ledger directly. */
class MobileTaskRunCoordinator(private val store: MobileRunStore, private val now: () -> Instant = Instant::now) {
    fun start(runId: String, draft: TaskContractDraft): ProfileRun {
        val manifest = MobileProfileManifestCompiler.compile(draft, now())
        val hash = manifest["integrity"]!!.jsonObject["manifest_hash"]!!.jsonPrimitive.content
        store.create(runId, hash)
        append(runId, "manifest.created", emptyMap())
        append(runId, "manifest.validated", emptyMap())
        append(runId, "capability.computed", emptyMap())
        return ProfileRun(runId, hash, manifest, requireNotNull(store.load(runId)).state)
    }

    fun recordIntent(run: ProfileRun, request: BoundToolRequest, fingerprint: String, scopedTargets: Set<String>, approval: MobileApprovalRecord? = null): MobileRunEvent {
        val ledger = requireNotNull(store.load(run.runId))
        MobileActionAuthorization.authorize(request, ledger.state, MobileToolCatalog.enabledIds(), scopedTargets, now().toEpochMilli(), approval)
        return append(run.runId, "tool.intent_recorded", mapOf("idempotency_key" to "effect:${request.proposalId.removePrefix("proposal:")}", "semantic_fingerprint" to fingerprint))
    }

    fun recordToolResult(runId: String, idempotencyKey: String, succeeded: Boolean): MobileRunEvent =
        append(runId, if (succeeded) "tool.succeeded" else "tool.failed", mapOf("idempotency_key" to idempotencyKey))

    fun restoreAfterProcessDeath(runId: String): MobileRunState {
        append(runId, "lifecycle.process_restored", emptyMap())
        return requireNotNull(store.load(runId)).state
    }

    fun cancel(runId: String): MobileRunEvent = append(runId, "run.cancelled", emptyMap())

    fun requestApproval(runId: String, approvalId: String): MobileRunEvent =
        append(runId, "approval.requested", mapOf("approval_id" to approvalId))

    fun resolveApproval(runId: String, approvalId: String, approved: Boolean): MobileRunEvent =
        append(runId, if (approved) "approval.granted" else "approval.denied", mapOf("approval_id" to approvalId))

    fun recordPermissionRevoked(runId: String): MobileRunEvent =
        append(runId, "lifecycle.permission_revoked", emptyMap())

    fun completeDocumentAnswer(
        run: ProfileRun,
        draft: TaskContractDraft,
        answer: AnswerPackage,
        evidence: Collection<EvidenceSpan>,
    ): VerifiedMobileCompletion {
        val completion = MobileCompletionVerifier.verifyDocumentAnswer(run.runId, draft, answer, evidence, now())
        completion.requiredObservationRefs.forEach { observationId ->
            append(run.runId, "observation.recorded", mapOf("observation_id" to observationId))
        }
        append(run.runId, "completion.proposed", emptyMap())
        append(run.runId, "completion.verified", mapOf("outcome" to completion.outcome))
        append(run.runId, "run.completed", mapOf("outcome" to completion.outcome))
        return completion
    }

    private fun append(runId: String, eventType: String, payload: Map<String, String>): MobileRunEvent {
        val state = requireNotNull(store.load(runId)).state
        return store.append(runId, eventType, payload, state.stateVersion, state.ledgerSequence)
    }
}
