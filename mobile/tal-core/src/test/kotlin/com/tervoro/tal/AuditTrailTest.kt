package com.tervoro.tal

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.assertFailsWith
import kotlinx.serialization.json.JsonPrimitive

class AuditTrailTest {
    @Test
    fun `events form a deterministic append-only hash chain`() {
        val persisted = mutableListOf<AuditEvent>()
        val trail = AuditTrail(
            sink = AuditSink { persisted += it },
            now = { Instant.parse("2026-08-30T12:00:00Z") },
        )

        val first = trail.append("task_started", mapOf("goal" to JsonPrimitive("test")))
        val second = trail.append("task_completed", mapOf("answer" to JsonPrimitive("ok")))

        assertEquals(first.eventHash, second.previousHash)
        assertEquals(2, persisted.size)
        assertTrue(trail.verify())
    }

    @Test
    fun `restoration rejects a tampered audit event`() {
        val trail = AuditTrail(now = { Instant.parse("2026-08-30T12:00:00Z") })
        val event = trail.append("task_started", mapOf("goal" to JsonPrimitive("test")))
        val tampered = event.copy(previousHash = "altered")
        assertFailsWith<MobileRuntimeException> { AuditTrail.restore(listOf(tampered)) }
    }
}
