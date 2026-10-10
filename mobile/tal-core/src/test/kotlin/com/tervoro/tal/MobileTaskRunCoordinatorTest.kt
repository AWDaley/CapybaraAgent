package com.tervoro.tal

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.serialization.json.JsonPrimitive

class MobileTaskRunCoordinatorTest {
    @Test fun `profile coordinator writes manifest and intent before local effect`() {
        val store = InMemoryMobileRunStore()
        val coordinator = MobileTaskRunCoordinator(store) { Instant.EPOCH }
        val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "Answer", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
        val run = coordinator.start("run:coordinator", draft)
        assertEquals(MobileRunPhase.READY, run.state.phase)
        val request = BoundToolRequest("proposal:read", "goal:one", run.manifestHash, 1, run.state.stateVersion, "document.selected.read", "1.0.0", "source:one", mapOf("maximum_items" to JsonPrimitive(1)), "read", emptySet(), "document_text_span")
        val intent = coordinator.recordIntent(run, request, "sha256:read", setOf("source:one"))
        assertEquals("tool.intent_recorded", intent.eventType)
        assertEquals(MobileRunPhase.WAITING_FOR_TOOL, requireNotNull(store.load(run.runId)).state.phase)
    }

    @Test fun `verified answer reaches durable terminal completion`() {
        val store = InMemoryMobileRunStore()
        val coordinator = MobileTaskRunCoordinator(store) { Instant.EPOCH }
        val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "Answer", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
        val run = coordinator.start("run:answer", draft)
        val source = VaultSource("source:one", "sha256:" + "b".repeat(64), "Capybaras swim.")
        val span = DocumentProvenance.evidence(source, 0, source.text.length)
        coordinator.completeDocumentAnswer(run, draft, AnswerPackage("Capybaras swim.", listOf(EvidenceCitation(span.evidenceId, 0, 15))), listOf(span))
        assertEquals(MobileRunPhase.COMPLETED, requireNotNull(store.load(run.runId)).state.phase)
    }

    @Test fun `process restoration preserves pending effect and cancellation is durable`() {
        val store = InMemoryMobileRunStore()
        val coordinator = MobileTaskRunCoordinator(store) { Instant.EPOCH }
        val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "Answer", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
        val run = coordinator.start("run:restore", draft)
        val request = BoundToolRequest("proposal:read", "goal:one", run.manifestHash, 1, run.state.stateVersion, "document.selected.read", "1.0.0", "source:one", emptyMap(), "read", emptySet(), "document_text_span")
        coordinator.recordIntent(run, request, "sha256:read", setOf("source:one"))
        val restored = coordinator.restoreAfterProcessDeath(run.runId)
        assertEquals(MobileRunPhase.WAITING_FOR_TOOL, restored.phase)
        assertEquals("effect:read", restored.pendingEffectKey)
        coordinator.cancel(run.runId)
        assertEquals(MobileRunPhase.CANCELLED, requireNotNull(store.load(run.runId)).state.phase)
    }

    @Test fun `approval transition is durable before a protected action`() {
        val store = InMemoryMobileRunStore()
        val coordinator = MobileTaskRunCoordinator(store) { Instant.EPOCH }
        val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "Answer", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
        val run = coordinator.start("run:approval", draft)
        coordinator.requestApproval(run.runId, "approval:write")
        assertEquals(MobileRunPhase.WAITING_FOR_APPROVAL, requireNotNull(store.load(run.runId)).state.phase)
        coordinator.resolveApproval(run.runId, "approval:write", approved = true)
        assertEquals(MobileRunPhase.READY, requireNotNull(store.load(run.runId)).state.phase)
    }

    @Test fun `permission revocation blocks an active run safely`() {
        val store = InMemoryMobileRunStore()
        val coordinator = MobileTaskRunCoordinator(store) { Instant.EPOCH }
        val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "Answer", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
        val run = coordinator.start("run:permission", draft)
        coordinator.recordPermissionRevoked(run.runId)
        assertEquals(MobileRunPhase.WAITING_FOR_INFORMATION, requireNotNull(store.load(run.runId)).state.phase)
    }
}
