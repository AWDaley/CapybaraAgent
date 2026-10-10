from collections.abc import Callable

from agent import BasicAgent
from agents.coder import CODER_PROMPT
from agents.researcher import RESEARCHER_PROMPT
from llm_client import LLMClient
from tal.domain_packs import GLOBAL_DOMAIN_REGISTRY
from tools import TOOL_INFO, TOOL_REGISTRY

AGENT_REGISTRY = {
    "researcher": {
        "system_prompt": RESEARCHER_PROMPT,
        "tools": ["web_search", "read_url", "recall", "remember", "read_file", "list_files"],
        "description": "Searches the web, reads URLs, and gathers information."
    },
    "coder": {
        "system_prompt": CODER_PROMPT,
        "tools": ["write_file", "read_file", "run_command", "python_repl", "calc", "list_files"],
        "description": "Writes files, executes Python code in REPL or scripts, and does calculations."
    },
    "general": {
        "system_prompt": "You are a helpful general assistant. You have access to tools. If the user asks you to do something that requires a tool, use it! Otherwise, just chat with them normally.",
        "tools": ["calc", "time", "convert units", "remember", "recall", "web_search", "read_url", "read_file", "list_files"],
        "description": "Handles general questions that don't need a specialist."
    }
}

def create_specialist(
    name: str,
    llm_client: LLMClient,
    verbose: bool = True,
    knowledge_store=None,
    guardrails_enabled: bool = True,
    reflection_enabled: bool = False,
    tal_mode: bool = False,
    use_slm_profile: bool = False,
    tool_allowlist: list[str] | None = None,
    tool_registry: dict[str, Callable] | None = None,
) -> BasicAgent:
    """Creates a configured BasicAgent instance based on the registry or DomainPack."""
    name = name.lower().strip()
    
    if tal_mode and GLOBAL_DOMAIN_REGISTRY.get(name):
        return GLOBAL_DOMAIN_REGISTRY.create_specialist(
            name=name,
            llm_client=llm_client,
            verbose=verbose,
            knowledge_store=knowledge_store,
            guardrails_enabled=guardrails_enabled,
            reflection_enabled=reflection_enabled,
            tal_mode=True,
            use_slm_profile=use_slm_profile,
            tool_allowlist=tool_allowlist,
            tool_registry=tool_registry,
        )

    if name not in AGENT_REGISTRY:
        print(f"⚠️  Specialist '{name}' not found. Defaulting to 'general'.")
        name = "general"
        
    config = AGENT_REGISTRY[name]
    
    # Filter an optional session-scoped registry instead of silently falling
    # back to global tools (notably the stateful Python REPL).
    available_tools = tool_registry if tool_registry is not None else TOOL_REGISTRY
    if tool_allowlist is not None:
        custom_registry = {k: available_tools[k] for k in tool_allowlist if k in available_tools}
    elif config["tools"] is None:
        custom_registry = available_tools
    else:
        custom_registry = {k: v for k, v in available_tools.items() if k in config["tools"]}
        
    # Create custom tool descriptions function for this subset
    def custom_descriptions():
        desc = "Available Tools:\n"
        import re
        for i, tool_name in enumerate(custom_registry.keys(), 1):
            block = TOOL_INFO.get(tool_name, f'{i}. {{"tool": "{tool_name}", "args": "..."}}\n   - Description missing')
            block = re.sub(r'^\s*\d+\.', f"{i}.", block)
            desc += block + "\n"
        return desc

    return BasicAgent(
        llm_client=llm_client,
        system_prompt=config["system_prompt"],
        verbose=verbose,
        knowledge_store=knowledge_store,
        guardrails_enabled=guardrails_enabled,
        reflection_enabled=reflection_enabled,
        tool_registry=custom_registry,
        tool_descriptions_fn=custom_descriptions,
        tal_mode=tal_mode,
        use_slm_profile=use_slm_profile
    )
