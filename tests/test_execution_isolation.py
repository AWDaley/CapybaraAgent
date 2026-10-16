import json

from agent import BasicAgent
from execution.isolated import ExecutionPolicy, IsolatedToolExecutor, govern_agent_tools
from tal.effect_classes import EffectClass


def test_tal_default_fails_closed_without_container_runtime(monkeypatch):
    monkeypatch.delenv("CAPYBARA_UNSAFE_LOCAL_EXEC", raising=False)
    monkeypatch.delenv("CAPYBARA_CONTAINER_RUNTIME", raising=False)
    monkeypatch.delenv("CAPYBARA_SANDBOX_IMAGE", raising=False)
    called = []
    agent = BasicAgent(tal_mode=True, tool_registry={
        "python_repl": lambda args: called.append(args),
        "run_command": lambda args: called.append(args),
        "calc": lambda args: "2",
    })
    assert "python_repl" not in agent.tools
    assert "run_command" not in agent.tools
    assert "calc" in agent.tools
    assert called == []


def test_container_config_must_be_digest_pinned(monkeypatch):
    monkeypatch.delenv("CAPYBARA_UNSAFE_LOCAL_EXEC", raising=False)
    runner = IsolatedToolExecutor(ExecutionPolicy(runtime="docker", image="python:latest"))
    assert not runner.policy.ready()
    assert "policy_denied" in runner.run_command(json.dumps({"command": "python script.py"}))


def test_dev_override_is_explicit(monkeypatch):
    monkeypatch.setenv("CAPYBARA_UNSAFE_LOCAL_EXEC", "1")
    unsafe = lambda args: args
    assert govern_agent_tools({"python_repl": unsafe})["python_repl"] is unsafe
