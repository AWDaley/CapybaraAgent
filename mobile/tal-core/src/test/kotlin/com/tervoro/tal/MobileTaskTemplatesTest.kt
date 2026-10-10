package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class MobileTaskTemplatesTest {
    @Test fun `document task contract is source-scoped and template-bound`() {
        val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "What does it say?", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
        assertEquals("answer_package_released", draft.successConditionId)
        assertEquals(RetentionChoice.EPHEMERAL, draft.retention)
    }
    @Test fun `template rejects invented capability or missing source`() {
        assertFailsWith<MobileRuntimeException> { MobileTaskTemplates.compose("document.summary", "Summarize", emptySet(), RetentionChoice.VAULT, emptySet()) }
        assertFailsWith<MobileRuntimeException> { MobileTaskTemplates.compose("document.summary", "Summarize", setOf("source:one"), RetentionChoice.VAULT, setOf("cloud_model.request")) }
    }
}
