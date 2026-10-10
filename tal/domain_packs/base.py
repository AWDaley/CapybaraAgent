from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent import BasicAgent
from llm_client import LLMClient
from tal.effect_classes import EffectClass, get_effect_class
from tools import TOOL_INFO, TOOL_REGISTRY


@dataclass
class DomainPack:
    """Modular, policy-governed domain extension specification."""
    name: str
    description: str
    tools: list[str]
    effect_envelope: list[EffectClass]
    system_prompt: str
    custom_validators: list[Callable[[str, Any], str | None]] = field(default_factory=list)
    verification_criteria: list[dict[str, Any]] = field(default_factory=list)
    controlled_vocabulary: dict[str, str] = field(default_factory=dict)


class DomainPackRegistry:
    """Registry managing domain packs and specialist instantiation."""
    def __init__(self):
        self._packs: dict[str, DomainPack] = {}

    def register(self, pack: DomainPack) -> None:
        self._packs[pack.name.lower().strip()] = pack

    def get(self, name: str) -> DomainPack | None:
        return self._packs.get(name.lower().strip())

    def list_packs(self) -> list[str]:
        return sorted(list(self._packs.keys()))

    def create_specialist(
        self,
        name: str,
        llm_client: LLMClient,
        verbose: bool = True,
        knowledge_store: Any | None = None,
        guardrails_enabled: bool = True,
        reflection_enabled: bool = False,
        tal_mode: bool = True,
        use_slm_profile: bool = False,
        tool_allowlist: list[str] | None = None,
        tool_registry: dict[str, Callable] | None = None,
    ) -> BasicAgent:
        pack = self.get(name)
        if not pack:
            # Fallback to general pack
            pack = self.get("general")
            if not pack:
                raise ValueError(f"Domain pack '{name}' not found and default 'general' missing.")

        available_tools = tool_registry if tool_registry is not None else TOOL_REGISTRY
        # A pipeline may narrow a pack, never grant it tools outside its policy.
        authorized = set(pack.tools)
        if tool_allowlist is not None:
            authorized.intersection_update(tool_allowlist)
        allowed_effects = set(pack.effect_envelope)
        custom_registry = {
            k: v for k, v in available_tools.items()
            if k in authorized and get_effect_class(k) in allowed_effects
        }

        def custom_descriptions():
            desc = f"Domain Pack: {pack.name.upper()} ({pack.description})\nAvailable Tools:\n"
            import re
            for i, tool_name in enumerate(custom_registry.keys(), 1):
                block = TOOL_INFO.get(tool_name, f'{i}. {{"tool": "{tool_name}", "args": "..."}}\n   - Description missing')
                block = re.sub(r'^\s*\d+\.', f"{i}.", block)
                desc += block + "\n"
            return desc

        return BasicAgent(
            llm_client=llm_client,
            system_prompt=pack.system_prompt,
            verbose=verbose,
            knowledge_store=knowledge_store,
            guardrails_enabled=guardrails_enabled,
            reflection_enabled=reflection_enabled,
            tool_registry=custom_registry,
            tool_descriptions_fn=custom_descriptions,
            tal_mode=tal_mode,
            use_slm_profile=use_slm_profile
        )


GLOBAL_DOMAIN_REGISTRY = DomainPackRegistry()
