"""Protocol tests use ONLY literal trusted fixture code on host.

The model-directed stateful runner itself never has a host Python fallback.
The opt-in container tests exercise the real Docker/Podman confinement and
are not substitutes for privileged-runtime penetration testing.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent import BasicAgent
from execution.isolated import ExecutionPolicy, govern_agent_tools
from execution.stateful import StatefulSandbox
from tal.pipeline_benchmark import (
    _snapshot_names, load_pipeline_fixture, pipeline_blocker,
)
from tal_test_runner import TALTestRunner


def _protocol_command():
    worker = Path(__file__).resolve().parents[1] / "execution" / "sandbox_worker.py"
    return [sys.executable, "-I", "-u", str(worker)]


def _send(proc, request):
    proc.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def test_literal_protocol_fixture_preserves_state_and_bounds_values():
    # Literal test strings, NEVER LLM-generated input. This is a protocol
    # unit test, not a sandbox conformance test.
    proc = subprocess.Popen(
        _protocol_command(), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        ready = json.loads(proc.stdout.readline())
        assert ready == {"id": 0, "ok": True, "output": "ready"}
        result = _send(proc, {
            "id": 1, "op": "exec",
            "code": "import hashlib\nimport json\na = [2, 4, 6, 8]\nbenchmark_summary = {'total': sum(a), 'average': sum(a) / len(a)}\nprint('ok')",
        })
        assert result["id"] == 1
        assert result["ok"] is True
        assert result["output"] == "ok"
        state = _send(proc, {"id": 2, "op": "snapshot", "names": ["benchmark_summary"]})
        assert state == {
            "id": 2, "ok": True,
            "state": {"benchmark_summary": {"total": 20, "average": 5.0}},
        }
        bad = _send(proc, {
            "id": 3, "op": "exec",
            "code": "bad_code = (",
        })
        assert bad["ok"] is False
        assert bad["error"] == "WORKER_EXECUTION_ERROR"
        again = _send(proc, {"id": 4, "op": "snapshot", "names": ["benchmark_summary"]})
        assert again["state"] == state["state"]
        assert _send(proc, {"id": 5, "op": "snapshot", "names": ["__builtins__"]})["ok"] is False
    finally:
        proc.kill()
        proc.communicate(timeout=5)


def test_governance_rejects_host_repl_and_mutable_container_image(monkeypatch, tmp_path):
    monkeypatch.delenv("CAPYBARA_UNSAFE_LOCAL_EXEC", raising=False)
    observed = []
    tool = lambda args: observed.append(args)
    assert "python_repl" not in govern_agent_tools({"python_repl": tool})
    agent = BasicAgent(
        tal_mode=True, tool_registry={"python_repl": tool},
    )
    assert "python_repl" not in agent.tools
    assert observed == []

    policy = ExecutionPolicy(runtime="docker", image="python:latest")
    sandbox = StatefulSandbox(str(tmp_path), policy)
    assert sandbox.ready is False
    assert "ISOLATION_UNAVAILABLE" in str(pytest.raises(Exception, sandbox._command).value)
    assert observed == []


def test_pipeline_exports_snapshot_names_and_never_uses_host_repl_by_default(monkeypatch):
    monkeypatch.delenv("CAPYBARA_CONTAINER_RUNTIME", raising=False)
    monkeypatch.delenv("CAPYBARA_SANDBOX_IMAGE", raising=False)
    fixture = load_pipeline_fixture("data/benchmark_isolated_stateful_pipeline.json")
    names = _snapshot_names(fixture, ("benchmark_summary",))
    assert names == ("benchmark_summary",)
    reason = pipeline_blocker(fixture, isolated_repl_available=False)
    assert "python_repl" in reason
    assert pipeline_blocker(fixture, isolated_repl_available=True) is None


@pytest.mark.skipif(
    os.environ.get("CAPYBARA_RUN_CONTAINER_TESTS") != "1",
    reason="Real sandbox integration must be explicitly enabled on a container-capable runner",
)
def test_real_container_worker_persists_state_and_cannot_escape_workspace(tmp_path):
    policy = ExecutionPolicy.from_environment()
    assert policy.ready(), "Integration must use an actual digest-pinned image and container CLI"
    with StatefulSandbox(str(tmp_path), policy, response_timeout_seconds=8) as sandbox:
        assert sandbox.execute_tool(json.dumps({"code": (
            "import hashlib\nimport json\n"
            "numbers = [n*n for n in range(1, 11)]\nprint(len(numbers))"
        )})) == "10"
        assert sandbox.snapshot(["numbers"])["numbers"] == [1, 4, 9, 16, 25, 36, 49, 64, 81, 100]
        assert not sandbox.execute_tool('{"code":"result = sum(numbers)"}').startswith("Error")
        assert sandbox.snapshot(["numbers"])["numbers"][-1] == 100
        # The bind mount points only to the temporary workspace; no host
        # home directory is present in this container.
        assert not sandbox.execute_tool(json.dumps({
            "code": "from pathlib import Path\nPath('proof.txt').write_text('inside container only')",
        })).startswith("Error")
        assert (tmp_path / "proof.txt").read_text() == "inside container only"
    assert sandbox.ready is False


@pytest.mark.skipif(
    os.environ.get("CAPYBARA_RUN_CONTAINER_TESTS") != "1",
    reason="Real container kill-on-timeout requires explicitly configured Docker/Podman",
)
def test_container_timeout_terminates_entire_worker_without_reuse(tmp_path):
    policy = ExecutionPolicy.from_environment()
    assert policy.ready()
    sandbox = StatefulSandbox(str(tmp_path), policy, response_timeout_seconds=1)
    name = sandbox.container_name
    try:
        with sandbox:
            reply = sandbox.execute_tool('{"code":"while True: pass"}')
            assert reply.startswith("Error:")
            assert sandbox.ready is False
            assert "WORKER_TIMEOUT" in reply
    finally:
        sandbox.close()
    inspect = subprocess.run(
        [policy.runtime, "container", "inspect", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=8, check=False,
    )
    assert inspect.returncode != 0, "Timed-out model container was not removed"


@pytest.mark.skipif(
    os.environ.get("CAPYBARA_RUN_CONTAINER_TESTS") != "1",
    reason="Real paired worker benchmark is opt-in to a pinned OS container",
)
def test_isolated_stateful_pipeline_same_fixture_runs_both_arms(tmp_path):
    from llm_client import LLMClient

    class _FixedTrustedProposal(LLMClient):
        def __init__(self):
            super().__init__(model="qwen3.5:4b")
            self.calls = 0

        def generate(self, messages, json_mode=False, timeout_seconds=None):
            self.calls += 1
            return json.dumps({
                "thought": "Set deterministic synthetic benchmark state",
                "action": {"tool": "python_repl", "args": {
                    "code": "values = [2, 4, 6, 8]\nbenchmark_summary = {'total': sum(values), 'average': sum(values) / len(values)}",
                }},
                "final_answer": None,
            })

        def generate_with_retry(self, messages, json_mode=False, max_retries=3,
                                callback=None, deadline=None):
            response = self.generate(messages, json_mode=json_mode)
            if callback:
                callback(response)
            return response

        @classmethod
        def list_models(cls):
            return []

    client = _FixedTrustedProposal()
    test_runner = TALTestRunner(client, storage_dir=str(tmp_path))
    result = test_runner.run_pipeline_test(
        "Create synthetic summary",
        pipeline_fixture="data/benchmark_isolated_stateful_pipeline.json",
        evidence_keys=("benchmark_summary",),
        artifact_paths=("benchmark_summary.json",),
        seed=11,
    )
    for trial in (result.baseline, result.tal):
        assert trial.execution_supported is True
        assert trial.success is True, trial.error
        assert trial.llm_calls == 1
        assert trial.observed_state["benchmark_summary"] == {"total": 20, "average": 5.0}
        assert json.loads(trial.observed_artifacts["benchmark_summary.json"]["content"]) == {
            "total": 20, "average": 5.0,
        }
    assert client.calls == 2
