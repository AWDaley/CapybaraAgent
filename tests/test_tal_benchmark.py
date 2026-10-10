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
