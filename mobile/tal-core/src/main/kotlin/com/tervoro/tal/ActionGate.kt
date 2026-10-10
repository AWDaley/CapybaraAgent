package com.tervoro.tal

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

class ActionGate(
    tools: Collection<TalTool>,
) {
    private val toolDefinitions = tools.associate { it.definition.name to it.definition }

    fun evaluate(
        proposal: Proposal.Action,
        manifest: TaskManifest,
        phase: ExecutionPhase,
    ): GateResult {
        if (!manifest.verifyIntegrity()) {
            return blocked("manifest", "TAL_MANIFEST_INTEGRITY", "Manifest integrity check failed")
        }

        val definition = toolDefinitions[proposal.toolName]
            ?: return blocked("schema", "TAL_UNKNOWN_TOOL", "Tool '${proposal.toolName}' is not registered")

        val schemaFailure = validateClosedSchema(definition, proposal.arguments)
        if (schemaFailure != null) return schemaFailure

        if (!manifest.capabilities.permits(definition.name)) {
            return blocked(
                "capability",
                "TAL_CAPABILITY_DENIED",
                "Tool '${definition.name}' is outside the effective capability envelope",
            )
        }

        if (phase !in definition.allowedPhases) {
            return blocked(
                "effect",
                "TAL_PHASE_EFFECT_DENIED",
                "${definition.effect} effect is not permitted during $phase",
            )
        }

        if (definition.effect == EffectClass.NETWORK || definition.effect == EffectClass.DESTRUCTIVE) {
            return blocked(
                "policy",
                "TAL_LOCAL_ONLY",
                "The Android MVP is local-only and does not expose ${definition.effect} effects",
            )
        }

        return GateResult(
            allowed = true,
            stage = "approval",
            reason = "Action cleared deterministic TAL validation",
            requiresApproval = requiresConfirmation(definition),
            sanitizedArguments = proposal.arguments.toMap(),
        )
    }

    private fun validateClosedSchema(
        definition: ToolDefinition,
        arguments: Map<String, JsonElement>,
    ): GateResult? {
        val unexpected = arguments.keys - definition.schema.keys
        if (unexpected.isNotEmpty()) {
            return blocked(
                "schema",
                "TAL_SCHEMA_CLOSED",
                "Unexpected arguments: ${unexpected.sorted().joinToString()}",
            )
        }

        definition.schema.forEach { (name, rule) ->
            val value = arguments[name]
            if (value == null && rule.required) {
                return blocked("schema", "TAL_SCHEMA_REQUIRED", "Required argument '$name' is missing")
            }
            if (value != null && !matches(value, rule)) {
                return blocked("schema", "TAL_SCHEMA_TYPE", "Argument '$name' has the wrong type or size")
            }
        }
        return null
    }

    private fun matches(value: JsonElement, rule: ParamRule): Boolean {
        val primitive = value as? JsonPrimitive ?: return false
        return when (rule.type) {
            ValueType.STRING -> primitive.isString && primitive.content.length <= rule.maxLength
            ValueType.INTEGER -> !primitive.isString && primitive.content.toLongOrNull() != null
            ValueType.BOOLEAN -> !primitive.isString && primitive.content.toBooleanStrictOrNull() != null
        }
    }

    private fun requiresConfirmation(definition: ToolDefinition): Boolean =
        definition.approvalPolicy == ApprovalPolicy.CONFIRM ||
            definition.effect in setOf(EffectClass.WRITE, EffectClass.EXECUTION, EffectClass.DESTRUCTIVE)

    private fun blocked(stage: String, code: String, reason: String) = GateResult(
        allowed = false,
        stage = stage,
        stableErrorCode = code,
        reason = reason,
    )
}
