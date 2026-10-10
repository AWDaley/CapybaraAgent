import ast
import json
import re

from .proposal_types import (
    ActionProposal,
    CompleteProposal,
    EscalateProposal,
    Proposal,
    ProposalProtocolError,
    parse_proposal,
    parse_strict_proposal,
)

MAX_REPAIR_ATTEMPTS = 2


def sanitize_json_string_values(raw: str) -> str:
    """Escape raw control characters inside JSON string values.
    
    SLMs frequently emit literal newlines/tabs inside JSON strings
    instead of escaped \\n/\\t sequences. Handles both double and single
    quoted string values.
    """
    result = []
    in_quote = None  # None, '"', or "'"
    escape_next = False
    
    for ch in raw:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\' and in_quote is not None:
            result.append(ch)
            escape_next = True
            continue
        if ch in ('"', "'"):
            if in_quote is None:
                in_quote = ch
            elif in_quote == ch:
                in_quote = None
            result.append(ch)
            continue
        if in_quote is not None:
            if ch == '\n':
                result.append('\\n')
                continue
            elif ch == '\r':
                result.append('\\r')
                continue
            elif ch == '\t':
                result.append('\\t')
                continue
        result.append(ch)
    
    return ''.join(result)


def repair_json_string(raw: str) -> str:
    """Fix common JSON mistakes emitted by LLMs/SLMs."""
    if not isinstance(raw, str):
        try:
            return json.dumps(raw)
        except Exception:
            return str(raw)

    s = raw.strip()

    # Extract content inside markdown code fences ```json ... ``` or ``` ... ``` if it looks like JSON
    fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```', s)
    if fence_match:
        s = fence_match.group(1).strip()

    # Fast path: already valid JSON
    try:
        json.loads(s)
        return s
    except Exception:
        pass

    # Try ast.literal_eval for single-quoted Python dict/list literals emitted by SLMs
    try:
        val = ast.literal_eval(s)
        if isinstance(val, (dict, list)):
            return json.dumps(val)
    except Exception:
        pass

    # Pre-process raw control characters inside JSON strings (literal newlines/tabs)
    s = sanitize_json_string_values(s)

    # Single-quoted keys/values to double-quotes
    s = re.sub(r"(?<=[{,:\[\s])'([^'\\]*(?:\\.[^'\\]*)*)'(?=[}:,\]\s])", r'"\1"', s)
    # Trailing commas in objects & arrays
    s = re.sub(r',\s*}', '}', s)
    s = re.sub(r',\s*]', ']', s)
    # Unquoted keys
    s = re.sub(r'([{,]\s*)(\w+)\s*:', r'\1"\2":', s)

    # Strip excess trailing closing braces/brackets emitted by SLMs (e.g. }}}}, ]]])
    while (s.endswith('}') or s.endswith(' ')) and s.count('}') > s.count('{'):
        s = s.rstrip()
        if s.endswith('}') and s.count('}') > s.count('{'):
            s = s[:-1]
    while (s.endswith(']') or s.endswith(' ')) and s.count(']') > s.count('['):
        s = s.rstrip()
        if s.endswith(']') and s.count(']') > s.count('['):
            s = s[:-1]

    # Balance unclosed quotes if truncated
    unescaped_quotes = len(re.findall(r'(?<!\\)"', s))
    if unescaped_quotes % 2 == 1:
        s += '"'

    # Balance unclosed brackets & braces if truncated
    open_sq = s.count('[')
    close_sq = s.count(']')
    if open_sq > close_sq:
        s += ']' * (open_sq - close_sq)

    open_curly = s.count('{')
    close_curly = s.count('}')
    if open_curly > close_curly:
        s += '}' * (open_curly - close_curly)

    return s


def repair_and_parse(raw_output: str, llm_client=None, structured: bool = True, strict: bool = False) -> Proposal:
    """
    Attempts to parse raw output into a Proposal with heuristic repair.
    If parsing fails and an LLM client is provided, performs bounded re-prompting.
    """
    cleaned = raw_output.strip()
    if not cleaned:
        return EscalateProposal(
            thought="Empty response received",
            reason="Model returned an empty response",
            context="",
            error_code="empty_model_response",
            violation="response was empty",
        )

    parser = parse_strict_proposal if strict else parse_proposal

    # 1. First attempt: Direct parse with deterministic JSON repair
    try:
        repaired = repair_json_string(cleaned)
        proposal = parser(repaired)
        # If successfully parsed an Action with valid tool name or Complete with answer
        if isinstance(proposal, (ActionProposal, CompleteProposal, EscalateProposal)):
            return proposal
    except (ProposalProtocolError, ValueError, TypeError) as exc:
        if strict:
            return EscalateProposal(
                thought="Invalid proposal protocol",
                reason="Model output did not match the closed TAL proposal schema",
                context=cleaned,
                error_code="proposal_protocol_error",
                violation=str(exc),
            )

    # Strict TAL mode deliberately avoids fuzzy parsing and repair-model turns.
    if strict:
        return EscalateProposal(
            thought="Invalid proposal protocol",
            reason="Model output did not match the closed TAL proposal schema",
            context=cleaned,
            error_code="proposal_protocol_error",
            violation="strict proposal parsing did not produce an actionable proposal",
        )

    # 2. Bounded LLM repair loop for legacy, non-TAL compatibility.
    current_raw = cleaned
    if llm_client is not None:
        for attempt in range(MAX_REPAIR_ATTEMPTS):
            repair_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a strict JSON repair utility. The previous model output was malformed. "
                        "Fix the JSON syntax and output ONLY valid JSON matching either:\n"
                        '{"thought": "...", "action": {"tool": "<tool_name>", "args": {..}}, "final_answer": null}\n'
                        "OR\n"
                        '{"thought": "...", "action": null, "final_answer": "<final response text>"}'
                    )
                },
                {
                    "role": "user",
                    "content": f"Fix this malformed output into valid JSON:\n\n{current_raw}"
                }
            ]
            try:
                fixed_text = llm_client.generate(repair_prompt, json_mode=structured)
                if fixed_text and fixed_text.strip():
                    fixed_repaired = repair_json_string(fixed_text)
                    proposal = parse_proposal(fixed_repaired)
                    if isinstance(proposal, (ActionProposal, CompleteProposal)):
                        return proposal
                    current_raw = fixed_text
            except Exception:
                pass

    # 3. Fallback proposal if all repair passes fail
    return parse_proposal(cleaned)
