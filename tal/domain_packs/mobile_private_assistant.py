"""Metadata-only private-assistant domain pack for mobile conformance work."""

from tal.domain_packs.base import DomainPack
from tal.effect_classes import EffectClass


MobilePrivateAssistantDomainPack = DomainPack(
    name="mobile_private_assistant",
    description="Closed local-only mobile document, vault, draft, note, and task workflows.",
    tools=[
        "document.selected.read",
        "image.selected.inspect",
        "vault.search",
        "draft.create",
        "note.create",
        "task.create_local",
    ],
    effect_envelope=[EffectClass.READ, EffectClass.WRITE],
    system_prompt="The mobile private-assistant pack uses typed TAL proposals only.",
    controlled_vocabulary={
        "domain_pack": "tal.mobile.private_assistant-0.1.0",
        "network_mode": "local_only",
    },
)
