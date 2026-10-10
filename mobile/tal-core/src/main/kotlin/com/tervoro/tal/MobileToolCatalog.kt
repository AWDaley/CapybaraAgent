package com.tervoro.tal

data class MobileToolContract(val toolId: String, val version: String, val effect: EffectClass, val requiresApproval: Boolean)

object MobileToolCatalog {
    private val contracts = listOf(
        MobileToolContract("document.selected.read", "1.0.0", EffectClass.READ, false),
        MobileToolContract("image.selected.inspect", "1.0.0", EffectClass.READ, false),
        MobileToolContract("vault.search", "1.0.0", EffectClass.READ, false),
        MobileToolContract("draft.create", "1.0.0", EffectClass.WRITE, true),
        MobileToolContract("note.create", "1.0.0", EffectClass.WRITE, true),
        MobileToolContract("task.create_local", "1.0.0", EffectClass.WRITE, true),
    ).associateBy { it.toolId }

    fun resolve(toolId: String, version: String): MobileToolContract {
        val contract = contracts[toolId] ?: throw MobileRuntimeException("UNKNOWN_FIELD", "Tool is not in the mobile catalog")
        if (contract.version != version) throw MobileRuntimeException("TOOL_VERSION_UNSUPPORTED", "Tool version is not certified")
        return contract
    }
    fun enabledIds(): Set<String> = contracts.keys
}
