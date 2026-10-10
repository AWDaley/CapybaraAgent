package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class MobileRunStoreTest {
    @Test
    fun `atomic append and reload preserve the authoritative projection`() {
        val store = InMemoryMobileRunStore()
        store.create("run:store-1", "sha256:" + "b".repeat(64))
        store.append("run:store-1", "manifest.created", emptyMap(), 0, 0)
        store.append("run:store-1", "manifest.validated", emptyMap(), 1, 1)
        val restored = requireNotNull(store.load("run:store-1"))
        assertEquals(MobileRunPhase.READY, restored.state.phase)
        assertEquals(2, restored.state.stateVersion)
        assertFailsWith<MobileRuntimeException> {
            store.append("run:store-1", "capability.computed", emptyMap(), 1, 1)
        }
    }
}
