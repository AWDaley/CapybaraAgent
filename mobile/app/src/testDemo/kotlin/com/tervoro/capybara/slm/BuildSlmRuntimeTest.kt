package com.tervoro.capybara.slm

import com.tervoro.tal.Proposal
import com.tervoro.tal.ProposalParser
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class BuildSlmRuntimeTest {
    private fun produce(goal: String): Proposal = runBlocking {
        val runtime = createDeterministicDemoRuntime()
        runtime.initialize()
        try {
            ProposalParser.parse(
                runtime.generate("goal=$goal\n<untrusted_observation>none</untrusted_observation>"),
            )
        } finally {
            runtime.close()
        }
    }

    @Test
    fun documentTasksProduceStrictActionJSON() {
        val proposal = assertIs<Proposal.Action>(produce("Summarize the selected document"))
        assertEquals("document.selected.read", proposal.toolName)
        assertTrue(proposal.arguments.isEmpty())
    }

    @Test
    fun notesUseDistinctIdempotencyKeysForDistinctGoals() {
        val a = assertIs<Proposal.Action>(produce("remember that the code is 123"))
        val b = assertIs<Proposal.Action>(produce("remember that the code is 456"))
        val retry = assertIs<Proposal.Action>(produce("remember that the code is 123"))
        val firstKey = a.arguments["idempotency_key"].toString()
        assertNotEquals(firstKey, b.arguments["idempotency_key"].toString())
        assertEquals(firstKey, retry.arguments["idempotency_key"].toString())
    }

    @Test
    fun generalGoalCompletesUnderClosedProposalParser() {
        assertIs<Proposal.Complete>(produce("Say hello"))
    }

    @Test
    fun clockReadsUseAuthorizedToolName() {
        val proposal = assertIs<Proposal.Action>(produce("tell me the time"))
        assertEquals("current_time", proposal.toolName)
    }
}
