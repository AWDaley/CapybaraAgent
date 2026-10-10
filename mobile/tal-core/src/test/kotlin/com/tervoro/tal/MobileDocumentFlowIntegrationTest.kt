package com.tervoro.tal

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals

class MobileDocumentFlowIntegrationTest {
    @Test fun `offline document answer is replayable from scoped read through evidence release`() {
        val store = InMemoryMobileRunStore()
        val coordinator = MobileTaskRunCoordinator(store) { Instant.EPOCH }
        val draft = MobileTaskTemplates.compose(
            templateId = "document.answer_with_evidence",
            goal = "What does the document state?",
            sourceRefs = setOf("source:one"),
            retention = RetentionChoice.EPHEMERAL,
            requestedCapabilities = setOf("document.selected.read"),
        )
        val run = coordinator.start("run:offline-document", draft)
        val request = BoundToolRequest(
            "proposal:read", "goal:one", run.manifestHash, 1, run.state.stateVersion,
            "document.selected.read", "1.0.0", "source:one", emptyMap(), "Read selected source", emptySet(), "document_text_span",
        )
        coordinator.recordIntent(run, request, "sha256:read-one", setOf("source:one"))
        coordinator.recordToolResult(run.runId, "effect:read", succeeded = true)
        val source = DocumentProvenance.ingest("source:one", "Capybaras swim.".toByteArray())
        val span = DocumentProvenance.evidence(source, 0, source.text.length)
        coordinator.completeDocumentAnswer(
            run, draft, AnswerPackage("Capybaras swim.", listOf(EvidenceCitation(span.evidenceId, 0, 15))), listOf(span),
        )
        val restored = requireNotNull(store.load(run.runId))
        assertEquals(MobileRunPhase.COMPLETED, restored.state.phase)
        assertEquals(restored.state, restored.replay())
        assertEquals("answer_delivered", restored.state.terminalOutcome)
    }
}
