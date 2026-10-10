package com.tervoro.capybara.security

import android.content.Context
import com.tervoro.tal.MobileRunEvent
import com.tervoro.tal.MobileRunLedger
import com.tervoro.tal.MobileRunState
import com.tervoro.tal.MobileRunStore
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.FileOutputStream

/**
 * Encrypted, atomic snapshot adapter for the durable run-store contract.  Each
 * write authenticates the whole ledger and restores it through MobileRunLedger,
 * which rejects bad sequence, state-version, or idempotency history.
 */
class EncryptedMobileRunStore(context: Context, private val secrets: AndroidKeyStoreSecrets) : MobileRunStore {
    private val directory = File(context.noBackupFilesDir, "runs").apply {
        check(mkdirs() || isDirectory) { "Unable to create private run directory" }
    }

    @Synchronized
    override fun create(runId: String, manifestHash: String): MobileRunState {
        check(!file(runId).exists()) { "Run already exists" }
        val ledger = MobileRunLedger(runId, manifestHash)
        persist(ledger)
        return ledger.state
    }

    @Synchronized
    override fun load(runId: String): MobileRunLedger? {
        val source = file(runId)
        if (!source.isFile) return null
        val plain = secrets.decrypt(source.readBytes(), aad(runId)).toString(Charsets.UTF_8)
        val root = json.parseToJsonElement(plain).jsonObject
        check(root.requiredString("ledger_version") == "1") { "Unsupported encrypted run ledger version" }
        check(root.requiredString("run_id") == runId) { "Encrypted run record is bound to another run" }
        val manifestHash = root.requiredString("manifest_hash")
        val events = root["events"]!!.jsonArray.map { item ->
            val event = item.jsonObject
            MobileRunEvent(
                eventId = event.requiredString("event_id"), runId = event.requiredString("run_id"),
                sequence = event.requiredString("sequence").toLong(), stateVersion = event.requiredString("state_version").toLong(),
                eventType = event.requiredString("event_type"),
                payload = event["payload"]!!.jsonObject.mapValues { (_, value) -> value.jsonPrimitive.content },
            )
        }
        return MobileRunLedger.restore(runId, manifestHash, events)
    }

    @Synchronized
    override fun append(runId: String, eventType: String, payload: Map<String, String>, expectedStateVersion: Long, expectedLedgerSequence: Long): MobileRunEvent {
        val ledger = load(runId) ?: error("Run does not exist")
        val event = ledger.append(eventType, payload, expectedStateVersion, expectedLedgerSequence)
        persist(ledger)
        return event
    }

    private fun persist(ledger: MobileRunLedger) {
        val root = buildJsonObject {
            put("ledger_version", JsonPrimitive(1))
            put("manifest_hash", JsonPrimitive(ledger.state.manifestHash))
            put("run_id", JsonPrimitive(ledger.state.runId))
            put("events", buildJsonArray {
                ledger.events.forEach { event -> add(buildJsonObject {
                    put("event_id", JsonPrimitive(event.eventId)); put("run_id", JsonPrimitive(event.runId))
                    put("sequence", JsonPrimitive(event.sequence)); put("state_version", JsonPrimitive(event.stateVersion))
                    put("event_type", JsonPrimitive(event.eventType)); put("payload", JsonObject(event.payload.toSortedMap().mapValues { JsonPrimitive(it.value) }))
                }) }
            })
        }
        val target = file(ledger.state.runId)
        val temporary = File(directory, "${target.name}.tmp")
        val encrypted = secrets.encrypt(root.toString().toByteArray(Charsets.UTF_8), aad(ledger.state.runId))
        FileOutputStream(temporary).use { output -> output.write(encrypted); output.fd.sync() }
        check(temporary.renameTo(target)) { "Atomic run snapshot commit failed" }
    }

    private fun file(runId: String): File {
        require(runId.matches(Regex("[A-Za-z0-9:_-]{3,160}"))) { "Invalid run ID" }
        return File(directory, "$runId.tal")
    }
    private fun aad(runId: String) = "tervoro-run-v1:$runId".toByteArray(Charsets.UTF_8)
    private fun JsonObject.requiredString(key: String): String = this[key]?.jsonPrimitive?.content ?: error("Corrupt encrypted run record")
    private companion object { val json = Json { ignoreUnknownKeys = false; isLenient = false } }
}
