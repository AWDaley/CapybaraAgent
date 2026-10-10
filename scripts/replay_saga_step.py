"""Replay the first distributed-saga step against a local Ollama model.

This is a validation helper: each attempt uses a temporary workspace and REPL
scope so it cannot reuse pipeline state or leave generated artifacts behind.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from llm_client import create_llm_client
from tal.pipeline_runner import StructuredPipelineRunner
from tal.schemas import StructuredPipeline
from tools import TOOL_REGISTRY
from tools.external_tools import create_repl_scope


def run_once(model: str, timeout_seconds: float, include_details: bool = False) -> dict:
    source = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "distributed_saga_recovery_pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    source["pipeline"] = source["pipeline"][:1]
    source["max_time_seconds"] = timeout_seconds
    source["max_steps"] = 10
    pipeline = StructuredPipeline.from_dict(source)
    scope = create_repl_scope()
    registry = dict(TOOL_REGISTRY)
    registry["python_repl"] = scope.run

    with tempfile.TemporaryDirectory() as workspace_dir:
        runner = StructuredPipelineRunner(
            llm_client=create_llm_client("ollama", model),
            workspace_dir=workspace_dir,
            verbose=False,
            tool_registry=registry,
            repl_globals_provider=lambda: scope.globals,
        )
        result = runner.run(pipeline, approval_callback=lambda *_: True)

    step = result.step_telemetry[0]
    proposals = [
        {
            "tool": event.data.get("data", ""),
            "type": event.data.get("type", ""),
        }
        for event in runner.event_log.events
        if event.event_type == "specialist_proposal"
    ]
    summary = {
        "success": result.success,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
        "steps_passed": result.steps_passed,
        "llm_calls": result.llm_calls,
        "tool_call_count": result.tool_call_count,
        "tool_error_count": result.tool_error_count,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "parse_repairs": result.parse_repairs,
        "protocol_error_count": result.protocol_error_count,
        "step_status": step.status,
        "step_attempts": step.attempts,
        "verification_passed": step.verification_passed,
        "verification_messages": step.verification_messages,
        "error": result.error,
    }
    if include_details:
        summary["proposals"] = proposals
        summary["tool_results"] = result.tool_calls
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--details", action="store_true", help="Include raw proposal and tool-call payloads.")
    args = parser.parse_args()
    results = [run_once(args.model, args.timeout, args.details) for _ in range(args.runs)]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
