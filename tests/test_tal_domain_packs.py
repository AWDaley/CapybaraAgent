from llm_client import LLMClient
from tal.domain_packs import (
    GLOBAL_DOMAIN_REGISTRY,
    DomainPack,
)
from tal.effect_classes import EffectClass


class MockLLM(LLMClient):
    def __init__(self):
        super().__init__(model="mock")
    def generate(self, messages, json_mode=False):
        return "mock response"
    @staticmethod
    def list_models():
        return ["mock"]


def test_domain_pack_registry_contents():
    packs = GLOBAL_DOMAIN_REGISTRY.list_packs()
    assert "coder" in packs
    assert "researcher" in packs
    assert "general" in packs


def test_coding_domain_pack_attributes():
    pack = GLOBAL_DOMAIN_REGISTRY.get("coder")
    assert pack is not None
    assert "write_file" in pack.tools
    assert "run_command" in pack.tools
    assert EffectClass.EXEC in pack.effect_envelope
    assert EffectClass.WRITE in pack.effect_envelope


def test_research_domain_pack_attributes():
    pack = GLOBAL_DOMAIN_REGISTRY.get("researcher")
    assert pack is not None
    assert "web_search" in pack.tools
    assert "read_url" in pack.tools
    assert EffectClass.NETWORK in pack.effect_envelope


def test_create_specialist_from_pack():
    mock_llm = MockLLM()
    specialist = GLOBAL_DOMAIN_REGISTRY.create_specialist(
        name="coder",
        llm_client=mock_llm,
        tal_mode=True
    )
    assert specialist.tal_mode is True
    assert "write_file" in specialist.tools
    assert "web_search" not in specialist.tools


def test_custom_domain_pack_registration():
    custom_pack = DomainPack(
        name="data_scientist",
        description="Analyzes tabular data and produces statistical plots",
        tools=["python_repl", "calc", "read_file"],
        effect_envelope=[EffectClass.READ, EffectClass.EXEC],
        system_prompt="You are a data science expert."
    )
    GLOBAL_DOMAIN_REGISTRY.register(custom_pack)
    assert "data_scientist" in GLOBAL_DOMAIN_REGISTRY.list_packs()
    
    retrieved = GLOBAL_DOMAIN_REGISTRY.get("data_scientist")
    assert retrieved.name == "data_scientist"
    assert "python_repl" in retrieved.tools
