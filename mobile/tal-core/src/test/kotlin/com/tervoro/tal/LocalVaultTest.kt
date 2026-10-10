package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals

class LocalVaultTest {
    @Test fun `search stays within allowed source scope and deletion removes retrieval`() {
        val vault = LocalVault()
        vault.upsert(VaultSource("source:one", "sha256:" + "1".repeat(64), "Capybaras are social swimmers."))
        vault.upsert(VaultSource("source:two", "sha256:" + "2".repeat(64), "Private medical information."))
        assertEquals(listOf("source:one"), vault.search("capybara", setOf("source:one")).map { it.sourceRef })
        assertEquals(emptyList(), vault.search("medical", setOf("source:one")))
        vault.delete("source:one")
        assertEquals(emptyList(), vault.search("capybara", setOf("source:one")))
    }
}
