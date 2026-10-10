package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class DocumentProvenanceTest {
    @Test fun `ingestion hashes original bytes and creates offset-stable evidence`() {
        val bytes = "First line\r\nSecond line".toByteArray()
        val source = DocumentProvenance.ingest("source:document-1", bytes)
        assertEquals("First line\nSecond line", source.text)
        val evidence = DocumentProvenance.evidence(source, 0, 10)
        assertEquals("First line", evidence.text)
        assertEquals(source.contentHash, evidence.sourceHash)
    }
    @Test fun `binary document is rejected`() {
        assertFailsWith<IllegalArgumentException> { DocumentProvenance.ingest("source:document-1", byteArrayOf(1, 0, 2)) }
    }
}
