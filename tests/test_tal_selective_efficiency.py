from agent import BasicAgent
from llm_client import LLMClient
from tal.slm_profile import is_slm_model
from tal_test_runner import TALTestRunner


class DummyLLM(LLMClient):
    def __init__(self, model="mock"):
        super().__init__(model=model)
    @classmethod
    def list_models(cls):
        return ["mock"]
    def generate(self, messages, json_mode=False):
        return '{"thought": "done", "action": null, "final_answer": "42"}'
    def generate_with_retry(self, messages, json_mode=False, max_retries=3, callback=None):
        return '{"thought": "done", "action": null, "final_answer": "42"}'


def test_is_slm_model_detection():
    # SLM models
    assert is_slm_model("gemma3:4b") is True
    assert is_slm_model("gemma:2b") is True
    assert is_slm_model("llama3.2:1b") is True
    assert is_slm_model("llama3.2:3b") is True
    assert is_slm_model("llama3.1:8b") is True
    assert is_slm_model("qwen2.5:3b") is True
    assert is_slm_model("qwen2.5:7b") is True
    assert is_slm_model("phi3:mini") is True
    assert is_slm_model("mistral:7b") is True
    assert is_slm_model("tinyllama") is True
    assert is_slm_model("claude-3-5-haiku") is True
    assert is_slm_model("gemini-2.0-flash-lite") is True

    # Frontier / Large models (NOT SLMs)
    assert is_slm_model("gpt-4o") is False
    assert is_slm_model("gpt-4.5") is False
    assert is_slm_model("claude-3-5-sonnet") is False
    assert is_slm_model("claude-3-opus") is False
    assert is_slm_model("gemini-1.5-pro") is False
    assert is_slm_model("gemini-2.0-pro") is False
    assert is_slm_model("llama3.3:70b") is False
    assert is_slm_model("qwen2.5:72b") is False
    # Frontier variants of SLM family names (must NOT classify as SLM)
    assert is_slm_model("mistral-large") is False
    assert is_slm_model("qwen-max") is False
    assert is_slm_model("gemma-ultra") is False
    assert is_slm_model("gemini-pro") is False
    assert is_slm_model(None) is False
    assert is_slm_model("") is False


def test_selective_reflection_policy():
    agent = BasicAgent(llm_client=DummyLLM())

    # Deterministic tools -> skip reflection (returns False)
    assert agent._should_reflect(["calc"]) is False
    assert agent._should_reflect(["python_repl"]) is False
    assert agent._should_reflect(["write_file"]) is False
    assert agent._should_reflect(["calc", "python_repl"]) is False
    assert agent._should_reflect(["write_file", "list_files"]) is False
    assert agent._should_reflect(["convert_units"]) is False

    # Open-ended research / network tools -> keep reflection (returns True)
    assert agent._should_reflect(["web_search"]) is True
    assert agent._should_reflect(["read_url"]) is True
    assert agent._should_reflect(["web_search", "calc"]) is True

    # No tools executed (pure direct synthesis) -> keep reflection (returns True)
    assert agent._should_reflect([]) is True


def test_agent_auto_detects_slm_profile():
    slm_agent = BasicAgent(llm_client=DummyLLM(model="gemma3:4b"), tal_mode=True)
    assert slm_agent.use_slm_profile is True

    frontier_agent = BasicAgent(llm_client=DummyLLM(model="gpt-4o"), tal_mode=True)
    assert frontier_agent.use_slm_profile is False


def test_tal_test_runner_auto_detects_slm_profile():
    slm_runner = TALTestRunner(llm_client=DummyLLM(model="gemma3:4b"))
    assert slm_runner.use_slm_profile is True

    frontier_runner = TALTestRunner(llm_client=DummyLLM(model="gpt-4o"))
    assert frontier_runner.use_slm_profile is False


def test_reflection_skipped_during_deterministic_react_run(monkeypatch):
    class CountingLLM(DummyLLM):
        def __init__(self):
            super().__init__(model="gemma3:4b")
            self.reflection_called = False

        def generate_with_retry(self, messages, json_mode=False, max_retries=3, callback=None):
            for m in messages:
                if "quality reviewer" in str(m.get("content", "")):
                    self.reflection_called = True
            # First turn: do calc, second turn: final answer
            if not hasattr(self, "_step"):
                self._step = 0
            self._step += 1
            if self._step == 1:
                return '{"thought": "calculating", "action": {"tool": "calc", "args": "{\\"expression\\": \\"10 * 5\\"}"}, "final_answer": null}'
            return '{"thought": "done", "action": null, "final_answer": "50"}'

    client = CountingLLM()
    agent = BasicAgent(
        llm_client=client,
        reflection_enabled=True,
        tal_mode=True
    )

    answer = agent.run_turn("Calculate 10 * 5")
    assert "50" in answer
    # Reflection should NOT have been called because 'calc' is a deterministic tool
    assert client.reflection_called is False
