package com.tervoro.tal

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

class ProposalParseException(
    val stableErrorCode: String,
    message: String,
) : IllegalArgumentException(message)

object ProposalParser {
    private val commonKeys = setOf("type", "thought")

    fun parse(raw: String): Proposal {
        if (raw.isBlank()) throw error("TAL_INVALID_EMPTY", "Model emitted an empty proposal")
        val root = try {
            StrictJson.parseToJsonElement(raw.trim()).jsonObject
        } catch (exception: Exception) {
            throw error("TAL_INVALID_JSON", "Proposal is not strict JSON", exception)
        }

        val type = root.requiredString("type")
        val thought = root.optionalString("thought") ?: ""
        return when (type) {
            "action" -> {
                root.requireClosed(commonKeys + setOf("tool", "args"))
                val tool = root.requiredString("tool")
                val arguments = root["args"] as? JsonObject
                    ?: throw error("TAL_SCHEMA_ARGS", "Action args must be a JSON object")
                Proposal.Action(thought, tool, arguments.toMap())
            }

            "complete" -> {
                root.requireClosed(commonKeys + "final_answer")
                Proposal.Complete(thought, root.requiredString("final_answer"))
            }

            "query" -> {
                root.requireClosed(commonKeys + "question")
                Proposal.Query(thought, root.requiredString("question"))
            }

            "escalate" -> {
                root.requireClosed(commonKeys + setOf("reason", "context"))
                Proposal.Escalate(
                    thought = thought,
                    reason = root.requiredString("reason"),
                    context = root.optionalString("context") ?: "",
                )
            }

            else -> throw error("TAL_SCHEMA_TYPE", "Unknown proposal type '$type'")
        }
    }

    private fun JsonObject.requireClosed(allowed: Set<String>) {
        val unexpected = keys - allowed
        if (unexpected.isNotEmpty()) {
            throw error("TAL_SCHEMA_CLOSED", "Unexpected proposal fields: ${unexpected.sorted().joinToString()}")
        }
    }

    private fun JsonObject.requiredString(name: String): String =
        optionalString(name)?.takeIf { it.isNotBlank() }
            ?: throw error("TAL_SCHEMA_REQUIRED", "Field '$name' must be a non-empty string")

    private fun JsonObject.optionalString(name: String): String? =
        (get(name) as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun error(code: String, message: String, cause: Throwable? = null): ProposalParseException =
        ProposalParseException(code, message).also { if (cause != null) it.initCause(cause) }
}
