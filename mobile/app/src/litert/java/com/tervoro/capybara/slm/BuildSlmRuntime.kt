package com.tervoro.capybara.slm

import android.content.Context
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.SamplerConfig
import com.tervoro.tal.LocalSlmRuntime
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

fun buildSlmRuntime(context: Context): LocalSlmRuntime = LiteRtLocalSlmRuntime(context.applicationContext)

private class LiteRtLocalSlmRuntime(
    private val context: Context,
) : LocalSlmRuntime {
    override val displayName = "LiteRT-LM on-device"
    override var isReady: Boolean = false
        private set

    private var engine: Engine? = null
    private var conversationConfig: ConversationConfig? = null

    override suspend fun initialize(modelPath: String?) = withContext(Dispatchers.IO) {
        require(!modelPath.isNullOrBlank()) { "Import a .litertlm model before initialization" }
        close()

        val initializedEngine = try {
            createEngine(modelPath, Backend.GPU())
        } catch (_: Exception) {
            createEngine(modelPath, Backend.CPU())
        }
        val initializedConversationConfig = ConversationConfig(
            systemInstruction = Contents.of(
                "You are a local TAL proposal generator. Return only the exact strict JSON requested by each prompt.",
            ),
            samplerConfig = SamplerConfig(topK = 20, topP = 0.9, temperature = 0.2),
            automaticToolCalling = false,
        )
        engine = initializedEngine
        conversationConfig = initializedConversationConfig
        isReady = true
    }

    override suspend fun generate(prompt: String): String = withContext(Dispatchers.Default) {
        check(isReady) { "LiteRT-LM is not initialized" }
        val activeEngine = engine ?: error("LiteRT-LM engine is unavailable")
        val config = conversationConfig ?: error("LiteRT-LM conversation configuration is unavailable")
        activeEngine.createConversation(config).use { conversation ->
            conversation.sendMessage(prompt).text
        }
    }

    override fun close() {
        isReady = false
        conversationConfig = null
        engine?.close()
        engine = null
    }

    private fun createEngine(modelPath: String, backend: Backend): Engine {
        val candidate = Engine(
            EngineConfig(
                modelPath = modelPath,
                backend = backend,
                cacheDir = context.cacheDir.absolutePath,
            ),
        )
        try {
            candidate.initialize()
            return candidate
        } catch (exception: Exception) {
            candidate.close()
            throw exception
        }
    }
}
