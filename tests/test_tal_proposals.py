import json

import pytest

from tal.proposal_types import (
    ActionProposal,
    CompleteProposal,
    EscalateProposal,
    ProposalProtocolError,
    QueryProposal,
    parse_proposal,
    parse_strict_proposal,
    tal_proposal_json_schema,
)
from tal.repair import repair_json_string


def test_parse_structured_action_proposal():
    raw = '{"thought": "I need to calculate something", "action": {"tool": "calc", "args": {"expression": "2 + 2"}}, "final_answer": null}'
    prop = parse_proposal(raw)
    assert isinstance(prop, ActionProposal)
    assert prop.thought == "I need to calculate something"
    assert prop.tool_name == "calc"
    assert json.loads(prop.tool_args) == {"expression": "2 + 2"}


def test_strict_protocol_accepts_closed_action_envelope():
    prop = parse_strict_proposal(
        '{"thought":"calculate","action":{"tool":"calc","args":{"expression":"2+2"}},"final_answer":null}'
    )

    assert isinstance(prop, ActionProposal)
    assert prop.tool_name == "calc"


def test_native_schema_restricts_action_to_active_tools():
    schema = tal_proposal_json_schema(["python_repl"])

    tool_schema = schema["properties"]["action"]["anyOf"][0]["properties"]["tool"]
    assert tool_schema == {"type": "string", "enum": ["python_repl"]}


def test_strict_protocol_rejects_flat_or_extra_fields():
    with pytest.raises(ProposalProtocolError, match="Action must be an object"):
        parse_strict_proposal('{"thought":"list","action":"list_files"}')
    with pytest.raises(ProposalProtocolError, match="unsupported field"):
        parse_strict_proposal('{"thought":"done","action":null,"final_answer":"ok","extra":true}')


def test_parse_flat_slm_action_proposal():
    raw = '{"thought": "Inspecting files", "action": "list_files"}'
    prop = parse_proposal(raw)
    assert isinstance(prop, ActionProposal)
    assert prop.tool_name == "list_files"


def test_parse_complete_proposal():
    raw = '{"thought": "Calculated successfully", "action": null, "final_answer": "The answer is 4."}'
    prop = parse_proposal(raw)
    assert isinstance(prop, CompleteProposal)
    assert prop.final_answer == "The answer is 4."


def test_parse_escalate_proposal():
    raw = '{"thought": "Cannot continue", "escalate": "Permission denied by security policy"}'
    prop = parse_proposal(raw)
    assert isinstance(prop, EscalateProposal)
    assert "Permission denied" in prop.reason


def test_parse_query_proposal():
    raw = '{"thought": "Need clarification", "query": "Which file would you like me to inspect?"}'
    prop = parse_proposal(raw)
    assert isinstance(prop, QueryProposal)
    assert "Which file" in prop.question


def test_repair_json_string():
    # Single quotes and trailing commas
    malformed = "{'thought': 'thinking', 'action': {'tool': 'calc', 'args': {'expression': '1+1'},},}"
    repaired = repair_json_string(malformed)
    parsed = json.loads(repaired)
    assert parsed["thought"] == "thinking"
    assert parsed["action"]["tool"] == "calc"


def test_repair_markdown_code_fence():
    fenced = "```json\n{\"thought\": \"fenced\", \"final_answer\": \"done\"}\n```"
    repaired = repair_json_string(fenced)
    parsed = json.loads(repaired)
    assert parsed["final_answer"] == "done"


def test_parse_proposal_unescaped_code_fstring():
    # Exact scenario where 4B SLM emitted nested unescaped quotes inside python_repl code
    raw = '{"thought": "Executing backtest", "action": {"tool": "python_repl", "args": {"code": "import json\\nprint(f\\"Initial price: ${\\"starting_price\\":.2f}\\")"}}}'
    prop = parse_proposal(raw)
    assert isinstance(prop, ActionProposal)
    assert prop.tool_name == "python_repl"
    args = json.loads(prop.tool_args)
    assert "import json" in args["code"]
    assert "print(f" in args["code"]


def test_action_with_malformed_json_never_becomes_complete():
    # Malformed JSON containing action markers must not drop into CompleteProposal
    raw = '{"thought": "Writing file", "action": {"tool": "write_file", "args": {"path": "test.txt", "content": "hello "world" unescaped"}}}'
    prop = parse_proposal(raw)
    assert isinstance(prop, ActionProposal)
    assert prop.tool_name == "write_file"
    args = json.loads(prop.tool_args)
    assert args["path"] == "test.txt"
    assert "hello" in args["content"]


def test_repair_trailing_unmatched_brackets_and_braces():
    # SLM emits trailing redundant braces
    raw_trailing = '{"thought": "done", "action": null, "final_answer": "Report finished"}}}}'
    repaired = repair_json_string(raw_trailing)
    parsed = json.loads(repaired)
    assert parsed["final_answer"] == "Report finished"

    # SLM truncated unclosed quote and brace
    raw_unclosed = '{"thought": "working", "action": null, "final_answer": "Incomplete report'
    repaired = repair_json_string(raw_unclosed)
    parsed = json.loads(repaired)
    assert "Incomplete report" in parsed["final_answer"]
