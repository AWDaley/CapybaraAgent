package com.tervoro.tal

import java.time.Instant
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

data class AuditEvent(
    val sequence: Long,
    val eventType: String,
    val timestamp: Instant,
    val data: JsonObject,
    val previousHash: String,
    val eventHash: String,
    val authenticationTag: String,
) {
    fun canonicalRecord(): String = CanonicalJson.encode(
        CanonicalJson.objectOf(
            "authentication_tag" to JsonPrimitive(authenticationTag),
            "data" to data,
            "event_hash" to JsonPrimitive(eventHash),
            "event_type" to JsonPrimitive(eventType),
            "previous_hash" to JsonPrimitive(previousHash),
            "sequence" to JsonPrimitive(sequence),
            "timestamp" to JsonPrimitive(timestamp.toString()),
        ),
    )
}

fun interface AuditSigner {
    fun sign(payload: ByteArray): String
}

fun interface AuditSink {
    fun persist(event: AuditEvent)
}

object NoOpAuditSink : AuditSink {
    override fun persist(event: AuditEvent) = Unit
}

class Sha256AuditSigner : AuditSigner {
    override fun sign(payload: ByteArray): String = TaskManifest.sha256(payload)
}

class AuditTrail(
    private val signer: AuditSigner = Sha256AuditSigner(),
    private val sink: AuditSink = NoOpAuditSink,
    private val now: () -> Instant = Instant::now,
) {
    private val mutableEvents = mutableListOf<AuditEvent>()
    val events: List<AuditEvent> get() = synchronized(this) { mutableEvents.toList() }

    @Synchronized
    fun append(eventType: String, data: Map<String, JsonElement> = emptyMap()): AuditEvent {
        require(eventType.matches(Regex("[a-z][a-z0-9_]{1,63}"))) { "Invalid audit event type" }
        val sequence = mutableEvents.size.toLong() + 1
        val timestamp = now()
        val previousHash = mutableEvents.lastOrNull()?.eventHash.orEmpty()
        val jsonData = JsonObject(data.toSortedMap())
        val unsigned = CanonicalJson.encode(
            CanonicalJson.objectOf(
                "data" to jsonData,
                "event_type" to JsonPrimitive(eventType),
                "previous_hash" to JsonPrimitive(previousHash),
                "sequence" to JsonPrimitive(sequence),
                "timestamp" to JsonPrimitive(timestamp.toString()),
            ),
        )
        val eventHash = TaskManifest.sha256(unsigned.toByteArray(Charsets.UTF_8))
        val tag = signer.sign(eventHash.toByteArray(Charsets.UTF_8))
        val event = AuditEvent(sequence, eventType, timestamp, jsonData, previousHash, eventHash, tag)
        sink.persist(event)
        mutableEvents += event
        return event
    }

    fun verify(signerVerifier: ((ByteArray, String) -> Boolean)? = null): Boolean = synchronized(this) {
        mutableEvents.foldIndexed(true to "") { index, (valid, priorHash), event ->
            if (!valid || event.sequence != index.toLong() + 1 || event.previousHash != priorHash) {
                false to event.eventHash
            } else {
                val unsigned = CanonicalJson.encode(
                    CanonicalJson.objectOf(
                        "data" to event.data,
                        "event_type" to JsonPrimitive(event.eventType),
                        "previous_hash" to JsonPrimitive(event.previousHash),
                        "sequence" to JsonPrimitive(event.sequence),
                        "timestamp" to JsonPrimitive(event.timestamp.toString()),
                    ),
                )
                val hashValid = TaskManifest.sha256(unsigned.toByteArray(Charsets.UTF_8)) == event.eventHash
                val tagValid = signerVerifier?.invoke(
                    event.eventHash.toByteArray(Charsets.UTF_8),
                    event.authenticationTag,
                ) ?: true
                (hashValid && tagValid) to event.eventHash
            }
        }.first
    }

    companion object {
        /** Restores only a complete, chain-valid, authenticator-valid audit history. */
        fun restore(
            events: List<AuditEvent>,
            signerVerifier: ((ByteArray, String) -> Boolean)? = null,
        ): AuditTrail {
            val restored = AuditTrail()
            synchronized(restored) { restored.mutableEvents += events }
            if (!restored.verify(signerVerifier)) {
                throw MobileRuntimeException("AUDIT_CHAIN_INVALID", "Persisted audit history failed verification")
            }
            return restored
        }
    }
}
