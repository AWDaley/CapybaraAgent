package com.tervoro.tal

/** A durable source-of-truth boundary. Implementations must make append atomic. */
interface MobileRunStore {
    fun create(runId: String, manifestHash: String): MobileRunState
    fun load(runId: String): MobileRunLedger?
    fun append(
        runId: String,
        eventType: String,
        payload: Map<String, String>,
        expectedStateVersion: Long,
        expectedLedgerSequence: Long,
    ): MobileRunEvent
}

/** Test/reference implementation; production adapters must encrypt their records at rest. */
class InMemoryMobileRunStore : MobileRunStore {
    private val ledgers = mutableMapOf<String, MobileRunLedger>()

    @Synchronized
    override fun create(runId: String, manifestHash: String): MobileRunState {
        check(runId !in ledgers) { "Run already exists" }
        return MobileRunLedger(runId, manifestHash).also { ledgers[runId] = it }.state
    }

    @Synchronized
    override fun load(runId: String): MobileRunLedger? = ledgers[runId]?.let { ledger ->
        MobileRunLedger.restore(ledger.state.runId, ledger.state.manifestHash, ledger.events)
    }

    @Synchronized
    override fun append(
        runId: String,
        eventType: String,
        payload: Map<String, String>,
        expectedStateVersion: Long,
        expectedLedgerSequence: Long,
    ): MobileRunEvent {
        val ledger = ledgers[runId] ?: throw MobileRuntimeException("UNRESOLVED_REFERENCE", "Run does not exist")
        return ledger.append(eventType, payload, expectedStateVersion, expectedLedgerSequence)
    }
}
