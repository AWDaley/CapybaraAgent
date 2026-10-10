package com.tervoro.tal

import java.security.MessageDigest
import java.time.Instant
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

@ConsistentCopyVisibility
data class TaskManifest private constructor(
    val manifestId: String,
    val talVersion: String,
    val goal: String,
    val createdAt: Instant,
    val capabilities: CapabilityEnvelope,
    val budget: BudgetLimits,
    val verificationCriteria: List<VerificationCriterion>,
    val manifestHash: String,
) {
    fun canonicalContract(): String = CanonicalJson.encode(contractJson())

    fun computeHash(): String = sha256(canonicalContract().toByteArray(Charsets.UTF_8))

    fun verifyIntegrity(): Boolean = manifestHash.isNotBlank() && manifestHash == computeHash()

    private fun contractJson(): JsonObject = CanonicalJson.objectOf(
        "budget" to CanonicalJson.objectOf(
            "max_repair_attempts" to JsonPrimitive(budget.maxRepairAttempts),
            "max_steps" to JsonPrimitive(budget.maxSteps),
            "max_time_millis" to JsonPrimitive(budget.maxTimeMillis),
            "max_tool_errors" to JsonPrimitive(budget.maxToolErrors),
        ),
        "capabilities" to CanonicalJson.objectOf(
            "denied" to JsonObject(capabilities.denied.mapValues { JsonPrimitive(it.value) }),
            "effective" to JsonArray(capabilities.effective.sorted().map(::JsonPrimitive)),
            "requested" to JsonArray(capabilities.requested.sorted().map(::JsonPrimitive)),
        ),
        "goal" to JsonPrimitive(goal),
        "tal_version" to JsonPrimitive(talVersion),
        "verification_criteria" to JsonArray(
            verificationCriteria.map {
                JsonPrimitive(
                    when (it) {
                        VerificationCriterion.NonEmptyFinalAnswer -> "non_empty_final_answer"
                        VerificationCriterion.VerifiedWritesOnly -> "verified_writes_only"
                    },
                )
            },
        ),
    )

    companion object {
        fun compile(
            goal: String,
            availableTools: Set<String>,
            requestedTools: Set<String> = availableTools,
            policyDenials: Map<String, String> = emptyMap(),
            budget: BudgetLimits = BudgetLimits(),
            verificationCriteria: List<VerificationCriterion> = listOf(
                VerificationCriterion.NonEmptyFinalAnswer,
                VerificationCriterion.VerifiedWritesOnly,
            ),
            createdAt: Instant = Instant.now(),
        ): TaskManifest {
            val normalizedGoal = goal.trim()
            require(normalizedGoal.isNotEmpty()) { "Goal must not be empty" }
            require(normalizedGoal.length <= 8_192) { "Goal exceeds the mobile context intake limit" }

            val requested = requestedTools.toSortedSet()
            val denied = buildMap {
                requested.filterNotTo(mutableSetOf()) { it in availableTools }.forEach {
                    put(it, "CAPABILITY_UNAVAILABLE")
                }
                policyDenials.filterKeys { it in requested }.forEach(::put)
            }.toSortedMap()
            val effective = requested.filterTo(sortedSetOf()) { it in availableTools && it !in denied }
            val envelope = CapabilityEnvelope(requested, effective, denied)

            val provisional = TaskManifest(
                manifestId = "",
                talVersion = "1.0-mobile",
                goal = normalizedGoal,
                createdAt = createdAt,
                capabilities = envelope,
                budget = budget.copy(),
                verificationCriteria = verificationCriteria.toList(),
                manifestHash = "",
            )
            val hash = provisional.computeHash()
            return provisional.copy(manifestId = "man_${hash.take(12)}", manifestHash = hash)
        }

        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { byte -> "%02x".format(byte) }
    }
}
