package com.tervoro.capybara.security

import android.content.Context
import com.tervoro.tal.AuditEvent
import com.tervoro.tal.AuditSink
import com.tervoro.tal.AuditTrail
import java.time.Instant
import java.io.File
import java.io.FileOutputStream
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.JsonObject

class EncryptedAuditSink(
    context: Context,
    sessionId: String,
    private val secrets: AndroidKeyStoreSecrets,
) : AuditSink {
    private val safeSessionId = sessionId.also {
        require(it.matches(Regex("[a-zA-Z0-9_-]{8,80}")))
    }
    private val directory = File(context.noBackupFilesDir, "audit/$safeSessionId").apply {
        check(mkdirs() || isDirectory) { "Unable to create private audit directory" }
    }

    @Synchronized
    override fun persist(event: AuditEvent) {
        val fileName = "event_${event.sequence.toString().padStart(6, '0')}.tal"
        val destination = File(directory, fileName)
        check(!destination.exists()) { "Append-only audit event already exists" }
        val aad = "$safeSessionId:${event.sequence}".toByteArray(Charsets.UTF_8)
        val encrypted = secrets.encrypt(event.canonicalRecord().toByteArray(Charsets.UTF_8), aad)
        val temporary = File(directory, "$fileName.tmp")
        FileOutputStream(temporary).use { stream ->
            stream.write(encrypted)
            stream.fd.sync()
        }
        check(temporary.renameTo(destination)) { "Atomic audit append failed" }
    }

    /** Returns audit history only if every encrypted event and its hash/HMAC chain verifies. */
    @Synchronized
    fun loadVerified(): List<AuditEvent> {
        val files = directory.listFiles { file -> file.name.matches(Regex("event_[0-9]{6}\\.tal")) }
            .orEmpty().sortedBy { it.name }
        val events = files.mapIndexed { index, file ->
            val sequence = index + 1L
            check(file.name == "event_${sequence.toString().padStart(6, '0')}.tal") { "Audit ledger has a sequence gap" }
            val plain = secrets.decrypt(file.readBytes(), "$safeSessionId:$sequence".toByteArray(Charsets.UTF_8)).toString(Charsets.UTF_8)
            val record = json.parseToJsonElement(plain).jsonObject
            AuditEvent(
                sequence = record.required("sequence").toLong(), eventType = record.required("event_type"),
                timestamp = Instant.parse(record.required("timestamp")), data = record["data"]!!.jsonObject,
                previousHash = record.required("previous_hash"), eventHash = record.required("event_hash"), authenticationTag = record.required("authentication_tag"),
            )
        }
        return AuditTrail.restore(events) { payload, tag -> secrets.verify(payload, tag) }.events
    }

    private fun JsonObject.required(name: String): String = this[name]?.jsonPrimitive?.content ?: error("Audit record is missing $name")
    private companion object { val json = Json { ignoreUnknownKeys = false; isLenient = false } }
}
