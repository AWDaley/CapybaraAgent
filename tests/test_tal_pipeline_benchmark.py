"""Paired execution MUST use one checked-in pipeline and fail closed on REPL."""

import json

import pytest

from llm_client import LLMClient
from tal.benchmark import BenchmarkSuite, SLMBenchmarkRunner
from tal.pipeline_benchmark import load_pipeline_fixture, pipeline_blocker
from tal_test_runner import TALTestRunner


class _NoModelCalls(LLMClient):
    def __init__(self):
        super().__init__(model="qwen3.5:4b")
        self.calls = 0

    def generate(self, messages, json_mode=False, **kwargs):
        self.calls += 1
        raise AssertionError("No model calls expected for safe harness or preflight-denied pipeline")

    @classmethod
    def list_models(cls):
        return []


def test_safe_two_step_pipeline_runs_in_both_arms_and_collects_result(tmp_path):
    client = _NoModelCalls()
    runner = TALTestRunner(client, storage_dir=str(tmp_path), mode="react")
    result = runner.run_pipeline_test(
        "Run fixed offline smoke pipeline",
        pipeline_fixture="data/benchmark_safe_pipeline.json",
        artifact_paths=("receipt.json", "proof.txt"),
        seed=73,
    )
    assert result.mode == "pipeline"
    assert client.calls == 0
    for metrics, is_tal in [(result.baseline, False), (result.tal, True)]:
        assert metrics.success is True
        assert metrics.execution_supported is True
        assert metrics.tal_enabled is is_tal
        assert metrics.llm_calls == 0
        assert metrics.tool_call_count == 0
        assert metrics.verification_passed is True
        assert set(metrics.observed_artifacts) == {"receipt.json", "proof.txt"}
        receipt = json.loads(metrics.observed_artifacts["receipt.json"]["content"])
        assert receipt == {"status": "ready", "value": 42}
        assert "proof.txt" in metrics.final_answer
    assert result.baseline.observed_artifacts["receipt.json"]["sha256"] == result.tal.observed_artifacts["receipt.json"]["sha256"]


def test_endurance_saga_is_reported_unsupported_before_model_execution(tmp_path):
    client = _NoModelCalls()
    pipeline = load_pipeline_fixture("data/distributed_saga_recovery_pipeline.json")
    reason = pipeline_blocker(pipeline)
    assert reason and "python_repl" in reason
    runner = TALTestRunner(client, storage_dir=str(tmp_path))
    result = runner.run_pipeline_test(
        "Perform distributed saga",
        pipeline_fixture="data/distributed_saga_recovery_pipeline.json",
    )
    assert not result.baseline.success and not result.tal.success
    assert result.baseline.execution_supported is False
    assert result.tal.execution_supported is False
    assert result.baseline.outcome == "unsupported"
    assert "python_repl" in result.tal.unsupported_reason
    assert client.calls == 0


@pytest.mark.parametrize("path", [
    "../outside.json", "data/../unsafe.json", "data/fixture.py",
    "/tmp/pipeline.json", "data/test name.json", "data/a/b.json",
])
def test_pipeline_fixture_rejects_path_escape_and_unsupported_extensions(path):
    with pytest.raises(ValueError):
        load_pipeline_fixture(path)


def test_v3_suite_routes_only_saga_through_fixed_pipeline(tmp_path):
    client = _NoModelCalls()
    v3 = BenchmarkSuite.from_dict(json.load(open("benchmarks/slm_v3.json", encoding="utf-8")))
    assert v3.version == "v3"
    assert len(v3.cases) == 5
    assert sum(bool(case.pipeline_fixture) for case in v3.cases) == 2
    smoke = next(case for case in v3.cases if case.case_id == "fixed_pipeline_harness_smoke")
    saga = next(case for case in v3.cases if case.case_id == "distributed_saga_recovery")
    assert smoke.pipeline_fixture == "data/benchmark_safe_pipeline.json"
    assert saga.pipeline_fixture == "data/distributed_saga_recovery_pipeline.json"

    # Exercise only the fixed harness/saga fixtures: other cases require an
    # actual SLM and should not be substituted with this scripted mock.
    two_case_suite = BenchmarkSuite.from_dict({
        "suite_id": "pipeline_only", "version": "v1",
        "description": "Two benchmark pipeline routes",
        "cases": [smoke.to_dict(), saga.to_dict()],
    })
    scorecard = SLMBenchmarkRunner(
        TALTestRunner(client, storage_dir=str(tmp_path)),
    ).run(two_case_suite, repetitions=1, seed=13)
    assert scorecard.mode == "pipeline"
    trials = {trial.case_id: trial for trial in scorecard.trials}
    assert len(trials["fixed_pipeline_harness_smoke"].pipeline_sha256) == 64
    assert len(trials["distributed_saga_recovery"].pipeline_sha256) == 64
    assert trials["fixed_pipeline_harness_smoke"].pipeline_sha256 != trials["distributed_saga_recovery"].pipeline_sha256
    assert trials["fixed_pipeline_harness_smoke"].baseline_oracle_passed is True
    assert trials["fixed_pipeline_harness_smoke"].tal_oracle_passed is True
    assert trials["distributed_saga_recovery"].baseline_oracle_passed is None
    assert trials["distributed_saga_recovery"].tal_oracle_passed is None
    summary = scorecard.summary()["overall"]
    assert summary["trials"] == 2
    assert summary["scored_trials"] == 1
    assert summary["unsupported_trials"] == 1
    assert summary["unscored_trials"] == 1
    assert summary["tal_verified_success_rate"] == 1.0
    assert client.calls == 0


def test_case_rejects_unregistered_or_nonsensical_pipeline_reference():
    with pytest.raises(ValueError, match="pipeline_fixture"):
        BenchmarkSuite.from_dict({
            "suite_id": "bad", "version": "v1", "description": "bad fixture",
            "cases": [{
                "case_id": "bad", "category": "bad", "difficulty": "easy",
                "prompt": "bad", "pipeline_fixture": "../../workspace/private.json",
            }],
        })
