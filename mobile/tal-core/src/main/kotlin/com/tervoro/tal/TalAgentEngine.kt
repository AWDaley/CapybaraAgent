package com.tervoro.tal

import java.util.UUID
import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

class TalAgentEngine(
    private val runtime: LocalSlmRuntime,
    tools: Collection<TalTool>,
    private val approvalHandler: ApprovalHandler,
    private val auditTrail: AuditTrail = AuditTrail(),
    private val onEvent: (AuditEvent) -> Unit = {},
) {
    private val toolMap = tools.associateBy { it.definition.name }
    private val tools = toolMap.values.toList()
    private val gate = ActionGate(tools)

    suspend fun runGoal(
        goal: String,
        requestedTools: Set<String> = toolMap.keys,
        budget: BudgetLimits = BudgetLimits(),
    ): EngineResult {
        check(runtime.isReady) { "Local SLM runtime is not initialized" }
        val manifest = TaskManifest.compile(
            goal = goal,
            availableTools = toolMap.keys,
            requestedTools = requestedTools,
            policyDenials = requestedTools
                .filter { toolMap[it]?.definition?.effect in setOf(EffectClass.NETWORK, EffectClass.DESTRUCTIVE) }
                .associateWith { "TAL_LOCAL_ONLY" },
            budget = budget,
        )
        emit("task_started", mapOf("goal" to JsonPrimitive(manifest.goal), "manifest" to JsonPrimitive(manifest.manifestId)))

        var phase = ExecutionPhase.EXECUTION
        var observation: String? = null
        var toolErrors = 0
        var repairAttempts = 0
        var lastToolFailed = false
        val pendingWriteVerification = mutableSetOf<String>()
        val startedNanos = System.nanoTime()

        for (step in 1..manifest.budget.maxSteps) {
            val remainingMillis = manifest.budget.maxTimeMillis - elapsedMillis(startedNanos)
            if (remainingMillis <= 0) {
                return escalate(manifest, "TAL_BUDGET_TIME", "Task exceeded its monotonic time budget")
            }

            val prompt = ContextPacker.pack(manifest, phase, tools, step, observation)
            val rawProposal = try {
                // A cooperative runtime may still be slow.  The engine owns the task budget,
                // so every inference call is constrained by the remaining monotonic allowance.
                withTimeout(remainingMillis) { runtime.generate(prompt) }
            } catch (_: TimeoutCancellationException) {
                return escalate(manifest, "TAL_BUDGET_TIME", "Local inference exceeded the remaining time budget")
            } catch (exception: CancellationException) {
                // Cancellation is a caller-controlled lifecycle signal, never a model failure.
                throw exception
            } catch (exception: Exception) {
                return escalate(manifest, "TAL_MODEL_FAILURE", exception.message ?: "Local model failed")
            }

            val proposal = try {
                ProposalParser.parse(rawProposal)
            } catch (exception: ProposalParseException) {
                repairAttempts += 1
                emit(
                    "proposal_rejected",
                    mapOf("code" to JsonPrimitive(exception.stableErrorCode), "reason" to JsonPrimitive(exception.message.orEmpty())),
                )
                if (repairAttempts > manifest.budget.maxRepairAttempts) {
                    return escalate(manifest, "TAL_REPAIR_BUDGET", "Proposal repair budget exhausted")
                }
                phase = ExecutionPhase.RECOVERY
                observation = "${exception.stableErrorCode}: ${exception.message}. Emit one corrected strict JSON proposal."
                continue
            }

            when (proposal) {
                is Proposal.Action -> {
                    emit(
                        "proposal_action",
                        mapOf("tool" to JsonPrimitive(proposal.toolName), "thought" to JsonPrimitive(proposal.thought.take(512))),
                    )
                    val gateResult = gate.evaluate(proposal, manifest, phase)
                    if (!gateResult.allowed) {
                        emit(
                            "action_blocked",
                            mapOf(
                                "code" to JsonPrimitive(gateResult.stableErrorCode.orEmpty()),
                                "reason" to JsonPrimitive(gateResult.reason),
                                "stage" to JsonPrimitive(gateResult.stage),
                            ),
                        )
                        phase = ExecutionPhase.RECOVERY
                        observation = "${gateResult.stableErrorCode}: ${gateResult.reason}"
                        continue
                    }

                    val tool = toolMap.getValue(proposal.toolName)
                    if (tool.definition.effect == EffectClass.WRITE) {
                        pendingWriteVerification += tool.definition.name
                    }
                    if (gateResult.requiresApproval) {
                        val request = ApprovalRequest(
                            requestId = "apr_${UUID.randomUUID().toString().take(12)}",
                            manifestId = manifest.manifestId,
                            manifestHash = manifest.manifestHash,
                            stateVersion = step.toLong(),
                            tool = tool.definition,
                            arguments = gateResult.sanitizedArguments,
                            canonicalArguments = CanonicalJson.encode(JsonObject(gateResult.sanitizedArguments.toSortedMap())),
                            expiresAt = Instant.now().plusSeconds(APPROVAL_TTL_SECONDS),
                        )
                        emit(
                            "approval_requested",
                            mapOf("request_id" to JsonPrimitive(request.requestId), "tool" to JsonPrimitive(tool.definition.name)),
                        )
                        val decision = approvalHandler.requestApproval(request)
                        emit(
                            "approval_resolved",
                            mapOf("request_id" to JsonPrimitive(request.requestId), "decision" to JsonPrimitive(decision.name.lowercase())),
                        )
                        if (decision != ApprovalDecision.APPROVED) {
                            phase = ExecutionPhase.RECOVERY
                            observation = "TAL_APPROVAL_DENIED: The user denied ${tool.definition.name}. Choose a safe alternative or explain."
                            continue
                        }
                        if (!request.matches(
                                manifestHash = manifest.manifestHash,
                                stateVersion = step.toLong(),
                                toolName = tool.definition.name,
                                arguments = gateResult.sanitizedArguments,
                            )
                        ) {
                            phase = ExecutionPhase.RECOVERY
                            observation = "TAL_APPROVAL_STALE: The authorization expired or no longer matches this action."
                            continue
                        }
                    }

                    val result = try {
                        tool.execute(gateResult.sanitizedArguments)
                    } catch (exception: Exception) {
                        ToolResult(false, exception.message ?: "Tool failed", stableErrorCode = "TAL_TOOL_EXCEPTION")
                    }
                    emit(
                        "tool_executed",
                        mapOf(
                            "tool" to JsonPrimitive(tool.definition.name),
                            "success" to JsonPrimitive(result.success),
                            "verified" to JsonPrimitive(result.independentlyVerified),
                            "output" to JsonPrimitive(result.output.take(2_000)),
                        ),
                    )
                    if (!result.success) {
                        toolErrors += 1
                        lastToolFailed = true
                        if (toolErrors > manifest.budget.maxToolErrors) {
                            return escalate(manifest, "TAL_TOOL_ERROR_BUDGET", "Tool error budget exhausted")
                        }
                        phase = ExecutionPhase.RECOVERY
                    } else {
                        lastToolFailed = false
                        phase = ExecutionPhase.EXECUTION
                        if (tool.definition.effect == EffectClass.WRITE && result.independentlyVerified) {
                            pendingWriteVerification -= tool.definition.name
                        }
                    }
                    observation = buildObservation(tool.definition.name, result)
                }

                is Proposal.Complete -> {
                    phase = ExecutionPhase.VERIFICATION
                    val failures = verifyCompletion(proposal, lastToolFailed, pendingWriteVerification)
                    emit(
                        "verification_run",
                        mapOf(
                            "passed" to JsonPrimitive(failures.isEmpty()),
                            "failures" to JsonPrimitive(failures.joinToString("; ")),
                        ),
                    )
                    if (failures.isEmpty()) {
                        emit("task_completed", mapOf("answer" to JsonPrimitive(proposal.finalAnswer)))
                        return EngineResult.Completed(manifest, proposal.finalAnswer)
                    }
                    phase = ExecutionPhase.RECOVERY
                    observation = "TAL_VERIFICATION_FAILED: ${failures.joinToString("; ")}"
                }

                is Proposal.Query -> {
                    emit("task_waiting_for_user", mapOf("question" to JsonPrimitive(proposal.question)))
                    return EngineResult.WaitingForUser(manifest, proposal.question)
                }

                is Proposal.Escalate -> return escalate(manifest, "TAL_MODEL_ESCALATED", proposal.reason)
            }
        }
        return escalate(manifest, "TAL_BUDGET_STEPS", "Task exceeded its step budget")
    }

    private fun verifyCompletion(
        proposal: Proposal.Complete,
        lastToolFailed: Boolean,
        pendingWriteVerification: Set<String>,
    ): List<String> = buildList {
        if (proposal.finalAnswer.isBlank()) add("final answer is empty")
        if (proposal.finalAnswer.length > 8_192) add("final answer exceeds the mobile output limit")
        if (lastToolFailed) add("the latest tool failure is unresolved")
        if (pendingWriteVerification.isNotEmpty()) {
            add("write effects lack independent read-back verification: ${pendingWriteVerification.sorted().joinToString()}")
        }
    }

    private fun buildObservation(toolName: String, result: ToolResult): String =
        "tool=$toolName; success=${result.success}; independently_verified=${result.independentlyVerified}; " +
            "data=${result.output.take(1_500)}"

    private fun emit(type: String, data: Map<String, JsonElement>): AuditEvent =
        auditTrail.append(type, data).also(onEvent)

    private fun escalate(manifest: TaskManifest, code: String, reason: String): EngineResult.Escalated {
        emit("task_escalated", mapOf("code" to JsonPrimitive(code), "reason" to JsonPrimitive(reason)))
        return EngineResult.Escalated(manifest, code, reason)
    }

    private fun elapsedMillis(startedNanos: Long): Long = (System.nanoTime() - startedNanos) / 1_000_000

    private companion object {
        const val APPROVAL_TTL_SECONDS = 60L
    }
}
