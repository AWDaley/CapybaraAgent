import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import BasicAgent
from llm_client import LLMClient
from planning_agent import PlanningAgent
from tal.task_graph import TaskGraph


class LocalMockLLM(LLMClient):
    def __init__(self, text="1. Step one\n2. Step two"):
        super().__init__(model="mock")
        self.text = text
    def generate(self, messages, json_mode=False):
        return self.text
    @staticmethod
    def list_models():
        return ["mock"]

def test_planning_agent_plan():
    mock_llm = LocalMockLLM("1. Step one\n2. Step two\n3. Step three")
    basic = BasicAgent(llm_client=mock_llm, verbose=False)
    planner = PlanningAgent(basic, mock_llm)
    
    steps = planner.plan("Build a web app")
    assert steps == ["Step one", "Step two", "Step three"]

def test_planning_agent_re_plan():
    mock_llm = LocalMockLLM("1. Revised step one\n2. Revised step two")
    basic = BasicAgent(llm_client=mock_llm, verbose=False)
    planner = PlanningAgent(basic, mock_llm)
    
    steps = planner.re_plan("Build a web app", ["Done step"], "Failed step", ["Remaining step"], "Error 500")
    assert steps == ["Revised step one", "Revised step two"]


def test_tal_planning_agent_emits_typed_task_graph():
    graph = {
        "graph_id": "web_app",
        "title": "Build web app",
        "nodes": [
            {"node_id": "inspect", "objective": "Inspect the workspace", "tool_allowlist": ["list_files"]},
            {"node_id": "implement", "objective": "Implement the smallest change", "dependencies": ["inspect"], "specialist": "coder"},
        ],
    }
    mock_llm = LocalMockLLM(json.dumps(graph))
    basic = BasicAgent(llm_client=mock_llm, verbose=False, tal_mode=True)
    planner = PlanningAgent(basic, mock_llm, tal_mode=True)

    planned = planner.plan_task_graph("Build a web app")

    assert isinstance(planned, TaskGraph)
    assert [node.node_id for node in planned.topological_order()] == ["inspect", "implement"]


def test_tal_planning_uses_graph_for_all_interfaces(monkeypatch):
    graph = TaskGraph.from_dict({
        "graph_id": "common", "title": "Common",
        "nodes": [{"node_id": "one", "objective": "Bounded step"}],
    })
    client = LocalMockLLM()
    planner = PlanningAgent(
        BasicAgent(llm_client=client, verbose=False, tal_mode=True),
        client, tal_mode=True,
    )
    routes = []
    def graph_plan(goal):
        routes.append("graph")
        return graph

    def run_graph(item, approval_callback=None, on_thought=None, on_specialist_event=None):
        routes.append("execute_graph")
        planner.last_outcome = "completed_unverified"
        return "same answer"

    monkeypatch.setattr(planner, "plan_task_graph", graph_plan)
    monkeypatch.setattr(planner, "execute_task_graph", run_graph)
    monkeypatch.setattr(
        planner, "plan",
        lambda *_: (_ for _ in ()).throw(AssertionError("Legacy planner was used")),
    )
    assert planner.run("same goal") == "same answer"
    assert planner.run_with_trace("same goal")["response"] == "same answer"
    events = []
    planner.run_streaming("same goal", lambda kind, data: events.append((kind, data)))
    assert routes.count("graph") == routes.count("execute_graph") == 3
    assert sum(kind == "answer" for kind, _ in events) == 1


def test_planning_trace_reports_invalid_graph_as_failed():
    client = LocalMockLLM("invalid non-json plan")
    planner = PlanningAgent(
        BasicAgent(llm_client=client, verbose=False, tal_mode=True), client, tal_mode=True,
    )
    trace = planner.run_with_trace("Do something")
    assert trace["outcome"] == "failed"
    assert "valid task graph" in trace["response"]
