"""Versioned, reproducible benchmark support for SLM-first Capybara runs.

The benchmark layer intentionally measures verified outcomes from the existing
TAL test runner.  It is model-agnostic at the storage level, but production
callers may require an SLM model name before a suite is executed.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import random
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from tal.slm_profile import is_slm_model
from tal_test_report import TALTestResult
from tal_test_runner import TALTestRunner


_VALID_DIFFICULTIES = {"easy", "medium", "hard", "endurance"}


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_") or "suite"


@dataclass(frozen=True)
class BenchmarkCase:
    """One immutable prompt-oriented benchmark case."""

    case_id: str
    category: str
    difficulty: str
    prompt: str
    acceptance: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkCase":
        required = ("case_id", "category", "difficulty", "prompt")
        missing = [name for name in required if not str(data.get(name, "")).strip()]
        if missing:
            raise ValueError(f"Benchmark case is missing required fields: {', '.join(missing)}")
        difficulty = str(data["difficulty"]).lower()
        if difficulty not in _VALID_DIFFICULTIES:
            raise ValueError(f"Unknown benchmark difficulty '{difficulty}'")
        raw_tags = data.get("tags", [])
        if not isinstance(raw_tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in raw_tags):
            raise ValueError("Benchmark case tags must be a list of non-empty strings")
        return cls(
            case_id=str(data["case_id"]),
            category=str(data["category"]),
            difficulty=difficulty,
            prompt=str(data["prompt"]),
            acceptance=str(data.get("acceptance", "")),
            tags=tuple(raw_tags),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data


@dataclass(frozen=True)
class BenchmarkSuite:
    """A versioned, immutable collection of benchmark cases."""

    suite_id: str
    version: str
    description: str
    cases: tuple[BenchmarkCase, ...]
    source_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: str = "") -> "BenchmarkSuite":
        suite_id = str(data.get("suite_id", "")).strip()
        version = str(data.get("version", "")).strip()
        description = str(data.get("description", "")).strip()
        raw_cases = data.get("cases")
        if not suite_id or not version or not description:
            raise ValueError("Benchmark suite requires suite_id, version, and description")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError("Benchmark suite requires a non-empty cases list")
        cases = tuple(BenchmarkCase.from_dict(item) for item in raw_cases if isinstance(item, dict))
        if len(cases) != len(raw_cases):
            raise ValueError("Every benchmark case must be an object")
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Benchmark case IDs must be unique")
        return cls(suite_id=suite_id, version=version, description=description, cases=cases, source_path=source_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "version": self.version,
            "description": self.description,
            "cases": [case.to_dict() for case in self.cases],
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


def load_benchmark_suite(path: str) -> BenchmarkSuite:
    """Load and validate a versioned suite file without executing it."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Benchmark suite must be a JSON object")
    return BenchmarkSuite.from_dict(raw, source_path=os.path.abspath(path))


@dataclass(frozen=True)
class BenchmarkTrial:
    case_id: str
    category: str
    difficulty: str
    repetition: int
    seed: int | None
    result: TALTestResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "difficulty": self.difficulty,
            "repetition": self.repetition,
            "seed": self.seed,
            "result": self.result.to_dict(),
        }


def _rate(results: list[bool]) -> float:
    return round(sum(results) / len(results), 4) if results else 0.0


@dataclass
class BenchmarkScorecard:
    suite_id: str
    suite_version: str
    suite_fingerprint: str
    model: str
    provider: str
    mode: str
    seed: int | None
    repetitions: int
    created_at: str = field(default_factory=lambda: _datetime.datetime.now(_datetime.timezone.utc).isoformat())
    trials: list[BenchmarkTrial] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        def summarize(items: list[BenchmarkTrial]) -> dict[str, Any]:
            baseline_success = [item.result.baseline.success for item in items]
            tal_success = [item.result.tal.success for item in items]
            return {
                "trials": len(items),
                "baseline_verified_success_rate": _rate(baseline_success),
                "tal_verified_success_rate": _rate(tal_success),
                "baseline_median_tokens": _median([item.result.baseline.total_tokens for item in items]),
                "tal_median_tokens": _median([item.result.tal.total_tokens for item in items]),
                "baseline_median_wall_seconds": _median([item.result.baseline.wall_clock_time for item in items]),
                "tal_median_wall_seconds": _median([item.result.tal.wall_clock_time for item in items]),
                "tal_tool_error_rate": _rate([item.result.tal.tool_error_count == 0 for item in items]),
                "tal_verification_rate": _rate([item.result.tal.verification_passed is True for item in items]),
            }

        by_category: dict[str, list[BenchmarkTrial]] = {}
        by_difficulty: dict[str, list[BenchmarkTrial]] = {}
        for trial in self.trials:
            by_category.setdefault(trial.category, []).append(trial)
            by_difficulty.setdefault(trial.difficulty, []).append(trial)
        return {
            "overall": summarize(self.trials),
            "by_category": {key: summarize(value) for key, value in sorted(by_category.items())},
            "by_difficulty": {key: summarize(value) for key, value in sorted(by_difficulty.items())},
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "suite_fingerprint": self.suite_fingerprint,
            "model": self.model,
            "provider": self.provider,
            "mode": self.mode,
            "seed": self.seed,
            "repetitions": self.repetitions,
            "created_at": self.created_at,
            "summary": self.summary(),
            "trials": [trial.to_dict() for trial in self.trials],
        }


def _median(values: list[int | float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return round((ordered[middle - 1] + ordered[middle]) / 2, 4)


class SLMBenchmarkRunner:
    """Execute a benchmark suite with deterministic trial order and scorecards."""

    def __init__(self, test_runner: TALTestRunner, require_slm: bool = True):
        self.test_runner = test_runner
        self.require_slm = require_slm

    def run(self, suite: BenchmarkSuite, repetitions: int = 1, seed: int | None = None) -> BenchmarkScorecard:
        if repetitions < 1:
            raise ValueError("repetitions must be at least one")
        model = str(getattr(self.test_runner.llm_client, "model", "unknown"))
        if self.require_slm and not is_slm_model(model):
            raise ValueError(f"SLM benchmark requires an SLM model, received '{model}'")

        trials = [(case, repetition) for repetition in range(repetitions) for case in suite.cases]
        rng = random.Random(seed)
        if seed is not None:
            rng.shuffle(trials)

        scorecard = BenchmarkScorecard(
            suite_id=suite.suite_id,
            suite_version=suite.version,
            suite_fingerprint=suite.fingerprint,
            model=model,
            provider=self.test_runner.llm_client.__class__.__name__.replace("Provider", "").replace("Client", "").lower(),
            mode=self.test_runner.mode,
            seed=seed,
            repetitions=repetitions,
        )
        for case, repetition in trials:
            trial_seed = rng.randrange(2**32) if seed is not None else None
            result = self.test_runner.run_single_test(case.prompt, seed=trial_seed)
            scorecard.trials.append(BenchmarkTrial(
                case_id=case.case_id,
                category=case.category,
                difficulty=case.difficulty,
                repetition=repetition,
                seed=trial_seed,
                result=result,
            ))
        return scorecard


def save_scorecard(scorecard: BenchmarkScorecard, storage_dir: str) -> str:
    """Atomically write a machine-readable scorecard and return its path."""
    os.makedirs(storage_dir, exist_ok=True)
    stamp = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%d_%H-%M-%SZ")
    filename = f"{_slug(scorecard.suite_id)}_{scorecard.suite_version}_{stamp}.json"
    path = os.path.join(storage_dir, filename)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(scorecard.to_dict(), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temporary, path)
    return path
