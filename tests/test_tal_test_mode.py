import json
import os
import shutil
import tempfile

import pytest

from llm_client import LLMClient
from tal_test_report import (
    RunMetrics,
    TALTestResult,
    format_batch_summary,
    format_comparison_table,
    save_batch_result,
    save_test_result,
)
from tal_test_runner import (
    TALTestRunner,
    TrackingLLMClient,
    sandbox_workspace,
)


@pytest.fixture
def test_dir():
    temp_dir = tempfile.mkdtemp(prefix="tal_test_fixture_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class MockMultiTurnLLM(LLMClient):
    """Mock LLM that returns a sequence of canned responses."""
    def __init__(self, responses: list[str]):
        super().__init__(model="mock-tal-model")
        self.responses = list(responses)
        self.call_count = 0
        self.calls_recorded = []

    def generate(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        self.calls_recorded.append(messages)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return '{"thought": "Completed", "action": null, "final_answer": "Done."}'

    @classmethod
    def list_models(cls) -> list[str]:
        return ["mock-tal-model"]


def test_tracking_llm_client():
    mock_base = MockMultiTurnLLM([
        '{"thought": "Calculating", "action": {"tool": "calc", "args": "{\"expression\": \"2+2\"}"}, "final_answer": null}',
        '{"thought": "Final answer", "action": null, "final_answer": "4"}'
    ])
    tracker = TrackingLLMClient(mock_base)

    assert tracker.llm_calls == 0
    assert tracker.total_tokens == 0

    resp1 = tracker.generate([{"role": "user", "content": "What is 2+2?"}])
    assert "calc" in resp1
    assert tracker.llm_calls == 1
    assert tracker.input_tokens > 0
    assert tracker.output_tokens > 0
    assert tracker.total_tokens == tracker.input_tokens + tracker.output_tokens

    resp2 = tracker.generate([{"role": "user", "content": "What is 2+2?"}, {"role": "agent", "content": resp1}])
    assert tracker.llm_calls == 2
    assert len(tracker.history) == 2


def test_tal_test_result_diffs():
    b = RunMetrics(
        mode="react",
        tal_enabled=False,
        final_answer="Baseline ans",
        steps_taken=4,
        wall_clock_time=2.0,
        llm_calls=4,
        total_tokens=500,
        tool_call_count=3,
        tool_error_count=1,
    )
    t = RunMetrics(
        mode="react",
        tal_enabled=True,
        final_answer="TAL ans",
        steps_taken=2,
        wall_clock_time=1.5,
        llm_calls=2,
        total_tokens=650,
        tool_call_count=2,
        tool_error_count=0,
        gate_blocks=1,
        epistemic_fact_count=4,
        verification_passed=True,
    )

    result = TALTestResult(
        prompt="Test prompt",
        mode="react",
        model="mock-model",
        provider="mock",
        baseline=b,
        tal=t,
    )

    diffs = result.get_diffs()
    assert diffs["steps_diff"] == -2
    assert diffs["steps_diff_pct"] == -50.0
    assert diffs["tokens_diff"] == 150
    assert diffs["tool_errors_diff"] == -1
    assert diffs["gate_interventions"] == 1
    assert diffs["epistemic_facts_gained"] == 4
    assert diffs["verification_passed"] is True

    # Test serialization roundtrip
    d = result.to_dict()
    assert d["prompt"] == "Test prompt"
    assert "diffs" in d
    assert d["baseline"]["steps_taken"] == 4
    assert d["tal"]["steps_taken"] == 2

    restored = TALTestResult.from_dict(d)
    assert restored.prompt == result.prompt
    assert restored.baseline.steps_taken == 4
    assert restored.tal.steps_taken == 2


def test_format_comparison_table():
    b = RunMetrics(mode="react", tal_enabled=False, final_answer="Answer A", steps_taken=3, wall_clock_time=1.2, total_tokens=300)
    t = RunMetrics(mode="react", tal_enabled=True, final_answer="Answer B", steps_taken=2, wall_clock_time=1.4, total_tokens=450, gate_blocks=1, epistemic_fact_count=3, verification_passed=True)

    res = TALTestResult(
        prompt="Calculate 10+20",
        mode="react",
        model="llama3",
        provider="ollama",
        baseline=b,
        tal=t
    )

    table_str = format_comparison_table(res)
    assert "TAL TEST MODE" in table_str
    assert "Calculate 10+20" in table_str
    assert "Baseline (No TAL)" in table_str
    assert "TAL Mode" in table_str
    assert "Answer A" in table_str
    assert "Answer B" in table_str


def test_format_batch_summary():
    r1 = TALTestResult(
        prompt="P1",
        baseline=RunMetrics(steps_taken=3, total_tokens=200, tool_error_count=1, wall_clock_time=1.0),
        tal=RunMetrics(steps_taken=2, total_tokens=300, tool_error_count=0, wall_clock_time=1.2, gate_blocks=1, epistemic_fact_count=2)
    )
    r2 = TALTestResult(
        prompt="P2",
        baseline=RunMetrics(steps_taken=4, total_tokens=300, tool_error_count=2, wall_clock_time=2.0),
        tal=RunMetrics(steps_taken=4, total_tokens=350, tool_error_count=0, wall_clock_time=1.8, gate_blocks=0, epistemic_fact_count=3)
    )

    summary = format_batch_summary([r1, r2])
    assert "BATCH SUMMARY" in summary
    assert "2 PROMPTS" in summary
    assert "Step Efficiency" in summary
    assert "Error Reduction" in summary


def test_save_and_load_results(test_dir):
    storage_dir = os.path.join(test_dir, "tal_tests")
    res = TALTestResult(
        prompt="Save test prompt",
        mode="react",
        baseline=RunMetrics(final_answer="base"),
        tal=RunMetrics(final_answer="tal")
    )

    filepath = save_test_result(res, storage_dir=storage_dir)
    assert os.path.exists(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["prompt"] == "Save test prompt"

    batch_path = save_batch_result([res], storage_dir=storage_dir)
    assert os.path.exists(batch_path)
    with open(batch_path, "r", encoding="utf-8") as f:
        bdata = json.load(f)
    assert bdata["total_prompts"] == 1


def test_sandbox_workspace_isolation():
    import tools.file_tools
    original_workspace = tools.file_tools.WORKSPACE_DIR

    with sandbox_workspace() as ws1:
        assert tools.file_tools.WORKSPACE_DIR == os.path.realpath(ws1)
        # Write a file inside ws1
        res = tools.file_tools.write_file(json.dumps({"path": "temp_test.txt", "content": "Run 1 data"}))
        assert "File written" in res
        assert os.path.exists(os.path.join(ws1, "temp_test.txt"))

    # After exiting ws1, directory is cleaned up and original workspace restored
    assert not os.path.exists(ws1)
    assert tools.file_tools.WORKSPACE_DIR == original_workspace

    # Separate run in ws2 does not see ws1 files
    with sandbox_workspace() as ws2:
        assert not os.path.exists(os.path.join(ws2, "temp_test.txt"))


def test_tal_runner_react_mode(test_dir):
    # Direct answer without tools
    mock_llm = MockMultiTurnLLM([
        # Run 1 (Baseline)
        '{"thought": "I will answer directly", "action": null, "final_answer": "Baseline 42"}',
        # Run 2 (TAL)
        '{"thought": "Direct TAL response", "action": null, "final_answer": "TAL 42"}'
    ])

    runner = TALTestRunner(
        llm_client=mock_llm,
        mode="react",
        max_steps=3,
        storage_dir=test_dir
    )

    result = runner.run_single_test("What is 6 * 7?")
    assert result.prompt == "What is 6 * 7?"
    assert result.mode == "react"
    assert result.baseline.final_answer == "Baseline 42"
    assert result.tal.final_answer == "TAL 42"
    assert result.baseline.success is True
    assert result.tal.success is True
    assert result.tal.tal_enabled is True
    assert result.baseline.tal_enabled is False


def test_tal_runner_with_tool_call(test_dir):
    mock_llm = MockMultiTurnLLM([
        # Baseline Turn 1: tool call
        json.dumps({"thought": "Calculate sum", "action": {"tool": "calc", "args": json.dumps({"expression": "10+20"})}, "final_answer": None}),
        # Baseline Turn 2: final answer
        json.dumps({"thought": "Result is 30", "action": None, "final_answer": "The sum is 30"}),
        # TAL Turn 1: tool call
        json.dumps({"thought": "Calculate sum in TAL", "action": {"tool": "calc", "args": json.dumps({"expression": "10+20"})}, "final_answer": None}),
        # TAL Turn 2: final answer
        json.dumps({"thought": "Result is 30 in TAL", "action": None, "final_answer": "The sum is 30"}),
    ])

    runner = TALTestRunner(
        llm_client=mock_llm,
        mode="react",
        max_steps=5,
        storage_dir=test_dir
    )

    result = runner.run_single_test("Add 10 and 20")
    assert result.baseline.tool_call_count == 1
    assert result.tal.tool_call_count == 1
    assert result.tal.epistemic_fact_count > 0  # TAL records facts for user input & tool obs


def test_tal_runner_planning_mode(test_dir):
    mock_llm = MockMultiTurnLLM([
        # Baseline: Plan generation
        "1. Write hello to file\n2. Done",
        # Baseline Step 1: execute step
        '{"thought": "Step 1 done", "action": null, "final_answer": "File written"}',
        # Baseline Step 2: execute step
        '{"thought": "Step 2 done", "action": null, "final_answer": "Finished"}',
        # TAL: Plan generation
        "1. Write hello to file\n2. Done",
        # TAL Step 1: execute step
        '{"thought": "Step 1 done TAL", "action": null, "final_answer": "File written"}',
        # TAL Step 2: execute step
        '{"thought": "Step 2 done TAL", "action": null, "final_answer": "Finished"}',
    ])

    runner = TALTestRunner(
        llm_client=mock_llm,
        mode="planning",
        max_steps=5,
        storage_dir=test_dir
    )

    result = runner.run_single_test("Plan to write file")
    assert result.mode == "planning"
    assert result.baseline.success is True
    assert result.tal.success is True


def test_tal_runner_multi_agent_mode(test_dir):
    mock_llm = MockMultiTurnLLM([
        # Baseline: Delegate
        "DELEGATE: general: Do the task",
        # Baseline: Specialist step
        '{"thought": "General specialist answering", "action": null, "final_answer": "Handled by specialist"}',
        # Baseline: Synthesize
        "Synthesis: Handled successfully.",
        # TAL: Delegate
        "DELEGATE: general: Do the task",
        # TAL: Specialist step
        '{"thought": "General specialist answering in TAL", "action": null, "final_answer": "Handled by TAL specialist"}',
        # TAL: Synthesize
        "TAL Synthesis: Handled successfully in TAL.",
    ])

    runner = TALTestRunner(
        llm_client=mock_llm,
        mode="multi-agent",
        storage_dir=test_dir
    )

    result = runner.run_single_test("Coordinate multi-agent goal")
    assert result.mode == "multi-agent"
    assert result.baseline.success is True
    assert result.tal.success is True


def test_tal_runner_batch_execution(test_dir):
    mock_llm = MockMultiTurnLLM([
        # Prompt 1 Baseline
        '{"thought": "P1 Base", "action": null, "final_answer": "Ans 1 Base"}',
        # Prompt 1 TAL
        '{"thought": "P1 TAL", "action": null, "final_answer": "Ans 1 TAL"}',
        # Prompt 2 Baseline
        '{"thought": "P2 Base", "action": null, "final_answer": "Ans 2 Base"}',
        # Prompt 2 TAL
        '{"thought": "P2 TAL", "action": null, "final_answer": "Ans 2 TAL"}',
    ])

    runner = TALTestRunner(
        llm_client=mock_llm,
        mode="react",
        storage_dir=test_dir
    )

    progress_events = []
    def on_prog(idx, tot, res):
        progress_events.append((idx, tot, res.prompt))

    prompts = ["Question 1", "Question 2"]
    results = runner.run_batch_test(prompts, on_progress=on_prog)

    assert len(results) == 2
    assert len(progress_events) == 2
    assert progress_events[0] == (1, 2, "Question 1")
    assert progress_events[1] == (2, 2, "Question 2")
