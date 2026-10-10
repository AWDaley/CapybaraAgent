package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class SourceDeletionRegistryTest {
    @Test fun `source deletion returns and clears every registered derivative`() {
        val registry = SourceDeletionRegistry()
        registry.register("source:one", "chunk:1")
        registry.register("source:one", "evidence:1")
        registry.register("source:one", "cache:1")
        assertEquals(setOf("cache:1", "chunk:1", "evidence:1"), registry.deleteSource("source:one"))
        assertFalse(registry.hasDerivative("source:one", "chunk:1"))
    }
}
