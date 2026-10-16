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
from tal_test_report import RunMetrics, TALTestResult
from tal_test_runner import TALTestRunner


_VALID_DIFFICULTIES = {"easy", "medium", "hard", "endurance"}


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_") or "suite"


@dataclass(frozen=True)
class AcceptanceOracle:
    """Minimal deterministic benchmark oracle independent of agent self-reports.

    A tool check matches the OBSERVED tool result, not model assertions about
    tool use. Cases without a machine-checkable oracle are unscored.
    """

    final_contains_all: tuple[str, ...] = ()
    tool_observations: tuple[tuple[str, str], ...] = ()
    state_equals: dict[str, Any] = field(default_factory=dict)
    artifact_verifier: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AcceptanceOracle":
        if not isinstance(raw, dict):
            raise ValueError("Benchmark oracle must be a JSON object")
        unexpected = set(raw) - {
            "final_contains_all", "tool_observations", "state_equals", "artifact_verifier",
        }
        if unexpected:
            raise ValueError(f"Benchmark oracle has unsupported fields: {sorted(unexpected)}")
        final = raw.get("final_contains_all", [])
        observations = raw.get("tool_observations", [])
        if not isinstance(final, list) or not all(isinstance(x, str) and x for x in final):
            raise ValueError("oracle.final_contains_all must be a list of non-empty strings")
        if not isinstance(observations, list) or not all(
            isinstance(item, dict)
            and set(item) == {"tool", "contains"}
            and all(isinstance(item[key], str) and item[key] for key in ("tool", "contains"))
            for item in observations
        ):
            raise ValueError("oracle.tool_observations must contain exact tool/contains objects")
        state = raw.get("state_equals", {})
        if not isinstance(state, dict) or len(state) > 16 or not all(
            isinstance(key, str) and key.isidentifier() for key in state
        ):
            raise ValueError("oracle.state_equals must map variable identifiers to expected JSON values")
        # JSON roundtrip enforces size, simple serializable observations, and
        # forbids NaN/Infinity and arbitrary executable expressions.
        try:
            state_json = _canonical_json(state)
            if len(state_json) > 65536:
                raise ValueError("oracle.state_equals exceeds bounded JSON size")
            state = json.loads(state_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("oracle.state_equals must be JSON-compatible") from exc
        verifier = raw.get("artifact_verifier")
        if verifier not in (None, "distributed_saga_v1"):
            raise ValueError("Unknown independent artifact verifier")
        if not final and not observations and not state and verifier is None:
            raise ValueError("Benchmark oracle must specify at least one independent check")
        return cls(
            final_contains_all=tuple(final),
            tool_observations=tuple((item["tool"], item["contains"]) for item in observations),
            state_equals=state,
            artifact_verifier=verifier,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_contains_all": list(self.final_contains_all),
            "tool_observations": [
                {"tool": tool, "contains": expected}
                for tool, expected in self.tool_observations
            ],
            **({"state_equals": self.state_equals} if self.state_equals else {}),
            **({"artifact_verifier": self.artifact_verifier} if self.artifact_verifier else {}),
        }

    def evaluate(self, run: RunMetrics) -> bool:
        if not run.success or run.error:
            return False
        answer = str(run.final_answer or "")
        if any(expected not in answer for expected in self.final_contains_all):
            return False
        for tool, expected in self.tool_observations:
            matched = False
            for observation in run.tools_called:
                name = str(observation.get("tool", "")).rsplit("] ", 1)[-1]
                result = str(observation.get("result", ""))
                if (
                    name == tool
                    and expected in result
                    and not result.lstrip().lower().startswith("error")
                    and "DENIED" not in result
                ):
                    matched = True
                    break
            if not matched:
                return False
        for key, expected in self.state_equals.items():
            if key not in run.observed_state or run.observed_state[key] != expected:
                return False
        if self.artifact_verifier is not None:
            from tal.benchmark_evidence import verify_distributed_saga
            if not verify_distributed_saga(run.observed_artifacts):
                return False
        return True


@dataclass(frozen=True)
class BenchmarkCase:
    """One immutable prompt-oriented benchmark case."""

    case_id: str
    category: str
    difficulty: str
    prompt: str
    acceptance: str = ""
    tags: tuple[str, ...] = ()
    oracle: AcceptanceOracle | None = None

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
            oracle=AcceptanceOracle.from_dict(data["oracle"]) if "oracle" in data else None,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        if self.oracle is None:
            data.pop("oracle")
        else:
            data["oracle"] = self.oracle.to_dict()
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
    baseline_oracle_passed: bool | None = None
    tal_oracle_passed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "difficulty": self.difficulty,
            "repetition": self.repetition,
            "seed": self.seed,
            "result": self.result.to_dict(),
            "baseline_oracle_passed": self.baseline_oracle_passed,
            "tal_oracle_passed": self.tal_oracle_passed,
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
            baseline_success = [
                item.baseline_oracle_passed for item in items
                if item.baseline_oracle_passed is not None
            ]
            tal_success = [
                item.tal_oracle_passed for item in items
                if item.tal_oracle_passed is not None
            ]
            scorable = len(tal_success)
            total_tool_calls = sum(item.result.tal.tool_call_count for item in items)
            total_tool_errors = sum(item.result.tal.tool_error_count for item in items)
            return {
                "trials": len(items),
                "scored_trials": scorable,
                "unscored_trials": len(items) - scorable,
                "oracle_coverage": round(scorable / len(items), 4) if items else 0.0,
                # Never silently count a prose-only acceptance description as a
                # machine-verified failure (or a machine-verified success).
                "baseline_verified_success_rate": _rate(baseline_success) if scorable else None,
                "tal_verified_success_rate": _rate(tal_success) if scorable else None,
                "baseline_agent_reported_verified_rate": _rate([
                    item.result.baseline.outcome == "verified" for item in items
                ]),
                "tal_agent_reported_verified_rate": _rate([
                    item.result.tal.outcome == "verified" for item in items
                ]),
                "baseline_median_tokens": _median([item.result.baseline.total_tokens for item in items]),
                "tal_median_tokens": _median([item.result.tal.total_tokens for item in items]),
                "baseline_median_wall_seconds": _median([item.result.baseline.wall_clock_time for item in items]),
                "tal_median_wall_seconds": _median([item.result.tal.wall_clock_time for item in items]),
                "tal_tool_error_rate": round(total_tool_errors / total_tool_calls, 4) if total_tool_calls else 0.0,
                "tal_zero_tool_error_run_rate": _rate([item.result.tal.tool_error_count == 0 for item in items]),
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
            result = self.test_runner.run_single_test(
                case.prompt, seed=trial_seed,
                evidence_keys=tuple(case.oracle.state_equals) if case.oracle else (),
                artifact_paths=(
                    ("saga_execution_audit.json", "saga_release_manifest.json", "saga_execution_report.md")
                    if case.oracle and case.oracle.artifact_verifier == "distributed_saga_v1"
                    else ()
                ),
            )
            scorecard.trials.append(BenchmarkTrial(
                case_id=case.case_id,
                category=case.category,
                difficulty=case.difficulty,
                repetition=repetition,
                seed=trial_seed,
                result=result,
                baseline_oracle_passed=(
                    case.oracle.evaluate(result.baseline) if case.oracle else None
                ),
                tal_oracle_passed=(
                    case.oracle.evaluate(result.tal) if case.oracle else None
                ),
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
