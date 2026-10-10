import json
import tempfile

import pytest

from llm_client import LLMClient
from tal.pipeline_runner import StructuredPipelineRunner
from tal.event_store import EventLog
from tal.task_graph import TaskGraph, TaskGraphRunner, TaskGraphValidationError
from tools.external_tools import reset_repl_globals


class _GraphLLM(LLMClient):
    def __init__(self, responses):
        super().__init__("qwen3.5:4b")
        self.responses = list(responses)

    def generate(self, messages, json_mode=False, timeout_seconds=None):
        return self.responses.pop(0)

    @classmethod
    def list_models(cls):
        return []


def test_task_graph_validates_dependencies_and_compiles_typed_handoffs():
    graph = TaskGraph.from_dict({
        "graph_id": "graph_1",
        "title": "Graph test",
        "nodes": [
            {"node_id": "seed", "objective": "Create source state", "state_exports": ["source"]},
            {"node_id": "left", "objective": "Use source", "dependencies": ["seed"]},
            {"node_id": "right", "objective": "Use source", "dependencies": ["seed"]},
            {"node_id": "join", "objective": "Reconcile", "dependencies": ["left", "right"]},
        ],
    })

    pipeline = graph.to_pipeline()

    assert [node.node_id for node in graph.topological_order()] == ["seed", "left", "right", "join"]
    join = next(step for step in pipeline.steps if step.step_id == "join")
    assert join.inputs_from_steps == ["left", "right"]


def test_task_graph_rejects_missing_and_cyclic_dependencies():
    with pytest.raises(TaskGraphValidationError, match="unknown dependency"):
        TaskGraph.from_dict({
            "graph_id": "missing",
            "title": "Missing dependency",
            "nodes": [{"node_id": "a", "objective": "A", "dependencies": ["b"]}],
        })


def test_task_graph_expands_declared_subtasks_into_narrow_nodes():
    graph = TaskGraph.from_dict({
        "graph_id": "expanded",
        "title": "Expanded graph",
        "nodes": [
            {
                "node_id": "broad",
                "objective": "Broad implementation task",
                "subtasks": ["Create deterministic input", "Verify deterministic output"],
                "state_exports": ["output_value"],
                "verification_criteria": [{"type": "repl_variable", "variable": "output_value"}],
            },
            {"node_id": "downstream", "objective": "Use the verified output", "dependencies": ["broad"]},
        ],
    })

    order = graph.topological_order()
    terminal = next(node for node in order if node.node_id == "broad__2")
    downstream = next(node for node in order if node.node_id == "downstream")

    assert [node.node_id for node in order] == ["broad__1", "broad__2", "downstream"]
    assert terminal.state_exports == ("output_value",)
    assert downstream.dependencies == ("broad__2",)
    with pytest.raises(TaskGraphValidationError, match="cycle"):
        TaskGraph.from_dict({
            "graph_id": "cycle",
            "title": "Cycle",
            "nodes": [
                {"node_id": "a", "objective": "A", "dependencies": ["b"]},
                {"node_id": "b", "objective": "B", "dependencies": ["a"]},
            ],
        })


def test_task_graph_runner_executes_verified_dependency_order():
    reset_repl_globals()
    graph = TaskGraph.from_dict({
        "graph_id": "state_graph",
        "title": "State graph",
        "nodes": [
            {
                "node_id": "seed",
                "objective": "Create source value in python_repl.",
                "specialist": "coder",
                "tool_allowlist": ["python_repl"],
                "state_exports": ["source_value"],
                "verification_criteria": [{"type": "repl_variable", "variable": "source_value", "assertion": "source_value == 41"}],
            },
            {
                "node_id": "consume",
                "objective": "Create derived value using source_value in python_repl.",
                "dependencies": ["seed"],
                "specialist": "coder",
                "tool_allowlist": ["python_repl"],
                "verification_criteria": [{"type": "repl_variable", "variable": "derived_value", "assertion": "derived_value == 42"}],
            },
        ],
    })
    responses = [
        json.dumps({"thought": "seed", "action": {"tool": "python_repl", "args": {"code": "source_value = 41"}}, "final_answer": None}),
        json.dumps({"thought": "done", "action": None, "final_answer": "seeded"}),
        json.dumps({"thought": "consume", "action": {"tool": "python_repl", "args": {"code": "derived_value = source_value + 1"}}, "final_answer": None}),
        json.dumps({"thought": "done", "action": None, "final_answer": "derived"}),
    ]

    with tempfile.TemporaryDirectory() as directory:
        pipeline_runner = StructuredPipelineRunner(_GraphLLM(responses), workspace_dir=directory, verbose=False)
        result = TaskGraphRunner(pipeline_runner).run(graph, approval_callback=lambda _tool, _args: True)

    assert result.success is True
    assert result.execution_order == ["seed", "consume"]
    assert result.pipeline_result.steps_passed == 2
    assert any(event.event_type == "task_graph_completed" for event in pipeline_runner.event_log.events)


def test_task_graph_parallel_batches_only_read_only_independent_nodes():
    graph = TaskGraph.from_dict({
        "graph_id": "parallel_graph",
        "title": "Parallel graph",
        "nodes": [
            {"node_id": "read_a", "objective": "Read A", "tools": ["read_file"]},
            {"node_id": "read_b", "objective": "Read B", "tools": ["calc"]},
            {"node_id": "write", "objective": "Write", "tools": ["write_file"]},
            {"node_id": "merge", "objective": "Merge", "dependencies": ["read_a", "read_b", "write"]},
        ],
    })
    assert [[node.node_id for node in batch] for batch in graph.parallel_batches()] == [
        ["read_a", "read_b"], ["write"], ["merge"],
    ]


def test_task_graph_runner_runs_read_only_batches_in_graph_order():
    graph = TaskGraph.from_dict({
        "graph_id": "parallel_runner",
        "title": "Parallel runner",
        "nodes": [
            {"node_id": "left", "objective": "Left", "tools": ["calc"]},
            {"node_id": "right", "objective": "Right", "tools": ["calc"]},
            {"node_id": "after", "objective": "After", "dependencies": ["left", "right"], "tools": ["read_file"]},
        ],
    })
    runner = TaskGraphRunner(type("Runner", (), {"event_log": EventLog()})())
    result = runner.run_read_only_parallel(graph, lambda node: node.objective)
    assert list(result) == ["left", "right", "after"]
    assert result["after"] == "After"
