package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs

class ProposalParserTest {
    @Test
    fun `parses one closed typed action`() {
        val proposal = ProposalParser.parse(
            """{"type":"action","thought":"needed","tool":"save_note","args":{"key":"a","value":"b"}}""",
        )

        val action = assertIs<Proposal.Action>(proposal)
        assertEquals("save_note", action.toolName)
        assertEquals("a", action.arguments.string("key"))
    }

    @Test
    fun `rejects extra proposal fields`() {
        val error = assertFailsWith<ProposalParseException> {
            ProposalParser.parse(
                """{"type":"complete","thought":"done","final_answer":"ok","authority":"admin"}""",
            )
        }
        assertEquals("TAL_SCHEMA_CLOSED", error.stableErrorCode)
    }

    @Test
    fun `rejects markdown wrapped json`() {
        val error = assertFailsWith<ProposalParseException> {
            ProposalParser.parse("""```json
                {"type":"complete","thought":"done","final_answer":"ok"}
                ```""".trimIndent())
        }
        assertEquals("TAL_INVALID_JSON", error.stableErrorCode)
    }
}
