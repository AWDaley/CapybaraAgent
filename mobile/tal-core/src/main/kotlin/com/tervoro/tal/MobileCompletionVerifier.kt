package com.tervoro.tal

import java.time.Instant

data class VerifiedMobileCompletion(
    val completionId: String,
    val runId: String,
    val successConditionRef: String,
    val requiredObservationRefs: Set<String>,
    val outputContractHash: String,
    val verifiedAt: Instant,
    val outcome: String,
)

object MobileCompletionVerifier {
    fun verifyDocumentAnswer(
        runId: String,
        draft: TaskContractDraft,
        answer: AnswerPackage,
        evidence: Collection<EvidenceSpan>,
        now: Instant = Instant.now(),
    ): VerifiedMobileCompletion {
        if (draft.templateId != "document.answer_with_evidence" || draft.successConditionId != "answer_package_released") {
            throw MobileRuntimeException("INVALID_STATE_TRANSITION", "Task is not an evidence-backed document-answer workflow")
        }
        val errors = EvidenceReleaseGate.verify(answer, draft.sourceRefs, evidence)
        if (errors.isNotEmpty()) throw MobileRuntimeException("COMPLETION_EVIDENCE_INSUFFICIENT", errors.joinToString("; "))
        val canonicalOutput = answer.answer + "\n" + answer.citations.sortedBy { it.evidenceId }.joinToString("|") { "${it.evidenceId}:${it.claimStart}:${it.claimEnd}" }
        return VerifiedMobileCompletion(
            completionId = "completion:" + TaskManifest.sha256((runId + canonicalOutput).toByteArray()).take(24),
            runId = runId, successConditionRef = draft.successConditionId,
            requiredObservationRefs = answer.citations.map { it.evidenceId }.toSet(),
            outputContractHash = "sha256:" + TaskManifest.sha256(canonicalOutput.toByteArray()),
            verifiedAt = now, outcome = "answer_delivered",
        )
    }
}
