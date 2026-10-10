package com.tervoro.tal

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/** Profile-shaped proposal binding used at the mobile tool boundary. */
data class BoundToolRequest(
    val proposalId: String,
    val goalId: String,
    val manifestHash: String,
    val manifestVersion: Int,
    val stateVersion: Long,
    val toolId: String,
    val toolVersion: String,
    val targetRef: String,
    val arguments: Map<String, JsonElement>,
    val purpose: String,
    val evidenceRefs: Set<String>,
    val expectedObservationType: String,
)

data class MobileApprovalRecord(
    val approvalId: String,
    val manifestHash: String,
    val stateVersion: Long,
    val actionId: String,
    val targetRef: String,
    val argumentsHash: String,
    val expiresAtEpochMillis: Long,
    val approved: Boolean,
)

object MobileActionAuthorization {
    fun authorize(
        request: BoundToolRequest,
        state: MobileRunState,
        effectiveTools: Set<String>,
        scopedTargets: Set<String>,
        nowEpochMillis: Long,
        approval: MobileApprovalRecord? = null,
    ) {
        fun deny(code: String, message: String): Nothing = throw MobileRuntimeException(code, message)
        if (request.manifestVersion != 1 || request.manifestHash != state.manifestHash || request.stateVersion != state.stateVersion) deny("STALE_STATE_VERSION", "Proposal binding is stale")
        if (request.toolVersion != "1.0.0" || request.toolId !in effectiveTools) deny("CAPABILITY_DENIED", "Tool is outside the effective capability envelope")
        if (request.targetRef !in scopedTargets) deny("UNRESOLVED_REFERENCE", "Tool target is outside the selected data scope")
        if (request.arguments.keys.any { it !in setOf("query_ref", "source_refs", "maximum_items") }) deny("UNKNOWN_FIELD", "Tool arguments are not closed")
        val max = (request.arguments["maximum_items"] as? kotlinx.serialization.json.JsonPrimitive)?.content?.toIntOrNull()
        if (max != null && max !in 1..12) deny("TOOL_ARGUMENT_INVALID", "maximum_items is outside the mobile bound")
        if (request.toolId in WRITE_TOOL_IDS) {
            val argsHash = "sha256:" + TaskManifest.sha256(CanonicalJson.encode(JsonObject(request.arguments.toSortedMap())).toByteArray(Charsets.UTF_8))
            if (approval == null || !approval.approved || approval.expiresAtEpochMillis <= nowEpochMillis ||
                approval.manifestHash != request.manifestHash || approval.stateVersion != request.stateVersion ||
                approval.actionId != request.toolId || approval.targetRef != request.targetRef || approval.argumentsHash != argsHash) {
                deny("APPROVAL_REQUIRED", "A current approval does not bind this exact local write")
            }
        }
    }
    private val WRITE_TOOL_IDS = setOf("draft.create", "note.create", "task.create_local")
}
