package com.tervoro.tal

/** Normalizes selected UTF-8 text into a source record and offset-stable evidence spans. */
object DocumentProvenance {
    fun ingest(sourceRef: String, bytes: ByteArray): VaultSource {
        require(bytes.size in 1..524_288) { "Document is empty or exceeds mobile text bound" }
        require(bytes.take(512).none { it == 0.toByte() }) { "Binary document format is not supported by the text workflow" }
        val text = bytes.toString(Charsets.UTF_8).replace("\r\n", "\n").replace('\r', '\n')
        require(text.isNotBlank()) { "Document contains no text" }
        return VaultSource(sourceRef, "sha256:" + TaskManifest.sha256(bytes), text)
    }

    fun evidence(source: VaultSource, startOffset: Int, endOffset: Int): EvidenceSpan {
        require(startOffset >= 0 && endOffset in (startOffset + 1)..source.text.length) { "Evidence range is outside source" }
        val text = source.text.substring(startOffset, endOffset)
        val material = "$startOffset:$endOffset:${TaskManifest.sha256(text.toByteArray(Charsets.UTF_8))}".toByteArray(Charsets.UTF_8)
        return EvidenceSpan("evidence:" + TaskManifest.sha256(material).take(24), source.sourceRef, source.contentHash, startOffset, endOffset, text)
    }
}
