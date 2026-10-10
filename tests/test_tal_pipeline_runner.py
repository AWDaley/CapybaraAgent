import json
import os
import tempfile
import time

import tools.file_tools
from prompt_loader import load_prompts_from_file
from tal.pipeline_runner import StructuredPipelineRunner
from tal.schemas import PipelineStep, StructuredPipeline
from llm_client import LLMClient


class MockLLMClient:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.messages_received = []
        self.model = "mock-slm:4b"
        self.provider = "mock"

    def generate(self, messages, json_mode=False, callback=None):
        self.messages_received.append(messages)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            if callback:
                callback(resp)
            return resp
        resp = '{"thought": "done", "action": null, "final_answer": "Task complete."}'
        if callback:
            callback(resp)
        return resp

    def generate_with_retry(self, messages, json_mode=False, max_retries=2, retry_delay=1.0, callback=None):
        return self.generate(messages, json_mode=json_mode, callback=callback)

    def count_tokens(self, text):
        return len(str(text)) // 4


class DeadlineAwareSlowLLM(LLMClient):
    def __init__(self):
        super().__init__(model="slow-test")
        self.provider = "test"
        self.timeouts = []

    @staticmethod
    def list_models():
        return []

    def generate(self, messages, json_mode=False, timeout_seconds=None):
        self.timeouts.append(timeout_seconds)
        time.sleep(min(timeout_seconds or 0.01, 0.05) + 0.01)
        raise TimeoutError("simulated provider timeout")



def test_pipeline_loader_ingestion():
    with tempfile.TemporaryDirectory() as tmpdir:
        pipe_path = os.path.join(tmpdir, "test_pipeline.json")
        pipeline_json = {
            "pipeline_id": "p1",
            "title": "Math & File Pipeline",
            "global_context": {"env": "test"},
            "pipeline": [
                {
                    "step_id": "step_calc",
                    "specialist": "coder",
                    "objective": "Calculate 5 + 5",
                    "verification": [{"type": "non_empty", "output": "10"}]
                }
            ]
        }
        with open(pipe_path, "w") as f:
            json.dump(pipeline_json, f)

        loaded = load_prompts_from_file(pipe_path)
        assert len(loaded) == 1
        assert loaded[0].get("is_pipeline") is True
        pipeline_obj = loaded[0].get("pipeline")
        assert isinstance(pipeline_obj, StructuredPipeline)
        assert pipeline_obj.pipeline_id == "p1"
        assert len(pipeline_obj.steps) == 1
        assert pipeline_obj.steps[0].step_id == "step_calc"


def test_pipeline_runner_success():
    import tools.file_tools
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            out_file = "test_out.txt"
            target_path = os.path.join(tmpdir, out_file)

            # Mock LLM calls write_file tool
            mock_llm = MockLLMClient([
                f'{{"thought": "writing file", "action": {{"tool": "write_file", "args": {{"path": "{out_file}", "content": "hello pipeline"}}}}, "final_answer": null}}',
                '{"thought": "done", "action": null, "final_answer": "Created test_out.txt"}'
            ])

            pipeline = StructuredPipeline(
                pipeline_id="p_test",
                title="File Creation Pipeline",
                global_context={},
                steps=[
                    PipelineStep(
                        step_id="step_1",
                        objective="Write hello pipeline to test_out.txt",
                        specialist="coder",
                        tool_allowlist=["write_file"],
                        verification_criteria=[{"type": "file_exists", "path": out_file, "min_size": 5}]
                    )
                ]
            )

            runner = StructuredPipelineRunner(
                llm_client=mock_llm,
                workspace_dir=tmpdir,
                verbose=False
            )

            res = runner.run(pipeline, approval_callback=lambda _tool, _args: True)
            assert res.success is True
            assert res.steps_passed == 1
            assert len(res.step_telemetry) == 1
            assert res.step_telemetry[0].status == "passed"
            assert os.path.exists(target_path)
            checkpoint_path = os.path.join(tmpdir, ".pipeline_checkpoints", "p_test.json")
            with open(checkpoint_path, encoding="utf-8") as checkpoint:
                saved = json.load(checkpoint)
            assert saved["artifact_catalog"][out_file]["source_node"] == "step_1"
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_pipeline_runner_anti_cascading_barrier():
    """Verify that when Step 1 fails, Step 2 is blocked and never executed."""
    import tools.file_tools
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            # Mock LLM that fails to create file on Step 1
            mock_llm = MockLLMClient([
                '{"thought": "doing nothing", "action": null, "final_answer": "I refused to write file"}',
                '{"thought": "retry 1", "action": null, "final_answer": "Still no file"}',
                '{"thought": "retry 2", "action": null, "final_answer": "Still no file"}'
            ])

            pipeline = StructuredPipeline(
                pipeline_id="p_barrier",
                title="Barrier Test",
                global_context={},
                steps=[
                    PipelineStep(
                        step_id="step_fail",
                        objective="Create mandatory file",
                        specialist="coder",
                        verification_criteria=[{"type": "file_exists", "path": "never_created.txt", "min_size": 1}],
                        max_retries=1
                    ),
                    PipelineStep(
                        step_id="step_never_runs",
                        objective="This step should never be reached",
                        specialist="general"
                    )
                ]
            )

            runner = StructuredPipelineRunner(
                llm_client=mock_llm,
                workspace_dir=tmpdir,
                verbose=False
            )

            res = runner.run(pipeline, approval_callback=lambda _tool, _args: True)
            assert res.success is False
            assert res.steps_passed == 0
            assert len(res.step_telemetry) == 1  # Only step 1 was attempted
            assert res.step_telemetry[0].status == "failed_verification"
            assert "Pipeline halted" in (res.error or "")
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_distributed_saga_step_one_missing_leaf_is_reported_and_blocks_pipeline():
    """A missing leaf key must fail step 1 and prevent downstream execution."""
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            missing_leaf_code = (
                "service_nodes = [\n"
                "    {'id': 'API_GATEWAY'}, {'id': 'ORDER_SVC'}, {'id': 'INVENTORY_SVC'},\n"
                "    {'id': 'PAYMENT_SVC'}, {'id': 'SHIPPING_SVC'}, {'id': 'NOTIFY_SVC'},\n"
                "    {'id': 'ORDER_DB'}, {'id': 'INVENTORY_DB'}, {'id': 'PAYMENT_LEDGER'},\n"
                "    {'id': 'EVENT_BUS'}, {'id': 'SAGA_ORCHESTRATOR'}, {'id': 'AUDIT_STORE'}\n"
                "]\n"
                "service_graph = {\n"
                "    'API_GATEWAY': ['ORDER_SVC'], 'ORDER_SVC': [],\n"
                "    'INVENTORY_SVC': [], 'PAYMENT_SVC': [], 'SHIPPING_SVC': [],\n"
                "    'NOTIFY_SVC': [], 'ORDER_DB': [], 'INVENTORY_DB': [],\n"
                "    'PAYMENT_LEDGER': [], 'EVENT_BUS': [], 'SAGA_ORCHESTRATOR': []\n"
                "}"
            )
            mock_llm = MockLLMClient([
                '{"thought": "build graph", "action": {"tool": "python_repl", "args": {"code": ' + json.dumps(missing_leaf_code) + '}}, "final_answer": null}',
                '{"thought": "retry graph", "action": {"tool": "python_repl", "args": {"code": ' + json.dumps(missing_leaf_code) + '}}, "final_answer": null}',
                '{"thought": "retry graph", "action": {"tool": "python_repl", "args": {"code": ' + json.dumps(missing_leaf_code) + '}}, "final_answer": null}',
            ])

            pipeline = StructuredPipeline(
                pipeline_id="distributed_saga_regression",
                title="Distributed Saga Regression",
                global_context={},
                steps=[
                    PipelineStep(
                        step_id="step_1_build_service_model",
                        objective="Build the 12-service graph.",
                        specialist="coder",
                        tool_allowlist=["python_repl"],
                        verification_criteria=[
                            {"type": "repl_variable", "variable": "service_nodes", "assertion": "len(service_nodes) == 12"},
                            {"type": "repl_graph", "variable": "service_graph", "expected_graph": {
                                "API_GATEWAY": ["ORDER_SVC"], "ORDER_SVC": [], "INVENTORY_SVC": [],
                                "PAYMENT_SVC": [], "SHIPPING_SVC": [], "NOTIFY_SVC": [],
                                "ORDER_DB": [], "INVENTORY_DB": [], "PAYMENT_LEDGER": [],
                                "EVENT_BUS": [], "SAGA_ORCHESTRATOR": [], "AUDIT_STORE": [],
                            }},
                        ],
                        max_retries=2,
                    ),
                    PipelineStep(
                        step_id="step_2_never_runs",
                        objective="This must not run after step 1 fails.",
                        specialist="coder",
                    ),
                ],
            )
            runner = StructuredPipelineRunner(llm_client=mock_llm, workspace_dir=tmpdir, verbose=False)

            result = runner.run(pipeline, approval_callback=lambda _tool, _args: True)

            assert result.success is False
            assert result.steps_passed == 0
            assert [telemetry.step_id for telemetry in result.step_telemetry] == ["step_1_build_service_model"]
            assert result.step_telemetry[0].attempts == 3
            assert result.step_telemetry[0].status == "failed_verification"
            assert result.tool_call_count == 3
            assert "missing keys" in result.step_telemetry[0].error
            assert "same action failed verification" in result.step_telemetry[0].error
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_distributed_saga_fixture_requires_explicit_audit_store_leaf():
    pipeline_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "distributed_saga_recovery_pipeline.json"
    )
    with open(pipeline_path, "r", encoding="utf-8") as handle:
        pipeline_data = json.load(handle)

    step = pipeline_data["pipeline"][0]
    assert "AUDIT_STORE -> []" in step["objective"]
    graph_criterion = next(
        criterion for criterion in step["verification_criteria"]
        if criterion.get("type") == "repl_graph"
    )
    assert graph_criterion["expected_graph"]["AUDIT_STORE"] == []
    assert len(graph_criterion["expected_graph"]) == 12


def test_pipeline_runner_remediation_recovery():
    """Verify that a step failing verification on attempt 1 can recover on attempt 2."""
    import tools.file_tools
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            out_file = "remediated.txt"
            target_path = os.path.join(tmpdir, out_file)

            # Attempt 1 does nothing, Attempt 2 creates the file after receiving remediation feedback
            mock_llm = MockLLMClient([
                # Attempt 1
                '{"thought": "failed attempt", "action": null, "final_answer": "forgot tool"}',
                # Attempt 2 (remediation turn)
                f'{{"thought": "fixing now", "action": {{"tool": "write_file", "args": {{"path": "{out_file}", "content": "fixed content"}}}}, "final_answer": null}}',
                '{"thought": "done", "action": null, "final_answer": "file fixed"}'
            ])

            pipeline = StructuredPipeline(
                pipeline_id="p_remed",
                title="Remediation Recovery Test",
                global_context={},
                steps=[
                    PipelineStep(
                        step_id="step_remed",
                        objective="Write remediated.txt",
                        specialist="coder",
                        tool_allowlist=["write_file"],
                        verification_criteria=[{"type": "file_exists", "path": out_file, "min_size": 5}],
                        max_retries=2
                    )
                ]
            )

            runner = StructuredPipelineRunner(
                llm_client=mock_llm,
                workspace_dir=tmpdir,
                verbose=False
            )

            res = runner.run(pipeline, approval_callback=lambda _tool, _args: True)
            assert res.success is True
            assert res.steps_passed == 1
            assert res.step_telemetry[0].attempts >= 1
            assert res.step_telemetry[0].status == "passed"
            assert os.path.exists(target_path)
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_pipeline_runner_retry_preserves_context_and_accepts_corrective_action():
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            bad_code = "service_graph = {'A': []}"
            good_code = "service_graph = {'A': [], 'B': []}"
            mock_llm = MockLLMClient([
                '{"thought": "bad graph", "action": {"tool": "python_repl", "args": {"code": ' + json.dumps(bad_code) + '}}, "final_answer": null}',
                '{"thought": "correcting graph", "action": {"tool": "python_repl", "args": {"code": ' + json.dumps(good_code) + '}}, "final_answer": null}',
            ])
            pipeline = StructuredPipeline(
                pipeline_id="retry_context",
                title="Retry Context",
                global_context={},
                steps=[PipelineStep(
                    step_id="step_retry",
                    objective="Create the graph.",
                    specialist="coder",
                    tool_allowlist=["python_repl"],
                    verification_criteria=[{
                        "type": "repl_graph",
                        "variable": "service_graph",
                        "expected_graph": {"A": [], "B": []},
                    }],
                    max_retries=1,
                )],
            )
            runner = StructuredPipelineRunner(llm_client=mock_llm, workspace_dir=tmpdir, verbose=False)

            result = runner.run(pipeline, approval_callback=lambda _tool, _args: True)

            assert result.success is True
            assert result.step_telemetry[0].attempts == 2
            assert result.tool_call_count == 2
            assert any(
                "PREVIOUS ATTEMPT FAILED ACCEPTANCE GATES" in str(message.get("content", ""))
                for call in mock_llm.messages_received[1:]
                for message in call
            )
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_pipeline_runner_empty_model_responses_receive_actionable_retry_feedback():
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            mock_llm = MockLLMClient(["", "", ""])
            pipeline = StructuredPipeline(
                pipeline_id="empty_response_retry",
                title="Empty Response Retry",
                global_context={},
                steps=[PipelineStep(
                    step_id="step_empty",
                    objective="Create required state.",
                    specialist="coder",
                    tool_allowlist=["python_repl"],
                    verification_criteria=[{
                        "type": "repl_variable",
                        "variable": "required_state",
                    }],
                    max_retries=2,
                )],
            )
            runner = StructuredPipelineRunner(llm_client=mock_llm, workspace_dir=tmpdir, verbose=False)

            result = runner.run(pipeline, approval_callback=lambda _tool, _args: True)

            assert result.success is False
            assert result.step_telemetry[0].attempts == 3
            assert "no actionable completion" in result.step_telemetry[0].error.lower()
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_pipeline_runner_stops_after_verified_tool_state_without_requesting_completion():
    """A valid side effect must pass without a second model turn for completion JSON."""
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    mock_llm = MockLLMClient([
        '{"thought":"set state","action":{"tool":"python_repl","args":{"code":"verified_value = 7"}},"final_answer":null}',
        '{"thought":"done","action":null,"final_answer":"ok","unexpected":true}',
    ])
    pipeline = StructuredPipeline(
        pipeline_id="verified_state_malformed_completion",
        title="Verified State With Malformed Completion",
        steps=[PipelineStep(
            step_id="set_state",
            objective="Set verified_value to 7.",
            specialist="coder",
            tool_allowlist=["python_repl"],
            verification_criteria=[{
                "type": "repl_variable",
                "variable": "verified_value",
                "assertion": "verified_value == 7",
            }],
        )],
    )

    result = StructuredPipelineRunner(llm_client=mock_llm, verbose=False).run(
        pipeline,
        approval_callback=lambda _tool, _args: True,
    )

    assert result.success is True
    assert result.step_telemetry[0].verification_passed is True
    assert result.protocol_error_count == 0
    assert mock_llm.call_count == 1


def test_pipeline_runner_retries_with_exact_tool_rejection_message():
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    mock_llm = MockLLMClient([
        '{"thought":"bad graph","action":{"tool":"python_repl","args":{"code":"graph = {\'A\': [], \'A\': []}"}},"final_answer":null}',
        '{"thought":"correct graph","action":{"tool":"python_repl","args":{"code":"graph = {\'A\': []}"}},"final_answer":null}',
    ])
    pipeline = StructuredPipeline(
        pipeline_id="tool_error_remediation",
        title="Tool Error Remediation",
        steps=[PipelineStep(
            step_id="graph",
            objective="Set graph.",
            specialist="coder",
            tool_allowlist=["python_repl"],
            verification_criteria=[{
                "type": "repl_graph",
                "variable": "graph",
                "expected_graph": {"A": []},
            }],
            max_retries=1,
        )],
    )

    result = StructuredPipelineRunner(llm_client=mock_llm, verbose=False).run(
        pipeline,
        approval_callback=lambda _tool, _args: True,
    )

    assert result.success is True
    assert result.tool_error_count == 1
    assert any(
        "Duplicate literal dictionary key" in str(message.get("content", ""))
        for message in mock_llm.messages_received[1]
    )
    assert "Deterministic verification passed" in result.step_telemetry[0].output


def test_pipeline_runner_specialist_tool_allowlist_cannot_expand_domain_policy():
    """A step allowlist cannot grant the general pack an execution capability."""
    import tools.file_tools
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            out_file = "general_out.txt"
            target_path = os.path.join(tmpdir, out_file)

            mock_llm = MockLLMClient([
                '{"thought": "general writing", "action": {"tool": "python_repl", "args": {"code": "x = 1"}}}',
                '{"thought": "done", "action": null, "final_answer": "Complete"}'
            ])

            pipeline = StructuredPipeline(
                pipeline_id="p_allowlist",
                title="Allowlist Test",
                global_context={},
                steps=[
                    PipelineStep(
                        step_id="step_gen_write",
                        objective="Generate file using general specialist",
                        specialist="general",
                        tool_allowlist=["python_repl"],
                        verification_criteria=[{"type": "file_exists", "path": out_file, "min_size": 5}]
                    )
                ]
            )

            runner = StructuredPipelineRunner(
                llm_client=mock_llm,
                workspace_dir=tmpdir,
                verbose=False
            )

            res = runner.run(pipeline, approval_callback=lambda _tool, _args: True)
            assert res.success is False
            assert res.steps_passed == 0
            assert not os.path.exists(target_path)
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_pipeline_runner_stale_artifact_does_not_prove_step_success():
    """Existing user artifacts are retained but cannot satisfy fresh-output gates."""
    import tools.file_tools
    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            stale_file = "stale_output.txt"
            stale_path = os.path.join(tmpdir, stale_file)

            # Pre-create stale file
            with open(stale_path, "w", encoding="utf-8") as f:
                f.write("old stale content")

            # Mock LLM that fails to produce a file
            mock_llm = MockLLMClient([
                '{"thought": "doing nothing", "action": null, "final_answer": "No file created"}',
                '{"thought": "still doing nothing", "action": null, "final_answer": "Still no file"}'
            ])

            pipeline = StructuredPipeline(
                pipeline_id="p_stale",
                title="Stale Artifact Cleanup Test",
                global_context={},
                steps=[
                    PipelineStep(
                        step_id="step_clean",
                        objective="Produce target deliverable",
                        specialist="general",
                        tool_allowlist=["write_file"],
                        verification_criteria=[{"type": "file_exists", "path": stale_file, "min_size": 1}],
                        max_retries=1
                    )
                ]
            )

            runner = StructuredPipelineRunner(
                llm_client=mock_llm,
                workspace_dir=tmpdir,
                verbose=False
            )

            res = runner.run(pipeline, approval_callback=lambda _tool, _args: True)
            # The stale file remains, but it cannot prove this step produced it.
            assert res.success is False
            assert os.path.exists(stale_path)
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_pipeline_runner_epistemic_priming():
    """Verify that verified epistemic facts are injected into step context for downstream specialists."""
    from tal.epistemic import EpistemicState
    mock_llm = MockLLMClient([])
    runner = StructuredPipelineRunner(llm_client=mock_llm, verbose=False)
    runner.epistemic_store.add_fact("Target DMZ_WEB_01 compromised", state=EpistemicState.VERIFIED, source="test")

    pipeline = StructuredPipeline(
        pipeline_id="p_epistemic",
        title="Epistemic Priming Test",
        global_context={},
        steps=[
            PipelineStep(
                step_id="step_check",
                objective="Synthesize report",
                specialist="general"
            )
        ]
    )

    ctx = runner._build_step_context(pipeline, pipeline.steps[0], step_results={})
    assert "### Established Verified Facts:" in ctx
    assert "Target DMZ_WEB_01 compromised" in ctx


def test_zero_trust_microsegmentation_pipeline_loads_and_runs(temp_workspace):
    """Verify that the new 5-step zero trust microsegmentation pipeline loads and executes through the harness."""
    import tempfile

    from tools.external_tools import reset_repl_globals
    reset_repl_globals()

    pipeline_path = os.path.join(os.path.dirname(__file__), "..", "data", "zero_trust_microsegmentation_pipeline.json")
    with open(pipeline_path, "r", encoding="utf-8") as f:
        p_data = json.load(f)

    pipeline = StructuredPipeline.from_dict(p_data)
    assert len(pipeline.steps) == 5
    assert pipeline.pipeline_id == "zero_trust_microsegmentation_pipeline_01"

    # Verify each step configuration
    step_ids = [s.step_id for s in pipeline.steps]
    assert step_ids == [
        "step_1_topology",
        "step_2_blast_radius_analysis",
        "step_3_export_telemetry_json",
        "step_4_active_remediation_test",
        "step_5_synthesize_containment_report"
    ]

    # Mock responses for coder and general specialists
    coder_step1_code = """
import networkx as nx
G = nx.DiGraph()
nodes = [
    'EDGE_ROUTER', 'REPO_MIRROR_01', 'AUTH_PROXY', 'API_GW',
    'INGRESS_CTRL', 'AUTH_SVC', 'PAYMENT_SVC', 'ORDER_SVC', 'INVENTORY_SVC',
    'REDIS_CACHE', 'ORDER_DB_PRIMARY', 'ORDER_DB_REPLICA', 'VAULT_SECRET_SRV',
    'BASTION_HOST', 'CI_CD_RUNNER', 'AUDIT_LOG_SRV'
]
G.add_nodes_from(nodes)
G.add_edge('REPO_MIRROR_01', 'CI_CD_RUNNER')
G.add_edge('CI_CD_RUNNER', 'PAYMENT_SVC')
G.add_edge('PAYMENT_SVC', 'VAULT_SECRET_SRV')
G.add_edge('CI_CD_RUNNER', 'ORDER_SVC')
G.add_edge('ORDER_SVC', 'ORDER_DB_PRIMARY')
G.add_edge('ORDER_DB_PRIMARY', 'ORDER_DB_REPLICA')
G.add_edge('INGRESS_CTRL', 'AUTH_SVC')
G.add_edge('AUTH_SVC', 'REDIS_CACHE')
G.add_edge('BASTION_HOST', 'AUDIT_LOG_SRV')
print(f"Topology built with {len(G.nodes)} nodes")
"""
    coder_step2_code = """
sp = nx.shortest_path(G, 'REPO_MIRROR_01', 'VAULT_SECRET_SRV')
desc = nx.descendants(G, 'REPO_MIRROR_01')
anc = nx.ancestors(G, 'VAULT_SECRET_SRV')
supply_chain_analysis = {
    'shortest_path': sp,
    'hops': len(sp) - 1,
    'descendants': sorted(list(desc)),
    'ancestors': sorted(list(anc)),
    'choke_point': 'CI_CD_RUNNER'
}
print(supply_chain_analysis)
"""
    coder_step4_code = """
G_isolated = nx.DiGraph()
G_isolated.add_nodes_from(G.nodes)
for u, v in G.edges():
    if u != 'CI_CD_RUNNER' and v != 'CI_CD_RUNNER':
        G_isolated.add_edge(u, v)

path_blocked = not nx.has_path(G_isolated, 'REPO_MIRROR_01', 'VAULT_SECRET_SRV')
containment_verified = path_blocked
isolation_telemetry = {
    'path_blocked': path_blocked,
    'isolated_choke_point': 'CI_CD_RUNNER',
    'remaining_reachable_nodes': sorted(list(nx.descendants(G_isolated, 'REPO_MIRROR_01')))
}
print(isolation_telemetry)
"""
    report_content = """# Zero-Trust Containment Report
## Incident Overview
- **Incident ID:** #INC-9940
- **Threat Actor:** APT-29-UNC
- **Compromised Source:** REPO_MIRROR_01
- **Crown Jewel Target:** VAULT_SECRET_SRV

## Attack Path Analysis
Shortest Path: REPO_MIRROR_01 -> CI_CD_RUNNER -> PAYMENT_SVC -> VAULT_SECRET_SRV (3 hops)

## Blast Radius Nodes
- CI_CD_RUNNER
- PAYMENT_SVC
- VAULT_SECRET_SRV
- ORDER_SVC
- ORDER_DB_PRIMARY
- ORDER_DB_REPLICA

## Microsegmentation Isolation Policy
Isolate choke point `CI_CD_RUNNER` to sever downstream egress to production database and vault services.
"""

    mock_llm = MockLLMClient([
        # Step 1
        f'{{"thought": "build graph", "action": {{"tool": "python_repl", "args": {{"code": {json.dumps(coder_step1_code)}}}}}, "final_answer": null}}',
        '{"thought": "step 1 done", "action": null, "final_answer": "Built 16-node topology"}',
        # Step 2
        f'{{"thought": "calc attack path", "action": {{"tool": "python_repl", "args": {{"code": {json.dumps(coder_step2_code)}}}}}, "final_answer": null}}',
        '{"thought": "step 2 done", "action": null, "final_answer": "Attack path analysis complete"}',
        # Step 4
        f'{{"thought": "isolate choke point", "action": {{"tool": "python_repl", "args": {{"code": {json.dumps(coder_step4_code)}}}}}, "final_answer": null}}',
        '{"thought": "step 4 done", "action": null, "final_answer": "Isolation containment verified"}',
        # Step 5
        '{"thought": "read telemetry", "action": {"tool": "read_file", "args": {"path": "supply_chain_audit.json"}}, "final_answer": null}',
        f'{{"thought": "write report", "action": {{"tool": "write_file", "args": {{"path": "zero_trust_containment_report.md", "content": {json.dumps(report_content)}}}}}, "final_answer": null}}',
        '{"thought": "step 5 done", "action": null, "final_answer": "Synthesized zero-trust report"}'
    ])

    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            runner = StructuredPipelineRunner(
                llm_client=mock_llm,
                workspace_dir=tmpdir,
                verbose=False
            )
            res = runner.run(pipeline, approval_callback=lambda _tool, _args: True)
            assert res.success is True
            assert res.steps_passed == 5
            assert os.path.exists(os.path.join(tmpdir, "supply_chain_audit.json"))
            assert os.path.exists(os.path.join(tmpdir, "zero_trust_containment_report.md"))
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws


def test_pipeline_step_max_steps_custom_budget():
    """Verify that PipelineStep with custom max_steps parses and is passed to specialist."""
    step = PipelineStep.from_dict({
        "step_id": "step_budget",
        "objective": "Test custom budget",
        "specialist": "coder",
        "max_steps": 15
    })
    assert step.max_steps == 15


def test_pipeline_deadline_caps_provider_and_reports_timeout():
    pipeline = StructuredPipeline(
        pipeline_id="p_deadline",
        title="Deadline Test",
        max_time_seconds=0.03,
        max_steps=5,
        steps=[PipelineStep(step_id="slow", objective="Wait", specialist="coder", max_retries=2, max_steps=3)],
    )
    llm = DeadlineAwareSlowLLM()
    runner = StructuredPipelineRunner(llm_client=llm, verbose=False)
    started = time.monotonic()
    result = runner.run(pipeline, approval_callback=lambda _tool, _args: True)

    assert time.monotonic() - started < 0.25
    assert result.success is False
    assert result.step_telemetry[0].status == "timed_out"
    assert llm.timeouts and llm.timeouts[0] <= 0.03


def test_pipeline_resume_restores_declared_repl_state():
    from tools.external_tools import reset_repl_globals

    first_step_code = "resume_value = 42\nprint(resume_value)"
    second_step_code = "resume_result = resume_value + 1\nprint(resume_result)"
    pipeline = StructuredPipeline(
        pipeline_id="p_resume",
        title="Resume Test",
        max_steps=10,
        steps=[
            PipelineStep(
                step_id="seed",
                objective="Create resume_value",
                specialist="coder",
                state_exports=["resume_value"],
                verification_criteria=[{"type": "repl_variable", "variable": "resume_value", "assertion": "resume_value == 42"}],
            ),
            PipelineStep(
                step_id="consume",
                objective="Create resume_result",
                specialist="coder",
                verification_criteria=[{"type": "repl_variable", "variable": "resume_result", "assertion": "resume_result == 43"}],
            ),
        ],
    )
    first_responses = [
        json.dumps({"thought": "seed", "action": {"tool": "python_repl", "args": {"code": first_step_code}}, "final_answer": None}),
        json.dumps({"thought": "done", "action": None, "final_answer": "seeded"}),
        json.dumps({"thought": "stop", "action": None, "final_answer": "not yet"}),
    ]
    resumed_responses = [
        json.dumps({"thought": "consume", "action": {"tool": "python_repl", "args": {"code": second_step_code}}, "final_answer": None}),
        json.dumps({"thought": "done", "action": None, "final_answer": "consumed"}),
    ]

    reset_repl_globals()
    with tempfile.TemporaryDirectory() as tmpdir:
        initial = StructuredPipelineRunner(llm_client=MockLLMClient(first_responses), workspace_dir=tmpdir, verbose=False)
        failed = initial.run(pipeline, approval_callback=lambda _tool, _args: True)
        assert failed.success is False
        assert os.path.exists(os.path.join(tmpdir, ".pipeline_checkpoints", "p_resume.json"))

        reset_repl_globals()
        resumed = StructuredPipelineRunner(llm_client=MockLLMClient(resumed_responses), workspace_dir=tmpdir, verbose=False)
        result = resumed.run(pipeline, approval_callback=lambda _tool, _args: True, resume=True)

    assert result.success is True
    assert result.steps_passed == 2
    assert result.step_telemetry[0].status == "resumed"
