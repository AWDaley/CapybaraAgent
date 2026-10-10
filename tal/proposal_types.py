import json
import re
from dataclasses import dataclass
from typing import Any, Union


@dataclass
class ActionProposal:
    """Model proposes executing a tool action."""
    thought: str
    tool_name: str
    tool_args: Any
    proposal_type: str = "action"


@dataclass
class CompleteProposal:
    """Model declares task completion with a final answer."""
    thought: str
    final_answer: str
    proposal_type: str = "complete"


@dataclass
class EscalateProposal:
    """Model or harness requests escalation / intervention."""
    thought: str
    reason: str
    context: str = ""
    error_code: str | None = None
    violation: str = ""
    proposal_type: str = "escalate"


@dataclass
class QueryProposal:
    """Model asks the user a clarifying question before proceeding."""
    thought: str
    question: str
    proposal_type: str = "query"


Proposal = Union[ActionProposal, CompleteProposal, EscalateProposal, QueryProposal]

# Providers that support constrained JSON can use this as an output format.
# Strict parsing below remains the final authority because provider support and
# schema enforcement vary by model/runtime.
TAL_PROPOSAL_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "thought": {"type": "string"},
        "action": {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["tool", "args"],
                    "properties": {
                        "tool": {"type": "string", "minLength": 1},
                        "args": {"type": ["object", "array", "string"]},
                    },
                },
                {"type": "null"},
            ]
        },
        "final_answer": {"type": ["string", "null"]},
        "query": {"type": "string", "minLength": 1},
        "escalate": {"type": "string", "minLength": 1},
    },
}


def tal_proposal_json_schema(allowed_tools: list[str] | None = None) -> dict[str, Any]:
    """Return the closed TAL schema, optionally restricting action tool names.

    The generic constant remains useful for providers that do not receive a
    per-step tool allowlist. Pipeline specialists should pass their actual
    allowlist so native JSON-schema providers can reject invented tool names.
    """
    schema = json.loads(json.dumps(TAL_PROPOSAL_JSON_SCHEMA))
    if allowed_tools:
        tool_schema = schema["properties"]["action"]["anyOf"][0]["properties"]["tool"]
        tool_schema.pop("minLength", None)
        tool_schema["enum"] = list(dict.fromkeys(allowed_tools))
    return schema


class ProposalProtocolError(ValueError):
    """Raised when a model response violates the closed TAL proposal protocol."""


def parse_strict_proposal(response_text: str) -> Proposal:
    """Parse the four TAL proposal types without fuzzy extraction.

    This is the normal production path for TAL mode.  Legacy parsing remains
    available for non-TAL compatibility and migration tests.
    """
    try:
        data = json.loads(response_text.strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProposalProtocolError("Proposal must be a valid JSON object") from exc
    if not isinstance(data, dict):
        raise ProposalProtocolError("Proposal must be a JSON object")

    allowed = {"thought", "action", "final_answer", "query", "escalate"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ProposalProtocolError(f"Proposal contains unsupported field(s): {', '.join(unknown)}")
    thought = str(data.get("thought") or "")

    if "query" in data:
        if set(data) - {"thought", "query"}:
            raise ProposalProtocolError("Query proposal may contain only thought and query")
        question = data["query"]
        if not isinstance(question, str) or not question.strip():
            raise ProposalProtocolError("Query proposal requires a non-empty query string")
        return QueryProposal(thought=thought, question=question)

    if "escalate" in data:
        if set(data) - {"thought", "escalate"}:
            raise ProposalProtocolError("Escalate proposal may contain only thought and escalate")
        reason = data["escalate"]
        if not isinstance(reason, str) or not reason.strip():
            raise ProposalProtocolError("Escalate proposal requires a non-empty reason")
        return EscalateProposal(thought=thought, reason=reason, context=response_text)

    if "action" not in data:
        raise ProposalProtocolError("Proposal requires action, query, or escalate")
    action = data["action"]
    if isinstance(action, dict):
        if set(action) != {"tool", "args"}:
            raise ProposalProtocolError("Action must contain exactly tool and args")
        if set(data) - {"thought", "action", "final_answer"}:
            raise ProposalProtocolError("Action proposal contains unsupported fields")
        if data.get("final_answer") is not None:
            raise ProposalProtocolError("Action proposal final_answer must be null")
        tool_name = action["tool"]
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ProposalProtocolError("Action tool must be a non-empty string")
        tool_args = action["args"]
        if not isinstance(tool_args, (dict, list, str)):
            raise ProposalProtocolError("Action args must be an object, list, or string")
        return ActionProposal(
            thought=thought,
            tool_name=tool_name,
            tool_args=json.dumps(tool_args) if isinstance(tool_args, (dict, list)) else tool_args,
        )

    if action is None:
        if set(data) - {"thought", "action", "final_answer"}:
            raise ProposalProtocolError("Complete proposal contains unsupported fields")
        final_answer = data.get("final_answer")
        if not isinstance(final_answer, str) or not final_answer.strip():
            raise ProposalProtocolError("Complete proposal requires a non-empty final_answer")
        return CompleteProposal(thought=thought, final_answer=final_answer)

    raise ProposalProtocolError("Action must be an object or null")


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Extracts first valid JSON object block from string."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"':
            in_string = not in_string
        if not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    raw_block = text[start:i+1]
                    try:
                        return json.loads(raw_block)
                    except json.JSONDecodeError:
                        return None
    return None


def _extract_fuzzy_action_proposal(cleaned: str) -> ActionProposal | None:
    """Resiliently extracts an ActionProposal when JSON is malformed due to unescaped code strings."""
    if not cleaned:
        return None

    # Check for thought
    thought = ""
    thought_m = re.search(r'["\']thought["\']\s*:\s*["\'](.*?)["\']\s*,\s*["\'](?:action|tool)', cleaned, re.DOTALL)
    if not thought_m:
        thought_m = re.search(r'["\']thought["\']\s*:\s*["\']([^"\']*)["\']', cleaned)
    if thought_m:
        thought = thought_m.group(1).strip()

    # Check for tool name
    tool_m = re.search(r'["\']tool["\']\s*:\s*["\']([a-zA-Z0-9_-]+)["\']', cleaned)
    if not tool_m:
        tool_m = re.search(r'["\']action["\']\s*:\s*\{\s*["\']tool["\']\s*:\s*["\']([a-zA-Z0-9_-]+)["\']', cleaned)
    if not tool_m:
        tool_m = re.search(r'["\']action["\']\s*:\s*["\']([a-zA-Z0-9_-]+)["\']', cleaned)

    if not tool_m:
        return None

    tool_name = tool_m.group(1).strip()
    if tool_name.lower() in ("null", "none", "complete", "finish"):
        return None

    # Handle python_repl code extraction
    if tool_name == "python_repl":
        code_m = re.search(r'["\']code["\']\s*:\s*["\']([\s\S]*?)(?:["\']\s*\}\s*\}|["\']\s*\}\s*$)', cleaned)
        if not code_m:
            code_m = re.search(r'["\']code["\']\s*:\s*["\']([\s\S]*)', cleaned)
        if code_m:
            code_str = code_m.group(1)
            # Clean up JSON escape sequences
            code_str = code_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace("\\'", "'")
            # Strip trailing unmatched quotes / closing braces
            code_str = re.sub(r'["\']\s*\}*\s*$', '', code_str).rstrip()
            return ActionProposal(
                thought=thought,
                tool_name=tool_name,
                tool_args=json.dumps({"code": code_str})
            )

    # Handle write_file path and content extraction
    if tool_name == "write_file":
        path_m = re.search(r'["\']path["\']\s*:\s*["\']([^"\']+)["\']', cleaned)
        path = path_m.group(1).strip() if path_m else "output.txt"
        content_m = re.search(r'["\']content["\']\s*:\s*["\']([\s\S]*?)(?:["\']\s*\}\s*\}|["\']\s*\}\s*$)', cleaned)
        if not content_m:
            content_m = re.search(r'["\']content["\']\s*:\s*["\']([\s\S]*)', cleaned)
        content_str = content_m.group(1) if content_m else ""
        content_str = content_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace("\\'", "'")
        content_str = re.sub(r'["\']\s*\}*\s*$', '', content_str).rstrip()
        return ActionProposal(
            thought=thought,
            tool_name=tool_name,
            tool_args=json.dumps({"path": path, "content": content_str})
        )

    # Handle generic tool extraction
    args_m = re.search(r'["\']args["\']\s*:\s*(\{[\s\S]*\})', cleaned)
    if args_m:
        raw_args = args_m.group(1)
        try:
            parsed_args = json.loads(raw_args)
            return ActionProposal(thought=thought, tool_name=tool_name, tool_args=json.dumps(parsed_args))
        except Exception:
            return ActionProposal(thought=thought, tool_name=tool_name, tool_args=raw_args)

    return ActionProposal(thought=thought, tool_name=tool_name, tool_args="{}")


def parse_proposal(response_text: str) -> Proposal:
    """
    Parses an LLM response into a typed Proposal instance.
    Supports structured JSON, flat SLM JSON, and ReAct text fallbacks.
    """
    cleaned = response_text.strip()
    if not cleaned:
        return EscalateProposal(
            thought="Empty response received",
            reason="Model emitted an empty response",
            context=""
        )

    # 1. Try direct full JSON parsing
    parsed_json = None
    try:
        parsed_json = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting JSON object block
        parsed_json = _extract_json_block(cleaned)

    if isinstance(parsed_json, dict):
        thought = str(parsed_json.get("thought") or parsed_json.get("reasoning") or "")
        
        # Check for Escalation
        if "escalate" in parsed_json or "escalation" in parsed_json:
            reason = str(parsed_json.get("escalate") or parsed_json.get("escalation") or parsed_json.get("reason") or "Escalation requested")
            return EscalateProposal(thought=thought, reason=reason, context=cleaned)

        # Check for Query
        if "query" in parsed_json or "question" in parsed_json:
            q = str(parsed_json.get("query") or parsed_json.get("question"))
            return QueryProposal(thought=thought, question=q)

        # Check for Action (Structured: {"action": {"tool": "...", "args": ...}})
        action_val = parsed_json.get("action")
        if isinstance(action_val, dict) and ("tool" in action_val or "name" in action_val):
            t_name = str(action_val.get("tool") or action_val.get("name") or "")
            t_args = action_val.get("args", {})
            if isinstance(t_args, (dict, list)):
                t_args = json.dumps(t_args)
            else:
                t_args = str(t_args)
            return ActionProposal(thought=thought, tool_name=t_name, tool_args=t_args)

        # Check for Action (Flat SLM style: {"action": "write_file", "path": "...", "content": "..."} or {"tool": "...", "args": ...})
        if isinstance(action_val, str) and action_val and action_val.lower() != "null":
            # Remaining keys form the tool arguments
            tool_args_dict = {k: v for k, v in parsed_json.items() if k not in ("action", "thought", "reasoning", "final_answer")}
            return ActionProposal(
                thought=thought,
                tool_name=action_val,
                tool_args=json.dumps(tool_args_dict) if tool_args_dict else "{}"
            )

        if "tool" in parsed_json:
            t_name = str(parsed_json["tool"])
            t_args = parsed_json.get("args", {})
            if isinstance(t_args, (dict, list)):
                t_args = json.dumps(t_args)
            else:
                t_args = str(t_args)
            return ActionProposal(thought=thought, tool_name=t_name, tool_args=t_args)

        # Check for Completion
        final_answer = parsed_json.get("final_answer") or parsed_json.get("answer")
        if final_answer is not None:
            return CompleteProposal(thought=thought, final_answer=str(final_answer))

    # 2. Resilient Fuzzy Action Proposal Extraction (handles malformed action JSON with code strings)
    fuzzy_prop = _extract_fuzzy_action_proposal(cleaned)
    if fuzzy_prop is not None:
        return fuzzy_prop

    # 3. Text / Regex ReAct format fallback
    thought = ""
    thought_match = re.search(r'Thought:(.*?)(?:Action:|Final Answer:|Escalate:|$)', cleaned, re.DOTALL | re.IGNORECASE)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Final Answer in text
    final_match = re.search(r'Final Answer:(.*?)$', cleaned, re.DOTALL | re.IGNORECASE)
    if final_match:
        return CompleteProposal(thought=thought, final_answer=final_match.group(1).strip())

    # Action in text
    action_match = re.search(r'Action:\s*(\{.*?\})', cleaned, re.DOTALL | re.IGNORECASE)
    if action_match:
        try:
            act_dict = json.loads(action_match.group(1))
            t_name = act_dict.get("tool", "")
            t_args = act_dict.get("args", {})
            if isinstance(t_args, (dict, list)):
                t_args = json.dumps(t_args)
            else:
                t_args = str(t_args)
            if t_name:
                return ActionProposal(thought=thought, tool_name=t_name, tool_args=t_args)
        except Exception:
            pass

    # Default fallback: Treat non-empty text as a direct final answer
    return CompleteProposal(thought=thought, final_answer=cleaned)
