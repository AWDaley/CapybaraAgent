import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from agent import BasicAgent
from context_manager import ContextManager
from llm_client import LLMClient
from memory.knowledge_store import KnowledgeStore
from memory.session_manager import SessionManager
from providers.ollama_provider import OllamaProvider
from token_counter import TokenCounter
from tools.file_tools import _get_safe_path


class LocalMockLLM(LLMClient):
    def __init__(self, text="Summary of conversation"):
        super().__init__(model="mock")
        self.text = text
    def generate(self, messages, json_mode=False):
        return self.text
    @staticmethod
    def list_models():
        return ["mock"]

def test_json_repair_apostrophe_preservation():
    agent = BasicAgent(verbose=False)
    raw = "{'tool': 'calculator', 'args': 'it\'s fine'}"
    repaired = agent._repair_json(raw)
    assert '"tool": "calculator"' in repaired

def test_token_counter_non_string():
    tc = TokenCounter()
    messages = [
        {"role": "user", "content": None},
        {"role": "assistant", "content": ["structured", "content"]},
        {"role": "user", "content": 12345}
    ]
    tokens = tc.count(messages, response=None)
    assert isinstance(tokens, int)
    assert tokens >= 0

def test_context_manager_system_filtering():
    cm = ContextManager(summary_threshold=10)
    mock_llm = LocalMockLLM("Summary text")
    
    messages = [
        {"role": "user", "content": "Hello " * 50},
        {"role": "system", "content": "System prompt " * 50},
        {"role": "agent", "content": "Hi " * 50}
    ]
    trimmed = cm.trim(messages, mock_llm)
    system_msgs = [m for m in trimmed if m.get("role") == "system"]
    assert len(system_msgs) >= 1

def test_knowledge_store_lock_initialized():
    ks = KnowledgeStore()
    assert hasattr(ks, "lock")
    assert ks.lock is not None

def test_file_tools_commonpath_traversal():
    with pytest.raises(ValueError, match="outside workspace"):
        _get_safe_path("../../../Windows/System32/config")

def test_session_manager_commonpath_traversal():
    sm = SessionManager()
    result = sm.load_session("../../etc/passwd")
    assert result == []

def test_ollama_provider_returns_empty_list_on_failure(monkeypatch):
    import urllib.request
    def mock_urlopen(*args, **kwargs):
        raise urllib.error.URLError("Connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    models = OllamaProvider.list_models()
    assert models == []

def test_python_repl_blocks_getattribute_escape():
    from tools.external_tools import _check_code_safety
    result = _check_code_safety("().__getattribute__('__class__')")
    assert result is not None and "not allowed" in result

def test_python_repl_blocks_all_dunder_attrs():
    from tools.external_tools import _check_code_safety
    result = _check_code_safety("x.__mro_entries__")
    assert result is not None and "not allowed" in result

def test_python_repl_blocks_dunder_string_literals():
    from tools.external_tools import _check_code_safety
    result = _check_code_safety("x = '__class__'")
    assert result is not None and "not allowed" in result

def test_python_repl_allows_normal_code():
    from tools.external_tools import _check_code_safety
    assert _check_code_safety("x = 5\nprint(x + 1)") is None
    assert _check_code_safety("data = [1, 2, 3]\nprint(sum(data))") is None

def test_general_agent_has_restricted_tools():
    from agents.agent_registry import AGENT_REGISTRY
    general = AGENT_REGISTRY["general"]
    assert general["tools"] is not None
    assert "run_command" not in general["tools"]
    assert "python_repl" not in general["tools"]
    assert "write_file" not in general["tools"]

def test_run_command_windows_builtin(monkeypatch, temp_workspace):
    import subprocess
    import sys

    from tools.external_tools import run_command
    monkeypatch.setattr(sys, "platform", "win32")
    calls = []
    class MockResult:
        stdout = "mocked output"
        stderr = ""
    def mock_run(*args, **kwargs):
        calls.append(kwargs)
        return MockResult()
    monkeypatch.setattr(subprocess, "run", mock_run)
    result = run_command(json.dumps({"command": "dir"}))
    assert "mocked output" in result
    assert calls[0]["shell"] is False

def test_gemini_provider_raises_on_unexpected_response():
    from llm_client import LLMError
    from providers.gemini_provider import GeminiProvider
    provider = GeminiProvider(model="gemini-2.0-flash", api_key="fake")
    import urllib.request
    class MockResponse:
        def read(self): return b'{"candidates": []}'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def mock_urlopen(*a, **kw): return MockResponse()
    import unittest.mock
    with unittest.mock.patch.object(urllib.request, 'urlopen', mock_urlopen):
        with pytest.raises(LLMError, match="unexpected response"):
            provider.generate([{"role": "user", "content": "test"}])

def test_read_file_pagination(temp_workspace):
    from tools.file_tools import WORKSPACE_DIR, read_file
    path = os.path.join(WORKSPACE_DIR, "paginated.txt")
    with open(path, "w") as f:
        f.writelines(f"Line {i}\n" for i in range(1, 21))
    result = read_file(json.dumps({"path": "paginated.txt", "start_line": 5, "end_line": 10}))
    assert "Line 5" in result
    assert "Line 10" in result
    assert "Line 11" not in result

def test_orchestrator_multiline_delegation_parsing():
    from agents.orchestrator import OrchestratorAgent
    class MultiLineMockLLM(LocalMockLLM):
        def generate(self, messages, json_mode=False):
            return "DELEGATE: researcher: Find information\nabout Tokyo\nand return facts\nDELEGATE: coder: Write a script"
    orch = OrchestratorAgent(llm_client=MultiLineMockLLM())
    delegations = orch.delegate("Test goal")
    assert len(delegations) == 2
    assert delegations[0][0] == "researcher"
    assert delegations[0][1] == "Find information about Tokyo and return facts"
    assert delegations[1][0] == "coder"
    assert delegations[1][1] == "Write a script"

def test_recall_empty_json_returns_all():
    from tools.basic_tools import recall, remember
    remember(json.dumps({"key": "test_city", "value": "Tokyo"}))
    result = recall("{}")
    assert "test_city" in result
    assert "Tokyo" in result

def test_python_repl_blocks_type_builtin():
    """type() should be blocked to prevent metaclass escape."""
    from tools.external_tools import _check_code_safety
    result = _check_code_safety("type('X', (object,), {})")
    assert result is not None and "not allowed" in result

def test_python_repl_blocks_chr_builtin():
    """chr() should be blocked to prevent name reconstruction."""
    from tools.external_tools import _check_code_safety
    result = _check_code_safety("chr(101) + chr(118)")
    assert result is not None and "not allowed" in result

def test_python_repl_type_not_in_builtins():
    """type should not be accessible at runtime in the REPL."""
    from tools.external_tools import SAFE_BUILTINS
    assert 'type' not in SAFE_BUILTINS

def test_python_repl_chr_not_in_builtins():
    """chr should not be accessible at runtime in the REPL."""
    from tools.external_tools import SAFE_BUILTINS
    assert 'chr' not in SAFE_BUILTINS

def test_ollama_provider_maps_agent_role():
    """Ollama should map 'agent' role to 'assistant'."""
    import urllib.request

    from providers.ollama_provider import OllamaProvider
    provider = OllamaProvider(model="test-model")
    
    captured = {}
    class MockResponse:
        def read(self): return b'{"message": {"content": "ok"}}'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    
    def mock_urlopen(req, **kw):
        captured['payload'] = json.loads(req.data.decode('utf-8'))
        return MockResponse()
    
    import unittest.mock
    with unittest.mock.patch.object(urllib.request, 'urlopen', mock_urlopen):
        provider.generate([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "agent", "content": "Hi there"},
        ])
    
    roles = [m["role"] for m in captured['payload']['messages']]
    assert "agent" not in roles
    assert "assistant" in roles


def test_ollama_provider_uses_native_response_schema_when_supplied():
    import urllib.request
    import unittest.mock

    from providers.ollama_provider import OllamaProvider
    captured = {}

    class MockResponse:
        def read(self): return b'{"message": {"content": "{}"}}'
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def mock_urlopen(req, **kw):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return MockResponse()

    schema = {"type": "object", "additionalProperties": False}
    with unittest.mock.patch.object(urllib.request, "urlopen", mock_urlopen):
        OllamaProvider(model="test-model").generate(
            [{"role": "user", "content": "Return JSON"}],
            json_mode=True,
            response_schema=schema,
        )

    assert captured["payload"]["format"] == schema

def test_openai_provider_maps_agent_role():
    """OpenAI should map 'agent' role to 'assistant'."""
    import urllib.request

    from providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider(model="gpt-4o", api_key="fake-key")
    
    captured = {}
    class MockResponse:
        def read(self): return b'{"choices": [{"message": {"content": "ok"}}]}'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    
    def mock_urlopen(req, **kw):
        captured['payload'] = json.loads(req.data.decode('utf-8'))
        return MockResponse()
    
    import unittest.mock
    with unittest.mock.patch.object(urllib.request, 'urlopen', mock_urlopen):
        provider.generate([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "agent", "content": "Hi there"},
        ])
    
    roles = [m["role"] for m in captured['payload']['messages']]
    assert "agent" not in roles
    assert "assistant" in roles

def test_observation_uses_tool_role(mock_llm):
    """Observation messages appended to memory should use role 'tool'."""
    def dummy_tool(args): return "tool_output"
    registry = {"dummy": dummy_tool}
    def desc(): return '{"tool": "dummy", "args": "{}"}'
    
    mock_llm.responses = [
        '{"thought": "using tool", "action": {"tool": "dummy", "args": "{}"}, "final_answer": null}',
        '{"thought": "done", "action": null, "final_answer": "Finished"}'
    ]
    agent = BasicAgent(llm_client=mock_llm, tool_registry=registry, tool_descriptions_fn=desc, guardrails_enabled=False, verbose=False)
    agent.run_turn("Test input")
    
    tool_msgs = [m for m in agent.memory if m.get("role") == "tool"]
    assert len(tool_msgs) >= 1
    assert "Observation: tool_output" in tool_msgs[0]["content"]

def test_providers_map_tool_to_user():
    """All providers should map internal 'tool' role to 'user' for LLM API compatibility."""
    import unittest.mock
    import urllib.request

    from providers.gemini_provider import GeminiProvider
    from providers.ollama_provider import OllamaProvider
    from providers.openai_provider import OpenAIProvider

    # Test Ollama
    ollama_provider = OllamaProvider(model="test-model")
    captured_ollama = {}
    class MockOllamaResponse:
        def read(self): return b'{"message": {"content": "ok"}}'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def mock_ollama_urlopen(req, **kw):
        captured_ollama['payload'] = json.loads(req.data.decode('utf-8'))
        return MockOllamaResponse()
    with unittest.mock.patch.object(urllib.request, 'urlopen', mock_ollama_urlopen):
        ollama_provider.generate([{"role": "tool", "content": "Observation: output"}])
    assert captured_ollama['payload']['messages'][0]['role'] == "user"

    # Test OpenAI
    openai_provider = OpenAIProvider(model="gpt-4o", api_key="fake")
    captured_openai = {}
    class MockOpenAIResponse:
        def read(self): return b'{"choices": [{"message": {"content": "ok"}}]}'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def mock_openai_urlopen(req, **kw):
        captured_openai['payload'] = json.loads(req.data.decode('utf-8'))
        return MockOpenAIResponse()
    with unittest.mock.patch.object(urllib.request, 'urlopen', mock_openai_urlopen):
        openai_provider.generate([{"role": "tool", "content": "Observation: output"}])
    assert captured_openai['payload']['messages'][0]['role'] == "user"

    # Test Gemini
    gemini_provider = GeminiProvider(model="gemini-1.5-flash", api_key="fake")
    captured_gemini = {}
    class MockGeminiResponse:
        def read(self): return b'{"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def mock_gemini_urlopen(req, **kw):
        captured_gemini['payload'] = json.loads(req.data.decode('utf-8'))
        return MockGeminiResponse()
    with unittest.mock.patch.object(urllib.request, 'urlopen', mock_gemini_urlopen):
        gemini_provider.generate([{"role": "tool", "content": "Observation: output"}])
    assert captured_gemini['payload']['contents'][0]['role'] == "user"

def test_memory_pruning(mock_llm):
    """BasicAgent memory should be pruned when it exceeds max_memory_messages."""
    mock_llm.responses = ['{"thought": "done", "action": null, "final_answer": "ok"}'] * 10
    agent = BasicAgent(llm_client=mock_llm, verbose=False, max_memory_messages=10)
    
    # Fill memory with 20 messages
    for i in range(15):
        agent.memory.append({"role": "user", "content": f"msg {i}"})
    
    assert len(agent.memory) > 10
    agent.run_turn("Trigger turn")
    assert len(agent.memory) <= 10


def test_should_reflect_guards_tal_and_code(mock_llm):
    """Reflection should not corrupt code blocks or trigger inappropriately in TAL mode."""
    agent = BasicAgent(llm_client=mock_llm, verbose=False, tal_mode=True, reflection_enabled=True)
    
    # In TAL mode, should not reflect if no network tools were used
    assert agent._should_reflect(["write_file", "python_repl"]) is False
    assert agent._should_reflect([]) is False
    assert agent._should_reflect(["web_search"]) is True

    # _reflect must preserve raw python code blocks unchanged without calling LLM
    code_text = "```python\nimport hashlib\nprint('hello')\n```"
    assert agent._reflect("write code", code_text) == code_text


def test_orchestrator_does_not_execute_embedded_code_fences(mock_llm, temp_workspace):
    """Model text is not an executable channel, even when it contains code."""
    from agents.orchestrator import OrchestratorAgent
    
    script_content = "with open('auto_created.txt', 'w') as f:\n    f.write('auto_created_ok')\n"
    code_fence_response = f"```python\n{script_content}\n```"

    class MultiMockLLM(LLMClient):
        def __init__(self):
            super().__init__(model="mock")
            self.calls = 0
        def generate(self, messages, json_mode=False):
            self.calls += 1
            if self.calls == 1:
                return "DELEGATE: coder: write and execute the script"
            elif self.calls == 2:
                # Specialist returns raw markdown code fence
                return code_fence_response
            else:
                return "Synthesized result"
        @staticmethod
        def list_models():
            return ["mock"]

    orchestrator = OrchestratorAgent(llm_client=MultiMockLLM(), verbose=False, tal_mode=True)
    goal = "Create a script and verify auto_created.txt is written"
    orchestrator.run(goal)

    # Verify auto_created.txt was created in workspace
    created_path = os.path.join(temp_workspace, "auto_created.txt")
    if not os.path.exists(created_path):
        # Check standard workspace directory
        workspace_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace"))
        created_path = os.path.join(workspace_dir, "auto_created.txt")
    
    assert not os.path.exists(created_path)

