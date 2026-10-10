package com.tervoro.capybara

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.tervoro.capybara.security.AndroidKeyStoreSecrets
import com.tervoro.capybara.security.EncryptedAuditSink
import com.tervoro.capybara.security.EncryptedNoteStore
import com.tervoro.capybara.slm.buildSlmRuntime
import com.tervoro.tal.ApprovalDecision
import com.tervoro.tal.ApprovalHandler
import com.tervoro.tal.ApprovalRequest
import com.tervoro.tal.AuditTrail
import com.tervoro.tal.EngineResult
import com.tervoro.tal.TalAgentEngine
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class MessageRole { USER, AGENT, SYSTEM }

data class ChatMessage(
    val id: String = UUID.randomUUID().toString(),
    val role: MessageRole,
    val content: String,
)

data class AgentUiState(
    val runtimeName: String = BuildConfig.RUNTIME_NAME,
    val modelReady: Boolean = false,
    val modelStatus: String = "Initializing local runtime…",
    val isRunning: Boolean = false,
    val phase: String = "idle",
    val auditEventCount: Int = 0,
    val selectedDocumentName: String? = null,
    val messages: List<ChatMessage> = listOf(
        ChatMessage(
            role = MessageRole.SYSTEM,
            content = "Local-only mode is active. TAL validates every proposed action before execution.",
        ),
    ),
    val pendingApproval: ApprovalRequest? = null,
    val error: String? = null,
)

class AgentViewModel(application: Application) : AndroidViewModel(application) {
    private val state = MutableStateFlow(AgentUiState())
    val uiState: StateFlow<AgentUiState> = state.asStateFlow()

    private val secrets = AndroidKeyStoreSecrets()
    private val noteStore = EncryptedNoteStore(application, secrets)
    private val documentStore = SelectedDocumentStore(application)
    private val modelManager = ModelManager(application)
    private val runtime = buildSlmRuntime(application)
    private val tools = listOf(
        CurrentTimeTool(),
        ListNotesTool(noteStore),
        ReadNoteTool(noteStore),
        SaveNoteTool(noteStore),
        SelectedDocumentReadTool(documentStore),
    )
    private var approvalDeferred: CompletableDeferred<ApprovalDecision>? = null
    private var activeRun: Job? = null

    init {
        val installedPath = modelManager.installedPath()
        if (BuildConfig.FLAVOR == "demo" || installedPath != null) {
            initializeRuntime(installedPath)
        } else {
            state.update {
                it.copy(modelStatus = "Import a .litertlm model to begin", modelReady = false)
            }
        }
    }

    fun importModel(uri: Uri) {
        if (state.value.isRunning) return
        state.update { it.copy(modelStatus = "Copying model into private storage…", error = null) }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val priorModel = modelManager.installedPath()
                val staged = withContext(Dispatchers.IO) { modelManager.stage(uri) }
                try {
                    state.update { it.copy(modelStatus = "Health-checking ${formatBytes(staged.model.sizeBytes)} staged model (${staged.model.sha256.take(12)}…)") }
                    runtime.close()
                    runtime.initialize(staged.model.path)
                    runtime.close()
                    val model = modelManager.promote(staged)
                    runtime.initialize(model.path)
                } catch (error: Exception) {
                    modelManager.discard(staged)
                    if (priorModel != null) runCatching { runtime.initialize(priorModel) }
                    throw error
                }
            }.onSuccess {
                state.update { it.copy(modelReady = true, modelStatus = "Ready · ${runtime.displayName}", error = null) }
            }.onFailure { error ->
                state.update {
                    it.copy(modelReady = false, modelStatus = "Model unavailable", error = error.message ?: "Model import failed")
                }
            }
        }
    }

    fun send(goal: String) {
        val normalized = goal.trim()
        if (normalized.isEmpty() || !runtime.isReady || state.value.isRunning) return
        state.update {
            it.copy(
                isRunning = true,
                phase = "execution",
                error = null,
                messages = it.messages + ChatMessage(role = MessageRole.USER, content = normalized),
            )
        }

        activeRun = viewModelScope.launch(Dispatchers.IO) {
            val taskId = "task_${UUID.randomUUID()}"
            val audit = AuditTrail(
                signer = secrets,
                sink = EncryptedAuditSink(getApplication(), taskId, secrets),
            )
            val engine = TalAgentEngine(
                runtime = runtime,
                tools = tools,
                approvalHandler = ApprovalHandler { request -> awaitApproval(request) },
                auditTrail = audit,
                onEvent = { event ->
                    state.update {
                        it.copy(
                            auditEventCount = it.auditEventCount + 1,
                            phase = event.eventType.replace('_', ' '),
                        )
                    }
                },
            )

            try {
                val result = engine.runGoal(normalized)
                val response = when (result) {
                    is EngineResult.Completed -> result.answer
                    is EngineResult.WaitingForUser -> result.question
                    is EngineResult.Escalated -> "${result.stableErrorCode}: ${result.reason}"
                }
                state.update {
                    it.copy(
                        isRunning = false,
                        phase = when (result) {
                            is EngineResult.Completed -> "completed"
                            is EngineResult.WaitingForUser -> "waiting for user"
                            is EngineResult.Escalated -> "escalated"
                        },
                        messages = it.messages + ChatMessage(role = MessageRole.AGENT, content = response),
                    )
                }
            } catch (_: CancellationException) {
                audit.append("task_cancelled", mapOf())
                state.update {
                    it.copy(
                        isRunning = false,
                        phase = "cancelled",
                        pendingApproval = null,
                        messages = it.messages + ChatMessage(
                            role = MessageRole.SYSTEM,
                            content = "Task cancelled. No further tool actions will be executed.",
                        ),
                    )
                }
                throw CancellationException("Agent task cancelled")
            } catch (error: Exception) {
                state.update {
                    it.copy(isRunning = false, phase = "failed", error = error.message ?: "Agent execution failed")
                }
            } finally {
                if (activeRun === coroutineContext[Job]) activeRun = null
            }
        }
    }

    fun selectDocument(uri: Uri) {
        if (state.value.isRunning) return
        runCatching { documentStore.select(uri) }
            .onSuccess { document -> state.update { it.copy(selectedDocumentName = document.displayName, error = null) } }
            .onFailure { error -> state.update { it.copy(error = error.message ?: "Document selection failed") } }
    }

    fun cancelRun() {
        val active = activeRun ?: return
        if (!active.isActive) return
        state.update { it.copy(phase = "cancelling", pendingApproval = null) }
        approvalDeferred?.cancel(CancellationException("Task cancelled by user"))
        approvalDeferred = null
        active.cancel(CancellationException("Task cancelled by user"))
    }

    fun resolveApproval(decision: ApprovalDecision) {
        approvalDeferred?.complete(decision)
        approvalDeferred = null
        state.update { it.copy(pendingApproval = null) }
    }

    private fun initializeRuntime(modelPath: String?) {
        viewModelScope.launch {
            runCatching { runtime.initialize(modelPath) }
                .onSuccess {
                    state.update { it.copy(modelReady = true, modelStatus = "Ready · ${runtime.displayName}", error = null) }
                }
                .onFailure { error ->
                    state.update {
                        it.copy(modelReady = false, modelStatus = "Model unavailable", error = error.message ?: "Initialization failed")
                    }
                }
        }
    }

    private suspend fun awaitApproval(request: ApprovalRequest): ApprovalDecision {
        check(approvalDeferred == null) { "Only one approval may be pending" }
        val deferred = CompletableDeferred<ApprovalDecision>()
        approvalDeferred = deferred
        state.update { it.copy(pendingApproval = request, phase = "waiting for approval") }
        return deferred.await()
    }

    override fun onCleared() {
        cancelRun()
        approvalDeferred?.cancel()
        runtime.close()
        super.onCleared()
    }

    private fun formatBytes(bytes: Long): String = when {
        bytes >= 1L shl 30 -> "%.1f GiB".format(bytes.toDouble() / (1L shl 30))
        bytes >= 1L shl 20 -> "%.1f MiB".format(bytes.toDouble() / (1L shl 20))
        else -> "$bytes bytes"
    }
}
