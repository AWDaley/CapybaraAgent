package com.tervoro.tal

import java.time.Instant

data class MobileObservation(
    val observationId: String,
    val runId: String,
    val toolId: String,
    val toolVersion: String,
    val observationType: String,
    val trustClass: String,
    val sourceRefs: Set<String>,
    val contentHash: String,
    val createdAt: Instant,
)

object MobileObservationValidator {
    private val observationTypes = setOf("document_text_span", "image_ocr_result", "evidence_bundle", "local_draft_committed", "local_task_list_committed", "verified_answer_package", "verified_summary_package")
    private val trustClasses = setOf("reported", "observed", "verified", "inferred", "conflicted")
    fun validate(observation: MobileObservation, scopedSources: Set<String>) {
        if (!observation.observationId.matches(Regex("observation:[a-z0-9._-]+")) || !observation.runId.matches(Regex("run:[a-z0-9._-]+"))) {
            throw MobileRuntimeException("TOOL_OUTPUT_INVALID", "Observation identity is invalid")
        }
        MobileToolCatalog.resolve(observation.toolId, observation.toolVersion)
        if (observation.observationType !in observationTypes || observation.trustClass !in trustClasses || observation.sourceRefs.isEmpty() || !scopedSources.containsAll(observation.sourceRefs)) {
            throw MobileRuntimeException("TOOL_OUTPUT_INVALID", "Observation type, trust, or source scope is invalid")
        }
        if (!observation.contentHash.matches(Regex("sha256:[a-f0-9]{64}"))) throw MobileRuntimeException("TOOL_OUTPUT_INVALID", "Observation content hash is invalid")
    }
}
