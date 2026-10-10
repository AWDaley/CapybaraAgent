package com.tervoro.tal

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertFailsWith

class MobileObservationValidatorTest {
    @Test fun `observation rejects invented tool or source scope`() {
        val valid = MobileObservation("observation:one", "run:one", "document.selected.read", "1.0.0", "document_text_span", "observed", setOf("source:one"), "sha256:" + "a".repeat(64), Instant.EPOCH)
        MobileObservationValidator.validate(valid, setOf("source:one"))
        assertFailsWith<MobileRuntimeException> { MobileObservationValidator.validate(valid.copy(sourceRefs = setOf("source:other")), setOf("source:one")) }
        assertFailsWith<MobileRuntimeException> { MobileObservationValidator.validate(valid.copy(toolId = "invented.tool"), setOf("source:one")) }
    }
}
