package com.tervoro.tal

data class ActionPreview(
    val previewId: String,
    val manifestHash: String,
    val stateVersion: Long,
    val goal: String,
    val dataUsed: List<String>,
    val action: String,
    val externalRecipients: List<String>,
    val informationDisclosed: List<String>,
    val informationNotDisclosed: List<String>,
    val reversibility: Reversibility,
    val verification: String,
    val authentication: AuthenticationRequirement,
)
enum class Reversibility { REVERSIBLE, REQUIRES_RECONCILIATION, IRREVERSIBLE }
enum class AuthenticationRequirement { NONE, DEVICE_CREDENTIAL, BIOMETRIC_STRONG }

object ActionPreviewFactory {
    fun from(request: BoundToolRequest, goal: String, dataUsed: List<String>): ActionPreview {
        require(request.manifestHash.matches(Regex("sha256:[a-f0-9]{64}")))
        val write = request.toolId in setOf("draft.create", "note.create", "task.create_local")
        return ActionPreview(
            previewId = "preview:${request.proposalId.removePrefix("proposal:")}", manifestHash = request.manifestHash,
            stateVersion = request.stateVersion, goal = goal.take(1_024), dataUsed = dataUsed.map { it.take(512) },
            action = "${request.toolId}: ${request.purpose}".take(1_024), externalRecipients = emptyList(),
            informationDisclosed = if (write) listOf("App-private local record") else emptyList(),
            informationNotDisclosed = listOf("No network recipient", "No cloud model"),
            reversibility = if (write) Reversibility.REQUIRES_RECONCILIATION else Reversibility.REVERSIBLE,
            verification = if (write) "Encrypted write plus read-back verification" else "Read-only scoped observation",
            authentication = if (write) AuthenticationRequirement.BIOMETRIC_STRONG else AuthenticationRequirement.NONE,
        )
    }
}
