package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class EvidenceReleaseGateTest {
    private val span = EvidenceSpan("evidence:one", "source:document-1", "sha256:" + "e".repeat(64), 0, 15, "Capybaras swim.")
    @Test fun `evidence-backed answer can be released`() {
        val answer = "Capybaras swim."
        assertTrue(EvidenceReleaseGate.verify(AnswerPackage(answer, listOf(EvidenceCitation("evidence:one", 0, answer.length))), setOf("source:document-1"), listOf(span)).isEmpty())
    }
    @Test fun `uncited or out-of-scope claims fail closed`() {
        assertTrue(EvidenceReleaseGate.verify(AnswerPackage("Capybaras swim.", emptyList()), setOf("source:document-1"), listOf(span)).isNotEmpty())
        val errors = EvidenceReleaseGate.verify(AnswerPackage("Capybaras swim.", listOf(EvidenceCitation("evidence:one", 0, 15))), emptySet(), listOf(span))
        assertEquals(true, errors.any { it.contains("outside manifest scope") })
    }
}
