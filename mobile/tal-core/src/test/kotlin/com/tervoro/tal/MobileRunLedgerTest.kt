package com.tervoro.tal

import java.io.File
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class MobileRunLedgerTest {
    @Test
    fun `replays the shared document answer fixture exactly`() {
        val fixtureDir = File(requireNotNull(System.getProperty("tervoro.fixtureDir")))
        val fixture = StrictJson.parseToJsonElement(
            File(fixtureDir, "document-answer-replay.json").readText(),
        ).jsonObject
        val ledger = MobileRunLedger(
            runId = fixture["run_id"]!!.jsonPrimitive.content,
            manifestHash = fixture["manifest_hash"]!!.jsonPrimitive.content,
        )
        fixture["events"]!!.jsonArray.forEach { element ->
            val instruction = element.jsonObject
            ledger.append(
                eventType = instruction["event_type"]!!.jsonPrimitive.content,
                payload = instruction.payloadStrings(),
                expectedStateVersion = ledger.state.stateVersion,
                expectedLedgerSequence = ledger.state.ledgerSequence,
            )
        }
        val expected = fixture["expected_state"]!!.jsonObject
        assertEquals(expected["ledger_sequence"]!!.jsonPrimitive.content.toLong(), ledger.state.ledgerSequence)
        assertEquals(expected["state_version"]!!.jsonPrimitive.content.toLong(), ledger.state.stateVersion)
        assertEquals(MobileRunPhase.COMPLETED, ledger.state.phase)
        assertEquals(listOf("observation:document-span-1"), ledger.state.observations)
        assertEquals("answer_delivered", ledger.state.terminalOutcome)
        assertEquals(ledger.state, ledger.replay())
    }

    @Test
    fun `stale append and duplicate effect intent fail closed`() {
        val ledger = MobileRunLedger("run:effect-1", "sha256:" + "a".repeat(64))
        ledger.append("manifest.created", emptyMap(), 0, 0)
        assertFailsWith<MobileRuntimeException> {
            ledger.append("manifest.validated", emptyMap(), 0, 1)
        }
        ledger.append("manifest.validated", emptyMap(), 1, 1)
        ledger.append(
            "tool.intent_recorded",
            mapOf("idempotency_key" to "effect:once", "semantic_fingerprint" to "sha256:one"),
            2,
            2,
        )
        ledger.append("tool.succeeded", mapOf("idempotency_key" to "effect:once"), 3, 3)
        val error = assertFailsWith<MobileRuntimeException> {
            ledger.append(
                "tool.intent_recorded",
                mapOf("idempotency_key" to "effect:once", "semantic_fingerprint" to "sha256:one"),
                4,
                4,
            )
        }
        assertEquals("IDEMPOTENCY_CONFLICT", error.stableErrorCode)
    }

    @Test
    fun `restored ledger rejects a tampered deterministic event`() {
        val manifestHash = "sha256:" + "a".repeat(64)
        val ledger = MobileRunLedger("run:restore", manifestHash)
        ledger.append("manifest.created", emptyMap(), 0, 0)
        ledger.append("manifest.validated", emptyMap(), 1, 1)

        val recovered = MobileRunLedger.restore("run:restore", manifestHash, ledger.events)
        assertEquals(ledger.state, recovered.state)

        val tampered = ledger.events.toMutableList().also { events ->
            events[1] = events[1].copy(stateVersion = 99)
        }
        val error = assertFailsWith<MobileRuntimeException> {
            MobileRunLedger.restore("run:restore", manifestHash, tampered)
        }
        assertEquals("CORRUPT_EVENT", error.stableErrorCode)
    }

    @Test
    fun `completion terminal event is accepted only after verification`() {
        val ledger = MobileRunLedger("run:complete-event", "sha256:" + "c".repeat(64))
        ledger.append("manifest.created", emptyMap(), 0, 0)
        ledger.append("manifest.validated", emptyMap(), 1, 1)
        ledger.append("completion.proposed", emptyMap(), 2, 2)
        ledger.append("completion.verified", mapOf("outcome" to "answer_delivered"), 3, 3)
        ledger.append("run.completed", emptyMap(), 4, 4)
        assertEquals(MobileRunPhase.COMPLETED, ledger.state.phase)
        assertEquals("answer_delivered", ledger.state.terminalOutcome)
    }

    private fun JsonObject.payloadStrings(): Map<String, String> =
        (this["payload"] as? JsonObject).orEmpty().mapValues { (_, value) -> value.jsonPrimitive.content }
}
