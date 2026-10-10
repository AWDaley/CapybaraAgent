from tal.effect_classes import EffectClass

from .base import GLOBAL_DOMAIN_REGISTRY, DomainPack, DomainPackRegistry
from .coding import CodingDomainPack
from .research import ResearchDomainPack

GeneralDomainPack = DomainPack(
    name="general",
    description="Handles general questions, arithmetic, time, conversions, and information lookups.",
    tools=["calc", "time", "convert units", "remember", "recall", "web_search", "read_url", "read_file", "write_file", "list_files"],
    effect_envelope=[EffectClass.READ, EffectClass.NETWORK, EffectClass.WRITE],
    system_prompt="You are a helpful general assistant. You have access to tools. If the user asks you to do something that requires a tool, use it! Otherwise, just chat with them normally."
)

# Register default packs
GLOBAL_DOMAIN_REGISTRY.register(GeneralDomainPack)
GLOBAL_DOMAIN_REGISTRY.register(CodingDomainPack)
GLOBAL_DOMAIN_REGISTRY.register(ResearchDomainPack)

__all__ = [
    "GLOBAL_DOMAIN_REGISTRY",
    "CodingDomainPack",
    "DomainPack",
    "DomainPackRegistry",
    "GeneralDomainPack",
    "ResearchDomainPack",
]
