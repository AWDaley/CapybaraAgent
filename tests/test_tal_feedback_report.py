import json
import os

from agent import BasicAgent
from agents.orchestrator import OrchestratorAgent
from llm_client import LLMClient
from tal.feedback_report import (
    TALFeedbackReport,
    compute_health_score,
    format_feedback_card,
    save_feedback_report,
)
from tal.pipeline_runner import PipelineExecutionResult


class MockLLM(LLMClient):
    def __init__(self, responses=None):
        super().__init__(model="mock-4b")
        self.provider = "ollama"
        self.responses = responses or []
        self.calls = 0

    def generate(self, messages, json_mode=False):
        self.calls += 1
        if self.responses and self.calls <= len(self.responses):
            return self.responses[self.calls - 1]
        return '{"thought": "done", "action": null, "final_answer": "Task completed successfully"}'

    @staticmethod
    def list_models():
        return ["mock-4b"]


def test_feedback_report_dataclass_and_serialization():
    report = TALFeedbackReport(
        prompt="Calculate 2 + 2",
        mode="react",
        model="mock-4b",
        provider="ollama",
        final_answer="The answer is 4",
        success=True,
        duration_seconds=1.25,
        steps_taken=2,
        max_steps=10,
        tool_call_count=1,
        epistemic_fact_count=3,
        verification_passed=True
    )

    d = report.to_dict()
    assert d["prompt"] == "Calculate 2 + 2"
    assert d["verification_passed"] is True

    reloaded = TALFeedbackReport.from_dict(d)
    assert reloaded.prompt == report.prompt
    assert reloaded.duration_seconds == 1.25


def test_compute_health_score():
    # Optimal run
    good_report = TALFeedbackReport(
        success=True,
        error=None,
        verification_passed=True,
        tool_error_count=0,
        steps_taken=3,
        max_steps=10,
        parse_repairs=0
    )
    score, rating, recs = compute_health_score(good_report)
    assert score == 100
    assert rating == "Optimal"
    assert "cleanly" in recs[0].lower()

    # Degraded run (tool error + verification failure)
    degraded_report = TALFeedbackReport(
        success=True,
        error=None,
        verification_passed=False,
        tool_error_count=1,
        steps_taken=9,
        max_steps=10,
        parse_repairs=3
    )
    score, rating, recs = compute_health_score(degraded_report)
    assert score < 70
    assert len(recs) >= 3


def test_format_feedback_card():
    report = TALFeedbackReport(
        prompt="Compute hash",
        mode="react",
        model="mock-4b",
        provider="ollama",
        final_answer="Hash: abc",
        success=True,
        duration_seconds=3.5,
        steps_taken=2,
        max_steps=15,
        total_tokens=450,
        input_tokens=300,
        output_tokens=150,
        llm_calls=2,
        tool_calls=[{"tool": "python_repl", "args": "code", "result": "abc"}],
        tool_call_count=1,
        tool_error_count=0,
        epistemic_fact_count=2,
        verification_passed=True,
        health_score=100,
        health_rating="Optimal"
    )

    card = format_feedback_card(report)
    assert "TAL PERFORMANCE FEEDBACK REPORT" in card
    assert "Optimal" in card
    assert "python_repl" in card
    assert "3.5s" in card


def test_save_feedback_report():
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        report = TALFeedbackReport(
            prompt="Test report generation",
            mode="react",
            model="mock-4b",
            final_answer="Output",
            health_score=95,
            health_rating="Optimal"
        )

        json_path, md_path = save_feedback_report(report, storage_dir=temp_dir)
        assert os.path.exists(json_path)
        assert os.path.exists(md_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["prompt"] == "Test report generation"

        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "# TAL Performance Feedback Report" in content
            assert "Optimal" in content


def test_basic_agent_generate_feedback_report():
    mock_llm = MockLLM([
        '{"thought": "Calculating", "action": {"tool": "calc", "args": {"expression": "10 * 10"}}, "final_answer": null}',
        '{"thought": "Done", "action": null, "final_answer": "100"}'
    ])
    agent = BasicAgent(llm_client=mock_llm, verbose=False, tal_mode=True)
    ans = agent.run_turn("Calculate 10 * 10")
    
    report = agent.generate_feedback_report("Calculate 10 * 10", ans, duration_seconds=0.5)
    assert isinstance(report, TALFeedbackReport)
    assert report.prompt == "Calculate 10 * 10"
    assert report.final_answer == "100"
    assert report.tool_call_count >= 1
    assert report.health_score >= 90


def test_orchestrator_generate_feedback_report():
    mock_llm = MockLLM([
        "DELEGATE: general: Do the task",
        '{"thought": "Handling task", "action": null, "final_answer": "General output"}',
        "Synthesized final response"
    ])
    orchestrator = OrchestratorAgent(llm_client=mock_llm, verbose=False, tal_mode=True)
    ans = orchestrator.run("Multi-agent test task")

    report = orchestrator.generate_feedback_report("Multi-agent test task", ans, duration_seconds=1.2)
    assert isinstance(report, TALFeedbackReport)
    assert report.mode == "multi-agent"
    assert report.final_answer == "Synthesized final response"
    assert report.health_score >= 90


def test_orchestrator_pipeline_report_uses_pipeline_budget_and_metrics():
    orchestrator = OrchestratorAgent(llm_client=MockLLM(), verbose=False, tal_mode=True)
    orchestrator.last_pipeline_result = PipelineExecutionResult(
        pipeline_id="metrics",
        title="Metrics",
        success=False,
        steps_total=8,
        steps_passed=1,
        error="Pipeline time budget exhausted before the next step.",
        elapsed_seconds=12.5,
        max_steps=70,
        steps_consumed=9,
        llm_calls=4,
        tool_call_count=3,
        tool_error_count=1,
        input_tokens=120,
        output_tokens=80,
        tool_calls=[{"tool": "[CODER] python_repl", "args": {"code": "x = 1"}, "result": "ok"}],
    )

    report = orchestrator.generate_feedback_report("Metrics", "partial", duration_seconds=999)

    assert report.duration_seconds == 12.5
    assert report.max_steps == 70
    assert report.steps_taken == 9
    assert report.llm_calls == 4
    assert report.total_tokens == 200


def test_orchestrator_pipeline_report_uses_one_canonical_tool_trace():
    orchestrator = OrchestratorAgent(llm_client=MockLLM(), verbose=False, tal_mode=True)
    orchestrator.event_log.append("specialist_tool_executed", {
        "specialist": "coder",
        "tool": "python_repl",
        "args": {"code": "duplicate = True"},
        "result": "duplicate event-log copy",
    })
    orchestrator.last_pipeline_result = PipelineExecutionResult(
        pipeline_id="canonical-tools",
        title="Canonical Tools",
        success=True,
        steps_total=1,
        steps_passed=1,
        tool_call_count=1,
        tool_error_count=0,
        tool_calls=[{
            "tool": "[CODER] python_repl",
            "args": {"code": "x = 1"},
            "result": "ok",
        }],
    )

    report = orchestrator.generate_feedback_report("Canonical Tools", "done")

    assert report.tool_call_count == 1
    assert len(report.tool_calls) == 1
    assert report.tool_calls[0]["tool"] == "[CODER] python_repl"
