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
