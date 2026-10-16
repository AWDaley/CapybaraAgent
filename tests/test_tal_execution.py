import time

from agent import BasicAgent
from llm_client import LLMClient
from tal.budget import ExecutionDeadline
from tal.context_packer import ExecutionPhase
from tal.execution import ExecutionErrorCode
from tal.verification import run_verification
from tools.external_tools import create_repl_scope, reset_repl_globals


class _UncooperativeLLM(LLMClient):
    def __init__(self):
        super().__init__("qwen3.5:4b")

    def generate(self, messages, json_mode=False, timeout_seconds=None):
        time.sleep(0.2)
        return '{"thought":"done","action":null,"final_answer":"done"}'

    def generate_with_retry(self, messages, json_mode=False, max_retries=3, callback=None, deadline=None):
        # Intentionally ignores deadline and provider timeout to prove the outer boundary.
        return self.generate(messages, json_mode=json_mode)

    @classmethod
    def list_models(cls):
        return []


class _ScriptedToolLLM(LLMClient):
    def __init__(self, responses):
        super().__init__("scripted")
        self.responses = list(responses)

    def generate(self, messages, json_mode=False, timeout_seconds=None, response_schema=None):
        return self.responses.pop(0)

    def generate_with_retry(self, messages, json_mode=False, max_retries=3, callback=None, deadline=None, response_schema=None):
        return self.generate(messages, json_mode=json_mode, response_schema=response_schema)

    @classmethod
    def list_models(cls):
        return []


def test_agent_hard_deadline_bounds_uncooperative_llm():
    agent = BasicAgent(llm_client=_UncooperativeLLM(), verbose=False, tal_mode=True)
    deadline = ExecutionDeadline.start(0.03)

    started = time.monotonic()
    result = agent.run_turn("Return a short answer.", max_steps=1, deadline=deadline)

    assert time.monotonic() - started < 0.15
    assert "hard deadline" in result
    failure = next(event for event in agent.event_log.events if event.event_type == "llm_call_failed")
    assert failure.data["error_code"] == ExecutionErrorCode.PROVIDER_TIMEOUT.value


def test_typed_result_blocks_syntax_before_python_tool_runs():
    calls = []

    def python_tool(args):
        calls.append(args)
        return "should not run"

    agent = BasicAgent(
        verbose=False,
        tal_mode=True,
        tool_registry={"python_repl": python_tool},
        guardrails_enabled=False,
    )
    agent.current_phase = ExecutionPhase.EXECUTION

    result = agent.act_result("python_repl", '{"code":"for item in:"}')

    assert result.ok is False
    assert result.error_code == ExecutionErrorCode.PREFLIGHT_SYNTAX_ERROR.value
    assert not calls
    blocked = next(event for event in agent.event_log.events if event.event_type == "action_blocked")
    assert blocked.data["error_code"] == ExecutionErrorCode.PREFLIGHT_SYNTAX_ERROR.value


def test_typed_tool_result_is_attached_to_event_log():
    agent = BasicAgent(
        verbose=False,
        tal_mode=True,
        tool_registry={"calc": lambda _args: "4"},
        guardrails_enabled=False,
    )
    agent.current_phase = ExecutionPhase.EXECUTION

    result = agent.act_result("calc", '{"expression":"2+2"}')

    assert result.ok is True
    assert result.stdout == "4"
    event = next(event for event in agent.event_log.events if event.event_type == "tool_executed")
    assert event.data["result_data"]["ok"] is True
    assert event.data["result_data"]["stdout"] == "4"
    assert event.data["queue_wait_seconds"] >= 0
    assert event.data["execution_seconds"] >= 0


def test_llm_call_timeout_uses_configured_cap_without_pipeline_deadline(monkeypatch):
    monkeypatch.setenv("CAPYBARA_LLM_CALL_TIMEOUT", "42")
    agent = BasicAgent(llm_client=_UncooperativeLLM(), verbose=False, tal_mode=True)

    assert agent._llm_call_timeout_seconds(None) == 42.0


def test_tal_rejects_an_unauthorized_tool_before_execution():
    executed = []
    agent = BasicAgent(
        llm_client=_ScriptedToolLLM([
            '{"thought":"inspect","action":{"tool":"list_files","args":{}},"final_answer":null}',
            '{"thought":"run","action":{"tool":"python_repl","args":{"code":"value = 1"}},"final_answer":null}',
        ]),
        verbose=False,
        tal_mode=True,
        tool_registry={"python_repl": lambda args: executed.append(args) or "ok"},
        guardrails_enabled=False,
    )

    result = agent.run_turn("Set value using python_repl.", max_steps=2, stop_after_tool=True,
                            approval_callback=lambda *_: True)

    assert result == "ok"
    assert executed == ['{"code": "value = 1"}']
    violation = next(event for event in agent.event_log.events if event.event_type == "proposal_protocol_error")
    assert "Unauthorized tool 'list_files'" in violation.data["violation"]


def test_tal_prompt_describes_only_active_registry_tools():
    agent = BasicAgent(
        llm_client=_ScriptedToolLLM([]),
        verbose=False,
        tal_mode=True,
        tool_registry={"python_repl": lambda _args: "ok"},
        guardrails_enabled=False,
    )

    prompt = agent._build_system_prompt()

    assert '"tool": "python_repl"' in prompt
    assert '"tool": "list_files"' not in prompt
    assert '"tool": "write_file"' not in prompt


def test_verification_reads_the_explicit_isolated_repl_scope():
    reset_repl_globals()
    scope = create_repl_scope()
    scope.globals["answer"] = 42

    passed, messages = run_verification(
        [{"type": "repl_variable", "variable": "answer", "assertion": "answer == 42"}],
        repl_globals=scope.globals,
    )

    assert passed is True
    assert "assertion passed" in messages[0]
