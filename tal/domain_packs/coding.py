from agents.coder import CODER_PROMPT
from tal.domain_packs.base import DomainPack
from tal.effect_classes import EffectClass

CodingDomainPack = DomainPack(
    name="coder",
    description="Specialized in file authoring, script execution, math, and verification.",
    tools=["write_file", "read_file", "run_command", "python_repl", "calc", "list_files"],
    effect_envelope=[EffectClass.READ, EffectClass.WRITE, EffectClass.EXEC],
    system_prompt=CODER_PROMPT,
    verification_criteria=[{"type": "non_empty"}],
    controlled_vocabulary={
        "WRITE": "write_file",
        "READ": "read_file",
        "EXEC": "run_command",
        "REPL": "python_repl",
        "CALC": "calc"
    }
)
