package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertFailsWith
import kotlinx.serialization.json.JsonPrimitive

class MobileActionAuthorizationTest {
    @Test fun `bound action rejects stale scope and mismatched approval`() {
        val state = MobileRunState("run:auth", "sha256:" + "f".repeat(64), stateVersion = 4)
        val request = BoundToolRequest("proposal:one", "goal:one", state.manifestHash, 1, 4, "note.create", "1.0.0", "source:selected", mapOf("maximum_items" to JsonPrimitive(1)), "save", emptySet(), "local_draft_committed")
        assertFailsWith<MobileRuntimeException> { MobileActionAuthorization.authorize(request, state, setOf("note.create"), setOf("source:selected"), 10) }
        val bad = MobileApprovalRecord("approval:one", state.manifestHash, 3, "note.create", "source:selected", "sha256:" + "0".repeat(64), 20, true)
        assertFailsWith<MobileRuntimeException> { MobileActionAuthorization.authorize(request, state, setOf("note.create"), setOf("source:selected"), 10, bad) }
    }
}
