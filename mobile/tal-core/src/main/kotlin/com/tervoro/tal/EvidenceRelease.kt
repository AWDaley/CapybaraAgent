package com.tervoro.tal

/** Immutable provenance for a visible span in a source the manifest authorized. */
data class EvidenceSpan(
    val evidenceId: String,
    val sourceRef: String,
    val sourceHash: String,
    val startOffset: Int,
    val endOffset: Int,
    val text: String,
) {
    init {
        require(evidenceId.matches(Regex("evidence:[a-z0-9._-]+")))
        require(sourceRef.isNotBlank() && sourceHash.matches(Regex("sha256:[a-f0-9]{64}")))
        require(startOffset >= 0 && endOffset > startOffset && endOffset - startOffset == text.length)
    }
}

data class EvidenceCitation(val evidenceId: String, val claimStart: Int, val claimEnd: Int)
data class AnswerPackage(val answer: String, val citations: List<EvidenceCitation>)

/** Terminal release gate for the selected-document answer workflow. */
object EvidenceReleaseGate {
    fun verify(
        answer: AnswerPackage,
        allowedSourceRefs: Set<String>,
        evidence: Collection<EvidenceSpan>,
    ): List<String> = buildList {
        if (answer.answer.isBlank()) add("answer is empty")
        if (answer.answer.length > 8_192) add("answer exceeds mobile output limit")
        val byId = evidence.associateBy { it.evidenceId }
        val claimedIntervals = mutableListOf<IntRange>()
        answer.citations.forEach { citation ->
            val span = byId[citation.evidenceId]
            if (span == null) add("citation references unknown evidence: ${citation.evidenceId}")
            else if (span.sourceRef !in allowedSourceRefs) add("citation source is outside manifest scope: ${span.sourceRef}")
            if (citation.claimStart < 0 || citation.claimEnd > answer.answer.length || citation.claimEnd <= citation.claimStart) {
                add("citation has invalid answer offsets: ${citation.evidenceId}")
            } else claimedIntervals += citation.claimStart until citation.claimEnd
        }
        if (answer.citations.isEmpty()) add("answer has no evidence citations")
        materialClaimRanges(answer.answer).forEach { claim ->
            if (claimedIntervals.none { interval -> interval.first <= claim.first && interval.last >= claim.last }) {
                add("material claim lacks a complete evidence citation")
            }
        }
    }

    private fun materialClaimRanges(answer: String): List<IntRange> {
        val ranges = mutableListOf<IntRange>()
        var start = 0
        answer.forEachIndexed { index, char ->
            if (char in ".!?\n") {
                val trimmedStart = answer.indexOfFirstNonWhitespace(start, index)
                val trimmedEnd = answer.indexOfLastNonWhitespace(start, index)
                if (trimmedStart != null && trimmedEnd != null) ranges += trimmedStart..trimmedEnd
                start = index + 1
            }
        }
        val trimmedStart = answer.indexOfFirstNonWhitespace(start, answer.length)
        val trimmedEnd = answer.indexOfLastNonWhitespace(start, answer.length)
        if (trimmedStart != null && trimmedEnd != null) ranges += trimmedStart..trimmedEnd
        return ranges
    }

    private fun String.indexOfFirstNonWhitespace(from: Int, until: Int): Int? =
        (from until until).firstOrNull { !this[it].isWhitespace() }
    private fun String.indexOfLastNonWhitespace(from: Int, until: Int): Int? =
        (from until until).lastOrNull { !this[it].isWhitespace() }
}
