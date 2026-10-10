package com.tervoro.tal

/** Deterministic, scope-filtered lexical retrieval reference implementation. */
data class VaultSource(val sourceRef: String, val contentHash: String, val text: String) {
    init { require(sourceRef.matches(Regex("source:[a-z0-9._-]+"))); require(contentHash.matches(Regex("sha256:[a-f0-9]{64}"))) }
}
data class VaultChunk(val sourceRef: String, val contentHash: String, val startOffset: Int, val endOffset: Int, val text: String)

class LocalVault(private val chunkSize: Int = 600) {
    private val sources = linkedMapOf<String, VaultSource>()
    init { require(chunkSize in 128..2_048) }
    fun upsert(source: VaultSource) { sources[source.sourceRef] = source }
    fun delete(sourceRef: String) { sources.remove(sourceRef) }
    fun search(query: String, allowedSources: Set<String>, maximumItems: Int = 12): List<VaultChunk> {
        require(maximumItems in 1..12)
        val terms = query.lowercase().split(Regex("\\s+")).filter { it.length >= 2 }.toSet()
        if (terms.isEmpty()) return emptyList()
        return sources.values.asSequence().filter { it.sourceRef in allowedSources }.flatMap { source -> chunks(source).asSequence() }
            .map { chunk -> chunk to terms.count { term -> chunk.text.lowercase().contains(term) } }
            .filter { it.second > 0 }.sortedWith(compareByDescending<Pair<VaultChunk, Int>> { it.second }.thenBy { it.first.sourceRef }.thenBy { it.first.startOffset })
            .take(maximumItems).map { it.first }.toList()
    }
    private fun chunks(source: VaultSource): List<VaultChunk> = buildList {
        var start = 0
        while (start < source.text.length) {
            val end = minOf(source.text.length, start + chunkSize)
            add(VaultChunk(source.sourceRef, source.contentHash, start, end, source.text.substring(start, end)))
            start = end
        }
    }
}
