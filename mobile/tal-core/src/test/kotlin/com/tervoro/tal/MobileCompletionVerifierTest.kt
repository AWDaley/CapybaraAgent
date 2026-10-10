package com.tervoro.tal

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class MobileCompletionVerifierTest {
    private val source = VaultSource("source:one", "sha256:" + "a".repeat(64), "Capybaras swim.")
    private val span = DocumentProvenance.evidence(source, 0, source.text.length)
    private val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "What can it do?", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
    @Test fun `verified document answer creates deterministic completion`() {
        val answer = AnswerPackage("Capybaras swim.", listOf(EvidenceCitation(span.evidenceId, 0, 15)))
        val completion = MobileCompletionVerifier.verifyDocumentAnswer("run:one", draft, answer, listOf(span), Instant.EPOCH)
        assertEquals("answer_delivered", completion.outcome)
        assertEquals("answer_package_released", completion.successConditionRef)
    }
    @Test fun `uncited answer cannot become a completion`() {
        assertFailsWith<MobileRuntimeException> { MobileCompletionVerifier.verifyDocumentAnswer("run:one", draft, AnswerPackage("Capybaras swim.", emptyList()), listOf(span)) }
    }
}
