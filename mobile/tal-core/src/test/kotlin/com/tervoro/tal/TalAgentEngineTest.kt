package com.tervoro.tal

import java.util.ArrayDeque
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonElement

class TalAgentEngineTest {
    @Test
    fun `approved verified write can complete`() = runTest {
        val runtime = FakeRuntime(
            """{"type":"action","thought":"save","tool":"save_note","args":{"value":"hello"}}""",
            """{"type":"complete","thought":"verified","final_answer":"Saved locally"}""",
        )
        val approvals = mutableListOf<ApprovalRequest>()
        val engine = TalAgentEngine(
            runtime = runtime,
            tools = listOf(VerifiedWriteTool()),
            approvalHandler = ApprovalHandler {
                approvals += it
                ApprovalDecision.APPROVED
            },
        )

        val result = engine.runGoal("save hello")

        assertIs<EngineResult.Completed>(result)
        assertEquals("Saved locally", result.answer)
        assertEquals(1, approvals.size)
        assertTrue(approvals.single().matches(
            manifestHash = result.manifest.manifestHash,
            stateVersion = 1,
            toolName = "save_note",
            arguments = mapOf("value" to kotlinx.serialization.json.JsonPrimitive("hello")),
        ))
    }

    @Test
    fun `denied write cannot be converted into successful completion text`() = runTest {
        val runtime = FakeRuntime(
            """{"type":"action","thought":"save","tool":"save_note","args":{"value":"hello"}}""",
            """{"type":"complete","thought":"claim done","final_answer":"Saved"}""",
            """{"type":"escalate","thought":"denied","reason":"User denied the required write","context":""}""",
        )
        val events = mutableListOf<AuditEvent>()
        val engine = TalAgentEngine(
            runtime = runtime,
            tools = listOf(VerifiedWriteTool()),
            approvalHandler = ApprovalHandler { ApprovalDecision.DENIED },
            onEvent = { events += it },
        )

        val result = engine.runGoal("save hello")

        assertIs<EngineResult.Escalated>(result)
        assertTrue(events.any { it.eventType == "verification_run" && it.data["passed"].toString() == "false" })
    }

    @Test
    fun `inference that exceeds the remaining task budget escalates deterministically`() = runTest {
        val engine = TalAgentEngine(
            runtime = object : LocalSlmRuntime {
                override val displayName = "slow fake"
                override val isReady = true
                override suspend fun initialize(modelPath: String?) = Unit
                override suspend fun generate(prompt: String): String {
                    delay(1_001)
                    return """{\"type\":\"complete\",\"thought\":\"late\",\"final_answer\":\"too late\"}"""
                }
            },
            tools = emptyList(),
            approvalHandler = ApprovalHandler { ApprovalDecision.APPROVED },
        )

        val result = engine.runGoal("answer", budget = BudgetLimits(maxTimeMillis = 1_000))

        assertIs<EngineResult.Escalated>(result)
        assertEquals("TAL_BUDGET_TIME", result.stableErrorCode)
    }

    private class FakeRuntime(vararg responses: String) : LocalSlmRuntime {
        private val responses = ArrayDeque(responses.toList())
        override val displayName = "fake"
        override val isReady = true
        override suspend fun initialize(modelPath: String?) = Unit
        override suspend fun generate(prompt: String): String = responses.removeFirst()
    }

    private class VerifiedWriteTool : TalTool {
        override val definition = ToolDefinition(
            name = "save_note",
            description = "save",
            effect = EffectClass.WRITE,
            approvalPolicy = ApprovalPolicy.CONFIRM,
            allowedPhases = setOf(ExecutionPhase.EXECUTION, ExecutionPhase.RECOVERY),
            schema = mapOf("value" to ParamRule(ValueType.STRING)),
        )

        override suspend fun execute(arguments: Map<String, JsonElement>) = ToolResult(
            success = true,
            output = "read-back matched",
            independentlyVerified = true,
        )
    }
}
