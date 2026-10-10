package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class PrivacySafeDiagnosticsTest {
    @Test fun `diagnostic accepts codes hashes counts timings and adapter only`() {
        val record = PrivacySafeDiagnostics.create("TAL_BUDGET_TIME", "sha256:" + "a".repeat(64), 4, 100, "litert.local")
        assertEquals("TAL_BUDGET_TIME", record.code)
        assertFailsWith<IllegalArgumentException> { PrivacySafeDiagnostics.create("raw user prompt", "sha256:" + "a".repeat(64), 1, 1, "adapter") }
    }
}
