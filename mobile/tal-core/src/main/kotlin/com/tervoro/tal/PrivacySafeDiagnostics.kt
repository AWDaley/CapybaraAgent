package com.tervoro.tal

data class DiagnosticRecord(
    val code: String,
    val manifestHash: String,
    val eventCount: Int,
    val elapsedMillis: Long,
    val adapterId: String,
)

object PrivacySafeDiagnostics {
    fun create(code: String, manifestHash: String, eventCount: Int, elapsedMillis: Long, adapterId: String): DiagnosticRecord {
        require(code.matches(Regex("[A-Z0-9_]{3,80}")))
        require(manifestHash.matches(Regex("sha256:[a-f0-9]{64}")))
        require(eventCount >= 0 && elapsedMillis >= 0 && adapterId.matches(Regex("[a-z0-9._-]{1,160}")))
        return DiagnosticRecord(code, manifestHash, eventCount, elapsedMillis, adapterId)
    }
}
