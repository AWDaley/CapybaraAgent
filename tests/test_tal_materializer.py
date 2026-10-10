import json
import os
import tempfile
from dataclasses import dataclass

from tal.materializer import OutputMaterializer
from tal.pipeline_runner import StructuredPipelineRunner
from tal.schemas import OutputSpec, PipelineStep, StructuredPipeline


@dataclass
class CustomPoint:
    x: int
    y: int


class MockNetworkXGraph:
    def nodes(self, data=False):
        return [("node_1", {"zone": "DMZ"}), ("node_2", {"zone": "INTERNAL"})]

    def edges(self, data=False):
        return [("node_1", "node_2", {"weight": 2.5})]


def test_coerce_serializable():
    data = {
        "set_val": {1, 2, 3},
        "tuple_val": (4, 5),
        "point": CustomPoint(x=10, y=20),
        "graph": MockNetworkXGraph()
    }
    res = OutputMaterializer.coerce_serializable(data)
    assert isinstance(res["set_val"], list)
    assert set(res["set_val"]) == {1, 2, 3}
    assert res["tuple_val"] == [4, 5]
    assert res["point"] == {"x": 10, "y": 20}
    assert "nodes" in res["graph"]
    assert len(res["graph"]["nodes"]) == 2


def test_resolve_template():
    repl_globals = {
        "count": 42,
        "nodes": ["A", "B", "C"],
        "info": {"status": "ok"}
    }
    template = {
        "title": "Report",
        "total_count": "$eval:count * 2",
        "first_node": "$eval:nodes[0]",
        "nested": {
            "all_nodes": "$eval:nodes",
            "info_status": "$eval:info['status']"
        }
    }
    resolved = OutputMaterializer.resolve_template(template, repl_globals)
    assert resolved["title"] == "Report"
    assert resolved["total_count"] == 84
    assert resolved["first_node"] == "A"
    assert resolved["nested"]["all_nodes"] == ["A", "B", "C"]
    assert resolved["nested"]["info_status"] == "ok"


def test_materialize_to_file_template():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = OutputSpec(
            target_file="test_out.json",
            spec_type="repl_template",
            template={
                "incident_id": "#INC-1234",
                "calculated_value": "$eval:val * 10"
            }
        )
        repl_globals = {"val": 5}
        ok, msg, data = OutputMaterializer.materialize_to_file(spec, tmpdir, repl_globals)
        assert ok is True
        assert "Materialized" in msg or "materialized" in msg
        assert data["calculated_value"] == 50

        out_path = os.path.join(tmpdir, "test_out.json")
        assert os.path.exists(out_path)
        with open(out_path, "r") as f:
            disk_data = json.load(f)
        assert disk_data["calculated_value"] == 50


def test_zero_llm_harness_step_in_pipeline():
    from tools.external_tools import python_repl, reset_repl_globals
    reset_repl_globals()
    python_repl({"code": "computed_metrics = {'score': 95, 'hosts': ['H1', 'H2', 'H3']}"})

    with tempfile.TemporaryDirectory() as tmpdir:
        class TrackingMockLLM:
            def __init__(self):
                self.calls = 0
                self.model = "mock"
                self.provider = "mock"

            def generate(self, messages, json_mode=False, callback=None):
                self.calls += 1
                return '{"thought": "done", "action": null, "final_answer": "ok"}'

            def generate_with_retry(self, messages, json_mode=False, max_retries=2, retry_delay=1.0, callback=None):
                return self.generate(messages, json_mode=json_mode, callback=callback)

            def count_tokens(self, text):
                return len(str(text)) // 4

        mock_llm = TrackingMockLLM()

        pipeline = StructuredPipeline(
            pipeline_id="p_harness",
            title="Harness Zero-LLM Test",
            global_context={},
            steps=[
                PipelineStep(
                    step_id="step_materialize",
                    specialist="harness",
                    objective="Deterministically write computed_metrics to metrics.json",
                    output_spec=OutputSpec(
                        target_file="metrics.json",
                        spec_type="repl_template",
                        template={
                            "system": "capybara",
                            "score": "$eval:computed_metrics['score']",
                            "hosts": "$eval:computed_metrics['hosts']"
                        }
                    ),
                    verification_criteria=[
                        {"type": "file_exists", "path": "metrics.json", "min_size": 5},
                        {"type": "json_schema", "path": "metrics.json", "required_keys": ["system", "score", "hosts"]}
                    ]
                )
            ]
        )

        runner = StructuredPipelineRunner(
            llm_client=mock_llm,
            workspace_dir=tmpdir,
            verbose=False
        )

        res = runner.run(pipeline)
        assert res.success is True
        assert res.steps_passed == 1
        # ZERO LLM calls should have been made for the harness step
        assert mock_llm.calls == 0

        target_file = os.path.join(tmpdir, "metrics.json")
        assert os.path.exists(target_file)
        with open(target_file, "r") as f:
            data = json.load(f)
        assert data["score"] == 95
        assert data["hosts"] == ["H1", "H2", "H3"]


def test_resolve_markdown_template_with_inline_eval():
    repl_globals = {
        "incident_id": "#INC-8821",
        "shortest_path": ["DMZ_WEB_01", "DMZ_WEB_02", "CORE_DB_01"],
        "shortest_path_text": "DMZ_WEB_01 -> DMZ_WEB_02 -> CORE_DB_01",
        "blast_radius": 6
    }
    template = (
        "# Incident Report: $eval{incident_id}\n\n"
        "**Path**: ${eval:shortest_path_text}\n"
        "**Blast Radius**: $eval{blast_radius} nodes"
    )
    resolved = OutputMaterializer.resolve_template(template, repl_globals)
    assert "# Incident Report: #INC-8821" in resolved
    assert "**Path**: DMZ_WEB_01 -> DMZ_WEB_02 -> CORE_DB_01" in resolved
    assert "**Blast Radius**: 6 nodes" in resolved


def test_materialize_to_file_markdown_template():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = OutputSpec(
            target_file="incident_report.md",
            spec_type="markdown_template",
            template=(
                "# Incident Response Deliverable\n"
                "Incident ID: $eval{incident['id']}\n"
                "Compromised Host: $eval{incident['initial_vector']}"
            )
        )
        repl_globals = {"incident": {"id": "#INC-9999", "initial_vector": "DMZ_WEB_01"}}
        ok, msg, data = OutputMaterializer.materialize_to_file(spec, tmpdir, repl_globals)
        assert ok is True
        assert "incident_report.md" in msg

        out_path = os.path.join(tmpdir, "incident_report.md")
        assert os.path.exists(out_path)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Incident ID: #INC-9999" in content
        assert "Compromised Host: DMZ_WEB_01" in content
