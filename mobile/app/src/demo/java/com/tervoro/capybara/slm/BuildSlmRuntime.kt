package com.tervoro.capybara.slm

import android.content.Context
import com.tervoro.tal.LocalSlmRuntime
import kotlinx.serialization.json.JsonPrimitive

@Suppress("UNUSED_PARAMETER")
fun buildSlmRuntime(context: Context): LocalSlmRuntime = DeterministicDemoSlmRuntime()

private class DeterministicDemoSlmRuntime : LocalSlmRuntime {
    override val displayName = "Deterministic TAL demo"
    override var isReady: Boolean = false
        private set

    override suspend fun initialize(modelPath: String?) {
        isReady = true
    }

    override suspend fun generate(prompt: String): String {
        check(isReady)
        val goal = prompt.substringAfter("goal=", "").substringBefore('\n').trim()
        val observation = prompt.substringAfter("<untrusted_observation>", "none")
            .substringBefore("</untrusted_observation>")
            .trim()

        if (observation != "none") {
            val answer = JsonPrimitive("Completed locally. ${observation.take(240)}")
            return """{"type":"complete","thought":"The governed action returned evidence","final_answer":$answer}"""
        }
        if (goal.contains("time", ignoreCase = true)) {
            return """{"type":"action","thought":"Read the phone clock","tool":"current_time","args":{}}"""
        }
        if (goal.contains("document", ignoreCase = true) || goal.contains("summar", ignoreCase = true)) {
            return """{\"type\":\"action\",\"thought\":\"Read only the user-selected document\",\"tool\":\"document.selected.read\",\"args\":{}}"""
        }
        if (goal.contains("note", ignoreCase = true) || goal.contains("remember", ignoreCase = true)) {
            val safeValue = JsonPrimitive(goal.take(500))
            return """{"type":"action","thought":"Store the requested text in encrypted local storage","tool":"note.create","args":{"idempotency_key":"effect:quick-note","key":"quick-note","value":$safeValue}}"""
        }
        val answer = JsonPrimitive("The deterministic demo received: ${goal.take(500)}")
        return """{"type":"complete","thought":"No tool effect is required","final_answer":$answer}"""
    }
}
