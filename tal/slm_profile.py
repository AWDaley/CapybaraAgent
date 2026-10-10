import re

from .capability import CapabilityEnvelope
from .epistemic import EpistemicStore


def is_slm_model(model_name: str | None) -> bool:
    """
    Determines if a model is a Small Language Model (SLM) based on model name patterns.
    Recognizes parameter size tags (<= 14B) and compact model family indicators.
    """
    if not model_name:
        return False
    m = str(model_name).lower().strip()

    # Parameter size indicators (e.g. 4b, 7b, 8b, 1.5b, 3.8b)
    size_match = re.search(r'(\d+)(?:\.\d+)?b\b', m)
    if size_match:
        size = int(size_match.group(1))
        return size <= 14

    # Frontier-class indicators — if present, not an SLM regardless of family name
    frontier_indicators = ['large', 'ultra', 'max', 'pro', 'plus', 'turbo']
    if any(ind in m for ind in frontier_indicators):
        return False

    # Keyword indicators using word boundaries or prefix tokens
    slm_patterns = [
        r'\bmini\b', r'\bmicro\b', r'\bnano\b', r'\bsmall\b',
        r'\bflash-lite\b', r'\bflash_lite\b', r'\bphi', r'\bqwen',
        r'\bgemma', r'\bmistral', r'\btiny', r'\bhaiku\b'
    ]
    return any(re.search(pat, m) for pat in slm_patterns)


def build_slm_system_prompt(
    tool_names: list[str],
    capabilities: CapabilityEnvelope | None = None,
    epistemic_store: EpistemicStore | None = None,
    base_role: str = "You are a concise, accurate assistant.",
    tool_descriptions_str: str = ""
) -> str:
    """
    Builds a token-efficient, flat JSON prompt specifically optimized for Small Language Models (SLMs).
    """
    prompt_parts = [
        base_role.strip(),
        "\nYou MUST respond in strict JSON format. Choose ONE of these formats:",
        "1. To run a tool:",
        '{"thought": "<short reason>", "action": {"tool": "<tool_name>", "args": {<json_args>}}, "final_answer": null}',
        "2. To complete the goal:",
        '{"thought": "<short reason>", "action": null, "final_answer": "<your response>"}',
        "3. To ask the user a necessary question:",
        '{"thought": "<short reason>", "query": "<question>"}',
        "4. To escalate an unrecoverable blocker:",
        '{"thought": "<short reason>", "escalate": "<reason>"}',
        "For python_repl code, do not repeat a literal dictionary key; each key may appear only once.",
        "For python_repl, do not import or use os, pathlib, subprocess, open(), or filesystem APIs. "
        "Import a standard-library module only when the step objective explicitly names it.",
        "Use only an explicitly authorized tool name. Never invent or substitute a tool.",
    ]

    if tool_descriptions_str:
        prompt_parts.append("\n" + tool_descriptions_str.strip())
    elif tool_names:
        tools_summary = ", ".join(sorted(tool_names))
        prompt_parts.append(f"\nAuthorized Tools: [{tools_summary}]")

    if capabilities and capabilities.denied:
        prompt_parts.append(f"\nDenied Tools (DO NOT CALL): {', '.join(d['capability'] for d in capabilities.denied)}")

    return "\n".join(prompt_parts)


def build_standard_system_prompt(
    base_prompt: str,
    tool_descriptions_str: str,
    capabilities: CapabilityEnvelope | None = None,
    epistemic_store: EpistemicStore | None = None,
    structured_output: bool = True
) -> str:
    """
    Builds standard comprehensive prompt for frontier / larger models.
    """
    instructions = (
        "\n\nYou MUST respond in pure JSON format.\n"
        "To use a tool, return:\n"
        "{\n"
        '  "thought": "<explain why you need to use a tool>",\n'
        '  "action": {"tool": "tool_name", "args": "tool_arguments"},\n'
        '  "final_answer": null\n'
        "}\n"
        "\n"
        "If you have the final answer, return:\n"
        "{\n"
        '  "thought": "<explain your final reasoning>",\n'
        '  "action": null,\n'
        '  "final_answer": "<your response to the user>"\n'
        "}"
    ) if structured_output else ""

    parts = [base_prompt.strip(), tool_descriptions_str.strip(), instructions]

    if capabilities:
        cap_str = capabilities.to_context_string()
        if cap_str:
            parts.append("\n" + cap_str)

    return "\n\n".join(p for p in parts if p)
