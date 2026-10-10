package com.tervoro.tal

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals

class MobileProfileManifestCompilerTest {
    @Test fun `registered document task compiles to a valid hashed profile manifest`() {
        val draft = MobileTaskTemplates.compose("document.answer_with_evidence", "Answer it", setOf("source:one"), RetentionChoice.EPHEMERAL, setOf("document.selected.read"))
        val manifest = MobileProfileManifestCompiler.compile(draft, Instant.EPOCH)
        MobileProfileContract.validateManifest(manifest)
        assertEquals(MobileProfileContract.TAL_VERSION, manifest["tal_version"]!!.toString().trim('"'))
    }
}
