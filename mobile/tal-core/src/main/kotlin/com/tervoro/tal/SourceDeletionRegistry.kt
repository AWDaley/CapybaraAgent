package com.tervoro.tal

/** Tracks source-derived identifiers so source deletion can be verified as a single transaction. */
class SourceDeletionRegistry {
    private val derivatives = mutableMapOf<String, MutableSet<String>>()

    fun register(sourceRef: String, derivativeRef: String) {
        require(sourceRef.matches(Regex("source:[a-z0-9._-]+")))
        require(derivativeRef.isNotBlank() && derivativeRef.length <= 160)
        derivatives.getOrPut(sourceRef) { sortedSetOf() }.add(derivativeRef)
    }

    fun deleteSource(sourceRef: String): Set<String> = derivatives.remove(sourceRef).orEmpty().toSortedSet()
    fun hasDerivative(sourceRef: String, derivativeRef: String): Boolean = derivativeRef in derivatives[sourceRef].orEmpty()
}
