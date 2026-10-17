"""Paired fixed-pipeline evaluations with explicit capability negotiation.

The baseline and TAL arms use the same versioned deterministic pipeline
definition. Model output never gets to invent the benchmark's pipeline, test
oracle, or a host execution capability. Unsupported stateful runtimes are
recorded as UNAVAILABLE (and excluded from the score denominator).
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any

from tal.benchmark_evidence import collect_benchmark_evidence
from tal.effect_classes import EffectClass, get_effect_class
from tal.pipeline_runner import StructuredPipelineRunner
from tal.schemas import StructuredPipeline
from tal_test_report import RunMetrics, TALTestResult, save_test_result
from tools import TOOL_REGISTRY

# No host subprocess, network, global knowledge store, or persistent REPL.
_ALLOWED_BENCHMARK_TOOLS = frozenset({
    "calc", "count words", "convert units", "read_file", "list_files", "write_file",
})
_ALLOWED_CHECKS = frozenset({
    "file_exists", "json_schema", "ast_syntax", "python_syntax",
    "cross_entity", "cross_reference", "cross_entity_consistency",
    "regex_match", "non_empty",
})
_ALLOWED_OUTPUT_SPECS = frozenset({"text", "raw", "template"})
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_pipeline_fixture(reference: str) -> StructuredPipeline:
    """Resolve a named, checked-in fixture; reject arbitrary filesystem paths."""
    if not isinstance(reference, str) or not re.fullmatch(r"data/[a-z0-9_-]+\.json", reference):
        raise ValueError("Pipeline benchmark fixture must be inside data/*.json")
    root = (_PROJECT_ROOT / "data").resolve()
    target = (_PROJECT_ROOT / reference).resolve()
    if target.parent != root or not target.is_file() or target.stat().st_size > 512 * 1024:
        raise ValueError("Pipeline benchmark fixture must be a local, bounded data/*.json file")
    with target.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    return StructuredPipeline.from_dict(payload)


def _has_runtime_expressions(value: Any) -> bool:
    if isinstance(value, str):
        return "$eval" in value or "${eval:" in value
    if isinstance(value, (tuple, list)):
        return any(_has_runtime_expressions(item) for item in value)
    if isinstance(value, dict):
        return any(_has_runtime_expressions(item) for item in value.values())
    return False


def pipeline_blocker(pipeline: StructuredPipeline) -> str | None:
    """Preflight all stages before any model call or side effect occurs."""
    for step in pipeline.steps:
        prefix = f"Step {step.step_id}: "
        if step.specialist.lower() not in {"harness", "system", "deterministic"}:
            if step.tool_allowlist is None:
                return prefix + "explicit tool_allowlist is required for a paired benchmark"
            missing = set(step.tool_allowlist) - _ALLOWED_BENCHMARK_TOOLS
            if missing:
                return prefix + f"unsupported capabilities {', '.join(sorted(missing))}; no stateful isolated REPL backend"
        if not step.verification_criteria:
            return prefix + "independent step verification is required"
        for criterion in step.verification_criteria:
            if not isinstance(criterion, dict) or criterion.get("type") not in _ALLOWED_CHECKS:
                return prefix + "unsupported verification criteria require an isolated stateful worker"
        spec = step.output_spec
        if spec is not None:
            if spec.spec_type not in _ALLOWED_OUTPUT_SPECS or _has_runtime_expressions(spec.template):
                return prefix + "runtime-driven output materialization requires an isolated stateful worker"
    return None


def _restricted_registry() -> dict:
    return {
        name: TOOL_REGISTRY[name]
        for name in _ALLOWED_BENCHMARK_TOOLS
        if name in TOOL_REGISTRY
        and get_effect_class(name) in {EffectClass.READ, EffectClass.WRITE}
    }


def _unsupported(reason: str, tal_mode: bool) -> RunMetrics:
    return RunMetrics(
        mode="pipeline", tal_enabled=tal_mode, success=False,
        outcome="unsupported", execution_supported=False,
        unsupported_reason=reason,
    )


def _run_arm(
    test_runner: Any, pipeline: StructuredPipeline,
    tal_mode: bool,
    evidence_keys: tuple[str, ...],
    artifact_paths: tuple[str, ...],
) -> RunMetrics:
    from tal_test_runner import TrackingLLMClient, sandbox_workspace

    tracker = TrackingLLMClient(test_runner.llm_client)
    started = time.monotonic()
    with sandbox_workspace() as workspace:
        # The single registry and input pipeline are identical in both arms.
        runner = StructuredPipelineRunner(
            llm_client=tracker,
            workspace_dir=workspace,
            verbose=False,
            knowledge_store=None,
            guardrails_enabled=True,
            tal_mode=tal_mode,
            use_slm_profile=test_runner.use_slm_profile,
            tool_registry=_restricted_registry(),
            # Never accidentally inspect another invocation's global REPL.
            repl_globals_provider=lambda: {},
        )
        # Mutating workspace writes are denied; only the deterministic harness
        # may produce expected files in this known-empty trial workspace.
        try:
            result = runner.run(pipeline, approval_callback=lambda *_: False)
            observed_state, observed_artifacts = collect_benchmark_evidence(
                workspace, evidence_keys, artifact_paths,
            )
            outcome = "completed_unverified" if result.success else "failed"
            return RunMetrics(
                mode="pipeline", tal_enabled=tal_mode, success=result.success,
                error=result.error, outcome=outcome,
                final_answer=result.final_output,
                wall_clock_time=time.monotonic() - started,
                steps_taken=result.steps_consumed,
                llm_calls=tracker.llm_calls,
                input_tokens=tracker.input_tokens,
                output_tokens=tracker.output_tokens,
                total_tokens=tracker.total_tokens,
                tool_call_count=result.tool_call_count,
                tool_error_count=result.tool_error_count,
                tools_called=[dict(item) for item in result.tool_calls],
                parse_repairs=result.parse_repairs,
                verification_passed=result.success,
                verification_messages=[
                    msg for step in result.step_telemetry
                    for msg in step.verification_messages
                ],
                events_count=len(runner.event_log.events),
                observed_state=observed_state,
                observed_artifacts=observed_artifacts,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            return RunMetrics(
                mode="pipeline", tal_enabled=tal_mode, success=False,
                outcome="failed", error=f"Pipeline execution error: {exc}",
                wall_clock_time=time.monotonic() - started,
            )


def run_pipeline_pair(
    test_runner: Any, prompt: str, pipeline_fixture: str,
    *, seed: int | None = None,
    evidence_keys: tuple[str, ...] = (),
    artifact_paths: tuple[str, ...] = (),
) -> TALTestResult:
    """Run both arms with one pipeline, snapshotting evidence before cleanup."""
    pipeline = load_pipeline_fixture(pipeline_fixture)
    reason = pipeline_blocker(pipeline)
    model = getattr(test_runner.llm_client, "model", "unknown")
    provider = type(test_runner.llm_client).__name__.lower()
    if reason:
        result = TALTestResult(
            prompt=prompt, mode="pipeline", model=model, provider=provider,
            baseline=_unsupported(reason, False), tal=_unsupported(reason, True),
        )
        save_test_result(result, storage_dir=test_runner.storage_dir)
        return result

    modes = [False, True]
    if seed is not None:
        random.Random(seed).shuffle(modes)
    observed: dict[bool, RunMetrics] = {}
    for mode in modes:
        observed[mode] = _run_arm(test_runner, pipeline, mode, evidence_keys, artifact_paths)
    result = TALTestResult(
        prompt=prompt, mode="pipeline", model=model, provider=provider,
        baseline=observed[False], tal=observed[True],
    )
    save_test_result(result, storage_dir=test_runner.storage_dir)
    return result
