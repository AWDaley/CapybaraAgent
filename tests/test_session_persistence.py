from agents.orchestrator import OrchestratorAgent
from main import persist_agent_session
from tal.event_store import EventLog
from tal.schemas import PipelineStep, StructuredPipeline


class RecordingSessionManager:
    def __init__(self):
        self.calls = []

    def auto_save(self, memory, metadata=None, event_log=None):
        self.calls.append({
            "memory": memory,
            "metadata": metadata,
            "event_log": event_log,
        })


class PipelineLLM:
    model = "test-model"
    provider = "test"

    def __init__(self):
        self.responses = [
            '{"thought": "set state", "action": {"tool": "python_repl", "args": {"code": "session_value = 1"}}, "final_answer": null}',
            '{"thought": "done", "action": null, "final_answer": "pipeline complete"}',
        ]

    def generate_with_retry(self, messages, json_mode=False, callback=None, deadline=None):
        response = self.responses.pop(0)
        if callback:
            callback(response)
        return response


def test_orchestrator_pipeline_records_memory_and_single_tool_event():
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    orchestrator = OrchestratorAgent(llm_client=PipelineLLM(), verbose=False, tal_mode=True)
    pipeline = StructuredPipeline(
        pipeline_id="session_pipeline",
        title="Session Pipeline",
        global_context={},
        steps=[PipelineStep(
            step_id="step_state",
            objective="Set session state.",
            specialist="coder",
            tool_allowlist=["python_repl"],
            verification_criteria=[{
                "type": "repl_variable",
                "variable": "session_value",
                "assertion": "session_value == 1",
            }],
        )],
    )

    result = orchestrator.run_pipeline(
        pipeline,
        approval_callback=lambda _tool, _args: True,
    )

    assert "Deterministic verification passed" in result
    assert [message["role"] for message in orchestrator.memory[-2:]] == ["user", "agent"]
    tool_events = [
        event for event in orchestrator.event_log.events
        if event.event_type == "specialist_tool_executed"
    ]
    assert len(tool_events) == 1


def test_persist_agent_session_uses_active_orchestrator_state():
    manager = RecordingSessionManager()
    fallback = type("Fallback", (), {"memory": [{"role": "user", "content": "fallback"}], "event_log": EventLog()})()
    orchestrator = type("Orchestrator", (), {
        "memory": [{"role": "user", "content": "pipeline"}, {"role": "agent", "content": "result"}],
        "event_log": EventLog(),
    })()

    persist_agent_session(manager, orchestrator, fallback, PipelineLLM(), "test", True)

    assert len(manager.calls) == 1
    assert manager.calls[0]["memory"] is orchestrator.memory
    assert manager.calls[0]["event_log"] is orchestrator.event_log
    assert manager.calls[0]["metadata"]["provider"] == "test"


def test_orchestrator_follow_up_does_not_reuse_previous_pipeline_metrics():
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    orchestrator = OrchestratorAgent(llm_client=PipelineLLM(), verbose=False, tal_mode=True)
    pipeline = StructuredPipeline(
        pipeline_id="report_scope",
        title="Report Scope",
        steps=[PipelineStep(
            step_id="state",
            objective="Set session state.",
            specialist="coder",
            tool_allowlist=["python_repl"],
            verification_criteria=[{
                "type": "repl_variable",
                "variable": "session_value",
                "assertion": "session_value == 1",
            }],
        )],
    )
    orchestrator.run_pipeline(pipeline, approval_callback=lambda _tool, _args: True)

    answer = orchestrator.run("y")
    report = orchestrator.generate_feedback_report("y", answer)

    assert answer.startswith("What would you like me to do?")
    assert orchestrator.last_execution is not None
    assert orchestrator.last_execution.execution_type == "delegation"
    assert orchestrator.last_execution.pipeline_result is None
    assert report.prompt == "y"
    assert report.tool_call_count == 0
    assert report.error is None
