package com.tervoro.tal

enum class RetentionChoice { EPHEMERAL, VAULT }
data class TaskContractDraft(
    val templateId: String,
    val goal: String,
    val sourceRefs: Set<String>,
    val retention: RetentionChoice,
    val requestedCapabilities: Set<String>,
    val successConditionId: String,
)
data class RegisteredTaskTemplate(
    val templateId: String,
    val successConditionId: String,
    val allowedCapabilities: Set<String>,
)

object MobileTaskTemplates {
    private val templates = listOf(
        RegisteredTaskTemplate("document.answer_with_evidence", "answer_package_released", setOf("document.selected.read")),
        RegisteredTaskTemplate("document.summary", "summary_package_released", setOf("document.selected.read")),
    ).associateBy { it.templateId }

    fun compose(
        templateId: String,
        goal: String,
        sourceRefs: Set<String>,
        retention: RetentionChoice,
        requestedCapabilities: Set<String>,
    ): TaskContractDraft {
        val template = templates[templateId] ?: throw MobileRuntimeException("UNKNOWN_FIELD", "Unregistered task template")
        val normalizedGoal = goal.trim()
        if (normalizedGoal.isEmpty() || normalizedGoal.length > 1_024) throw MobileRuntimeException("TOOL_ARGUMENT_INVALID", "Goal is outside the mobile task bound")
        if (sourceRefs.isEmpty() || sourceRefs.any { !it.matches(Regex("source:[a-z0-9._-]+")) }) throw MobileRuntimeException("UNRESOLVED_REFERENCE", "A selected source is required")
        if (!template.allowedCapabilities.containsAll(requestedCapabilities)) throw MobileRuntimeException("CAPABILITY_DENIED", "Requested capability is outside template policy")
        return TaskContractDraft(templateId, normalizedGoal, sourceRefs.toSortedSet(), retention, requestedCapabilities.toSortedSet(), template.successConditionId)
    }
}
