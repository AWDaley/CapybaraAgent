import json
import shutil
import tempfile

import pytest

from llm_client import LLMClient
from tal.benchmark import (
    BenchmarkSuite,
    SLMBenchmarkRunner,
    load_benchmark_suite,
    save_scorecard,
)
from tal_test_runner import TALTestRunner


class _BenchmarkLLM(LLMClient):
    def __init__(self):
        super().__init__("qwen3.5:4b")

    def generate(self, messages, json_mode=False, timeout_seconds=None):
        return '{"thought":"done","action":null,"final_answer":"done"}'

    @classmethod
    def list_models(cls):
        return []


def test_load_versioned_slm_suite_contains_regression_case():
    suite = load_benchmark_suite("benchmarks/slm_v1.json")

    assert suite.suite_id == "capybara_slm_core"
    assert suite.version == "v1"
    assert suite.fingerprint
    assert any(case.case_id == "distributed_saga_recovery" for case in suite.cases)
    assert {case.difficulty for case in suite.cases} == {"easy", "medium", "hard", "endurance"}


def test_suite_rejects_invalid_or_duplicate_cases():
    with pytest.raises(ValueError, match="unique"):
        BenchmarkSuite.from_dict({
            "suite_id": "test",
            "version": "v1",
            "description": "test suite",
            "cases": [
                {"case_id": "same", "category": "x", "difficulty": "easy", "prompt": "one"},
                {"case_id": "same", "category": "x", "difficulty": "easy", "prompt": "two"},
            ],
        })


def test_scorecard_is_reproducible_and_persisted():
    suite = BenchmarkSuite.from_dict({
        "suite_id": "tiny",
        "version": "v1",
        "description": "test suite",
        "cases": [
            {"case_id": "one", "category": "test", "difficulty": "easy", "prompt": "Answer hello."},
            {"case_id": "two", "category": "test", "difficulty": "medium", "prompt": "Answer goodbye."},
        ],
    })
    directory = tempfile.mkdtemp(prefix="capy_benchmark_")
    try:
        runner = TALTestRunner(_BenchmarkLLM(), storage_dir=directory, max_steps=1)
        scorecard = SLMBenchmarkRunner(runner).run(suite, repetitions=2, seed=7)
        result_path = save_scorecard(scorecard, directory)

        with open(result_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        assert len(scorecard.trials) == 4
        assert saved["suite_fingerprint"] == suite.fingerprint
        assert saved["summary"]["overall"]["trials"] == 4
        assert set(saved["summary"]["by_difficulty"]) == {"easy", "medium"}
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_slm_benchmark_rejects_non_slm_model():
    runner = TALTestRunner(_BenchmarkLLM())
    runner.llm_client.model = "frontier-pro"
    suite = BenchmarkSuite.from_dict({
        "suite_id": "tiny",
        "version": "v1",
        "description": "test suite",
        "cases": [{"case_id": "one", "category": "test", "difficulty": "easy", "prompt": "hello"}],
    })

    with pytest.raises(ValueError, match="requires an SLM"):
        SLMBenchmarkRunner(runner).run(suite)


def test_oracle_rejects_unobserved_tool_use_and_wrong_answers():
    from tal.benchmark import AcceptanceOracle
    from tal_test_report import RunMetrics

    oracle = AcceptanceOracle.from_dict({
        "final_contains_all": ["6713"],
        "tool_observations": [{"tool": "calc", "contains": "6713"}],
    })
    assert oracle.evaluate(RunMetrics(
        success=True, final_answer="The result is 6713",
        tools_called=[{"tool": "calc", "result": "6713"}],
    ))
    assert not oracle.evaluate(RunMetrics(success=True, final_answer="6713"))
    assert not oracle.evaluate(RunMetrics(
        success=True, final_answer="6713",
        tools_called=[{"tool": "calc", "result": "Error: refused 6713"}],
    ))
    assert not oracle.evaluate(RunMetrics(
        success=True, final_answer="6712",
        tools_called=[{"tool": "calc", "result": "6713"}],
    ))


def test_oracle_requires_real_checks_not_prose_only():
    from tal.benchmark import AcceptanceOracle

    with pytest.raises(ValueError, match="at least one"):
        AcceptanceOracle.from_dict({})
    with pytest.raises(ValueError, match="unsupported fields"):
        AcceptanceOracle.from_dict({"pass": True})
    suite = load_benchmark_suite("benchmarks/slm_v1.json")
    calc = next(item for item in suite.cases if item.case_id == "deterministic_calculation")
    assert calc.oracle is not None
    assert calc.to_dict()["oracle"]["final_contains_all"] == ["6713"]


def test_unscored_cases_are_excluded_not_counted_as_failures():
    from tal.benchmark import BenchmarkScorecard, BenchmarkTrial
    from tal_test_report import TALTestResult, RunMetrics

    result = TALTestResult(
        prompt="hello",
        baseline=RunMetrics(success=True, outcome="completed_unverified"),
        tal=RunMetrics(success=True, outcome="completed_unverified"),
    )
    score = BenchmarkScorecard(
        suite_id="test", suite_version="1", suite_fingerprint="f",
        model="slm", provider="local", mode="react", seed=1, repetitions=1,
        trials=[BenchmarkTrial("one", "test", "easy", 0, None, result)],
    )
    overall = score.summary()["overall"]
    assert overall["scored_trials"] == 0
    assert overall["unscored_trials"] == 1
    assert overall["baseline_verified_success_rate"] is None
    assert overall["tal_verified_success_rate"] is None
