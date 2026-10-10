package com.tervoro.tal

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class TaskManifestTest {
    @Test
    fun `sha256 encoding matches the standard known vector`() {
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            TaskManifest.sha256("abc".toByteArray()),
        )
    }

    @Test
    fun `hash is deterministic and excludes run timestamp`() {
        val first = TaskManifest.compile(
            goal = "  Save a note  ",
            availableTools = setOf("save_note", "current_time"),
            requestedTools = setOf("save_note"),
            createdAt = Instant.parse("2026-01-01T00:00:00Z"),
        )
        val second = TaskManifest.compile(
            goal = "Save a note",
            availableTools = setOf("current_time", "save_note"),
            requestedTools = setOf("save_note"),
            createdAt = Instant.parse("2026-08-30T12:00:00Z"),
        )

        assertEquals(first.manifestHash, second.manifestHash)
        assertEquals(first.manifestId, second.manifestId)
        assertTrue(first.verifyIntegrity())
    }

    @Test
    fun `requested unavailable capabilities are denied rather than granted`() {
        val manifest = TaskManifest.compile(
            goal = "Do something",
            availableTools = setOf("current_time"),
            requestedTools = setOf("current_time", "network_request"),
        )

        assertEquals(setOf("current_time"), manifest.capabilities.effective)
        assertEquals("CAPABILITY_UNAVAILABLE", manifest.capabilities.denied["network_request"])
        assertFalse(manifest.capabilities.permits("network_request"))
    }
}
