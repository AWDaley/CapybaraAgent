import json

from agents.agent_registry import AGENT_REGISTRY
from agents.coder import CODER_PROMPT
from tal.repair import repair_json_string, sanitize_json_string_values
from tal.schemas import RememberParams, WriteFileParams
from tools.external_tools import EXTERNAL_TOOL_DESCRIPTIONS


def test_sanitize_json_string_values_raw_newlines():
    raw_json = '{"path": "test.txt", "content": "# Title\n\nLine 2\n- Bullet"}'
    sanitized = sanitize_json_string_values(raw_json)
    parsed = json.loads(sanitized)
    assert parsed["path"] == "test.txt"
    assert parsed["content"] == "# Title\n\nLine 2\n- Bullet"


def test_sanitize_json_string_values_preserves_escaped_sequences():
    raw_json = r'{"code": "print(\"hello\\nworld\")\nx = 10"}'
    sanitized = sanitize_json_string_values(raw_json)
    # The escaped \\n inside print string should remain intact
    parsed = json.loads(sanitized)
    assert "print(\"hello\\nworld\")" in parsed["code"]


def test_repair_json_string_with_raw_newlines_and_single_quotes():
    raw = """```json
    {'path': 'summary.md', 'content': 'Line 1
Line 2
Line 3',}
```"""
    repaired = repair_json_string(raw)
    parsed = json.loads(repaired)
    assert parsed["path"] == "summary.md"
    assert "Line 1\nLine 2\nLine 3" in parsed["content"]


def test_schema_from_json_with_raw_multiline_content():
    # Simulate SLM emitting literal unescaped newlines in write_file arguments
    raw_payload = '{"path": "notes.txt", "content": "Header\n\nParagraph text\n- item 1\n- item 2"}'
    params = WriteFileParams.from_json(raw_payload, "write_file")
    assert isinstance(params, WriteFileParams)
    assert params.path == "notes.txt"
    assert "Header\n\nParagraph text" in params.content


def test_schema_from_json_remember_with_raw_newlines():
    # Simulate SLM emitting literal newlines in remember tool
    raw_payload = '{"key": "compound_interest", "value": "Principal: $1000\nRate: 5%\nTotal: $1283.36"}'
    params = RememberParams.from_json(raw_payload, "remember")
    assert isinstance(params, RememberParams)
    assert params.key == "compound_interest"
    assert "Principal: $1000\nRate: 5%" in params.value


def test_python_repl_tool_description_has_input_guard():
    assert "python_repl" in EXTERNAL_TOOL_DESCRIPTIONS
    assert "input()" in EXTERNAL_TOOL_DESCRIPTIONS
    assert "Hardcode" in EXTERNAL_TOOL_DESCRIPTIONS or "hardcode" in EXTERNAL_TOOL_DESCRIPTIONS


def test_coder_prompt_has_python_repl_and_input_guard():
    assert "python_repl" in CODER_PROMPT
    assert "input()" in CODER_PROMPT
    assert "python_repl" in AGENT_REGISTRY["coder"]["tools"]


def test_orchestrator_resets_consecutive_errors(monkeypatch):
    from agents.orchestrator import OrchestratorAgent
    from llm_client import LLMClient

    class MockLLM(LLMClient):
        def __init__(self):
            super().__init__(model="mock")
        @classmethod
        def list_models(cls):
            return ["mock"]
        def generate(self, messages, json_mode=False):
            sys_msg = str(messages[0].get("content", "")) if messages else ""
            if "synthesize" in sys_msg.lower():
                return "Final synthesized mock answer"
            return "DELEGATE: researcher: Find info\nDELEGATE: coder: Write code"
        def generate_with_retry(self, messages, json_mode=False, max_retries=3, callback=None):
            return '{"thought": "done", "action": null, "final_answer": "specialist result"}'

    orchestrator = OrchestratorAgent(
        llm_client=MockLLM(),
        tal_mode=True,
        verbose=False
    )

    assert orchestrator.tal_mode is True
    result = orchestrator.run("Test goal")
    assert "Final synthesized mock answer" in result


def test_is_slm_model_qwen():
    from tal.slm_profile import is_slm_model
    assert is_slm_model("qwen3.5:4b") is True
    assert is_slm_model("qwen 3.5 4b") is True
    assert is_slm_model("qwen2.5:3b") is True
    assert is_slm_model("qwen2.5-coder:7b") is True
    assert is_slm_model("gpt-4o") is False


def test_sanitize_repl_code():
    from tools.external_tools import _sanitize_repl_code

    # Markdown fence
    code1 = "```python\nprint(1 + 1)\n```"
    assert _sanitize_repl_code(code1) == "print(1 + 1)"

    # Outer triple quotes wrapper
    code2 = '"""\nimport math\nprint(math.sqrt(16))\n"""'
    assert "import math" in _sanitize_repl_code(code2)
    assert not _sanitize_repl_code(code2).startswith('"""')

    # Trailing dangling triple quotes
    code3 = 'result = 42\nprint(result)"""'
    assert _sanitize_repl_code(code3) == 'result = 42\nprint(result)'

    # Trailing unmatched closing braces / brackets / parens
    code4 = 'print(telemetry_json)}'
    assert _sanitize_repl_code(code4) == 'print(telemetry_json)'

    code5 = 'data = [1, 2, 3]]'
    assert _sanitize_repl_code(code5) == 'data = [1, 2, 3]'

    code6 = 'print({"status": True})}}'
    assert _sanitize_repl_code(code6) == 'print({"status": True})'


def test_python_repl_robust_execution():
    from tools.external_tools import python_repl, reset_repl_globals
    reset_repl_globals()

    # Pass JSON with trailing triple quotes in code
    raw_json = json.dumps({"code": "x = 10\ny = 20\nprint(x + y)'''"})
    output = python_repl(raw_json)
    assert "30" in output

    # Pass raw python dict string directly
    dict_str = "{'code': 'print(100 * 2)'}"
    output = python_repl(dict_str)
    assert "200" in output


def test_orchestrator_fallback_synthesis():
    from agents.orchestrator import OrchestratorAgent
    from llm_client import LLMClient

    class EmptySynthesisLLM(LLMClient):
        def __init__(self):
            super().__init__(model="mock")
        @classmethod
        def list_models(cls):
            return ["mock"]
        def generate(self, messages, json_mode=False):
            sys_msg = str(messages[0].get("content", "")) if messages else ""
            if "synthesize" in sys_msg.lower() or "summarize" in sys_msg.lower():
                # Simulate model returning empty string during synthesis
                return ""
            return "DELEGATE: coder: Compute primes"
        def generate_with_retry(self, messages, json_mode=False, max_retries=3, callback=None):
            return '{"thought": "done", "action": null, "final_answer": "Found 15 primes with sum 328."}'

    orchestrator = OrchestratorAgent(
        llm_client=EmptySynthesisLLM(),
        tal_mode=True,
        verbose=False
    )

    result = orchestrator.run("Generate primes and save to primes_report.txt")
    # Result must not be empty and must include specialist context
    assert result and result.strip() != ""
    assert "Found 15 primes with sum 328." in result
    assert "Summary of Task" in result
    # Telemetry should also have logged the completed task
    assert len(orchestrator.event_log.events) > 0


def test_agent_duplicate_action_loop_breaker():
    from agent import BasicAgent
    from llm_client import LLMClient

    class RepeatLLM(LLMClient):
        def __init__(self):
            super().__init__(model="mock-slm:4b")
            self.turn = 0
        @classmethod
        def list_models(cls):
            return ["mock"]
        def generate(self, messages, json_mode=False):
            return self.generate_with_retry(messages, json_mode=json_mode)
        def generate_with_retry(self, messages, json_mode=False, max_retries=3, retry_delay=1.0, callback=None):
            self.turn += 1
            if self.turn in (1, 2):
                # Model repeatedly sends identical failing code
                return '{"thought": "trying division", "action": {"tool": "python_repl", "args": {"code": "1 / 0"}}, "final_answer": null}'
            return '{"thought": "fixed", "action": null, "final_answer": "Handled division by zero"}'

    agent = BasicAgent(
        llm_client=RepeatLLM(),
        tal_mode=True,
        guardrails_enabled=False,
        verbose=False
    )

    ans = agent.run_turn("Divide 1 by 0", max_steps=5)
    assert ans == "Handled division by zero"
    # Verify memory contains the repetition warning
    tool_observations = [m["content"] for m in agent.memory if m.get("role") == "tool"]
    assert any("[REPETITION WARNING]" in obs for obs in tool_observations)

