package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class MobileToolCatalogTest {
    @Test fun `catalog resolves only certified local tool versions`() {
        assertEquals(EffectClass.READ, MobileToolCatalog.resolve("document.selected.read", "1.0.0").effect)
        assertFailsWith<MobileRuntimeException> { MobileToolCatalog.resolve("cloud_model.request", "1.0.0") }
        assertFailsWith<MobileRuntimeException> { MobileToolCatalog.resolve("note.create", "2.0.0") }
    }
}
