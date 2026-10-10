package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals

class ActionPreviewTest {
    @Test fun `local write preview discloses exact local effect without recipients`() {
        val request = BoundToolRequest("proposal:note", "goal:one", "sha256:" + "a".repeat(64), 1, 3, "note.create", "1.0.0", "source:selected", emptyMap(), "save note", emptySet(), "local_draft_committed")
        val preview = ActionPreviewFactory.from(request, "Save this", listOf("selected note"))
        assertEquals(AuthenticationRequirement.BIOMETRIC_STRONG, preview.authentication)
        assertEquals(emptyList(), preview.externalRecipients)
        assertEquals(Reversibility.REQUIRES_RECONCILIATION, preview.reversibility)
    }
}
