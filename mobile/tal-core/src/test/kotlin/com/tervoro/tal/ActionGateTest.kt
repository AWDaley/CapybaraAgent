package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

class ActionGateTest {
    private val writeTool = object : TalTool {
        override val definition = ToolDefinition(
            name = "save_note",
            description = "save",
            effect = EffectClass.WRITE,
            approvalPolicy = ApprovalPolicy.CONFIRM,
            allowedPhases = setOf(ExecutionPhase.EXECUTION),
            schema = mapOf("value" to ParamRule(ValueType.STRING, maxLength = 20)),
        )

        override suspend fun execute(arguments: Map<String, JsonElement>) = ToolResult(true, "ok", true)
    }

    @Test
    fun `write action is permitted only with approval`() {
        val manifest = TaskManifest.compile("save", setOf("save_note"))
        val result = ActionGate(listOf(writeTool)).evaluate(
            Proposal.Action("", "save_note", mapOf("value" to JsonPrimitive("hello"))),
            manifest,
            ExecutionPhase.EXECUTION,
        )

        assertTrue(result.allowed)
        assertTrue(result.requiresApproval)
    }

    @Test
    fun `closed tool schema rejects unexpected args before approval`() {
        val manifest = TaskManifest.compile("save", setOf("save_note"))
        val result = ActionGate(listOf(writeTool)).evaluate(
            Proposal.Action(
                "",
                "save_note",
                mapOf("value" to JsonPrimitive("hello"), "hidden" to JsonPrimitive(true)),
            ),
            manifest,
            ExecutionPhase.EXECUTION,
        )

        assertFalse(result.allowed)
        assertEquals("TAL_SCHEMA_CLOSED", result.stableErrorCode)
        assertFalse(result.requiresApproval)
    }

    @Test
    fun `effect class prevents an auto-approved write misconfiguration`() {
        val unsafeDefinition = object : TalTool {
            override val definition = writeTool.definition.copy(approvalPolicy = ApprovalPolicy.AUTO)
            override suspend fun execute(arguments: Map<String, JsonElement>) = ToolResult(true, "ok", true)
        }
        val manifest = TaskManifest.compile("save", setOf("save_note"))
        val result = ActionGate(listOf(unsafeDefinition)).evaluate(
            Proposal.Action("", "save_note", mapOf("value" to JsonPrimitive("hello"))),
            manifest,
            ExecutionPhase.EXECUTION,
        )

        assertTrue(result.allowed)
        assertTrue(result.requiresApproval)
    }
}
