from agents.researcher import RESEARCHER_PROMPT
from tal.domain_packs.base import DomainPack
from tal.effect_classes import EffectClass

ResearchDomainPack = DomainPack(
    name="researcher",
    description="Specialized in web search, URL reading, fact verification, and knowledge synthesis.",
    tools=["web_search", "read_url", "recall", "remember", "read_file", "list_files"],
    effect_envelope=[EffectClass.READ, EffectClass.NETWORK, EffectClass.WRITE],
    system_prompt=RESEARCHER_PROMPT,
    verification_criteria=[{"type": "non_empty"}],
    controlled_vocabulary={
        "SEARCH": "web_search",
        "READ_URL": "read_url",
        "RECALL": "recall",
        "REMEMBER": "remember"
    }
)
