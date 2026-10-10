import json
import os

from agents.orchestrator import OrchestratorAgent
from llm_client import LLMClient
from tal.action_gate import ActionGate
from tal.capability import CapabilityEnvelope
from tal.proposal_types import ActionProposal
from tal.verification import materialize_missing_deliverables
from tools.file_tools import write_file


def test_write_file_ast_syntax_guard(temp_workspace):
    # Valid python file
    valid_code = "def hello():\n    return 'world'\n"
    res1 = write_file(json.dumps({"path": "valid.py", "content": valid_code}))
    assert "File written successfully" in res1
    assert os.path.exists(os.path.join(temp_workspace, "valid.py"))

    # Malformed / truncated python file
    broken_code = "class AttackGraph:\n    def __"
    res2 = write_file(json.dumps({"path": "broken.py", "content": broken_code}))
    assert "Python SyntaxError" in res2
    assert not os.path.exists(os.path.join(temp_workspace, "broken.py"))

    # Non-python files (e.g. .json, .md, .txt) should not be checked by ast.parse
    res3 = write_file(json.dumps({"path": "doc.md", "content": "# Just Markdown\nNot python!"}))
    assert "File written successfully" in res3


def test_deliverable_auto_materializer(temp_workspace):
    context_text = """
### Deliverables Generated
#### **File: `incident_graph_data.json`**
```json
{
  "incident_id": "#INC-8821",
  "nodes_compromised": 4,
  "status": "contained"
}
```

#### **File: `incident_response_report.md`**
```markdown
# Incident Response Report
- Incident ID: #INC-8821
- Priority: Critical
```
"""
    missing = ["incident_graph_data.json", "incident_response_report.md"]
    materialized = materialize_missing_deliverables(context_text, temp_workspace, missing)
    
    assert "incident_graph_data.json" in materialized
    assert "incident_response_report.md" in materialized

    # Verify content on disk
    json_path = os.path.join(temp_workspace, "incident_graph_data.json")
    assert os.path.exists(json_path)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["incident_id"] == "#INC-8821"

    md_path = os.path.join(temp_workspace, "incident_response_report.md")
    assert os.path.exists(md_path)
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "# Incident Response Report" in content


def test_action_gate_schema_auto_heal(temp_workspace):
    # Write a test file to the workspace
    test_file = os.path.join(temp_workspace, "active_report.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("report data")

    gate = ActionGate()
    envelope = CapabilityEnvelope(effective={"read_file"})
    
    # Model emits read_file without path
    proposal = ActionProposal(thought="Checking results", tool_name="read_file", tool_args={})
    res = gate.evaluate(proposal, envelope)
    
    assert res.allowed is True
    assert res.sanitized_args is not None
    assert res.sanitized_args.get("path") == "active_report.txt"


def test_orchestrator_pre_synthesis_remediation(temp_workspace):
    """Test that Orchestrator triggers remediation or materialization if expected deliverables are missing."""
    class RemediationMockLLM(LLMClient):
        def __init__(self):
            super().__init__(model="mock")
            self.calls = 0

        def generate(self, messages, json_mode=False):
            self.calls += 1
            if self.calls == 1:
                # Delegate to coder
                return "DELEGATE: coder: write the output files"
            elif self.calls == 2:
                # Specialist fails to call tool and only gives text
                return "I have analyzed the scenario."
            elif self.calls == 3:
                # Remediation turn: specialist writes the file
                return '{"thought": "Writing missing file", "action": {"tool": "write_file", "args": {"path": "remediation_output.json", "content": "{\\"status\\": \\"remediated\\"}"}}, "final_answer": null}'
            else:
                return "Final synthesized response."

        @staticmethod
        def list_models():
            return ["mock"]

    orchestrator = OrchestratorAgent(llm_client=RemediationMockLLM(), verbose=False, guardrails_enabled=False, tal_mode=True)
    goal = "Execute pipeline and save result to remediation_output.json"
    ans = orchestrator.run(goal)

    output_path = os.path.join(temp_workspace, "remediation_output.json")
    assert not os.path.exists(output_path)
