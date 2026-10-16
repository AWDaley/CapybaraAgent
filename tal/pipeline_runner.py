import json
import logging
import time
import os
import hashlib
from dataclasses import asdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import tools.file_tools
from llm_client import LLMClient

from .epistemic import EpistemicState, EpistemicStore
from .artifact_catalog import ArtifactCatalog
from .budget import ExecutionDeadline
from .event_store import EventLog
from .materializer import OutputMaterializer
from .recovery import diagnose_verification_messages
from .safe_paths import resolve_workspace_path
from .schemas import PipelineStep, StructuredPipeline
from .verification import run_verification

logger = logging.getLogger("capybara.pipeline_runner")


def _is_tool_error(result: Any) -> bool:
    """Return whether a tool observation represents a failed invocation."""
    text = str(result or "").strip().lower()
    return bool(
        text.startswith("error")
        or "traceback (most recent call last)" in text
        or "stderr:" in text
        or "assertionerror" in text
        or "syntaxerror" in text
        or "action denied" in text
    )


def _normalize_tool_args(args: Any) -> str:
    """Normalize tool arguments for cross-attempt repetition detection."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (TypeError, json.JSONDecodeError):
            return args.strip()
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(args).strip()


@dataclass
class StepTelemetry:
    step_id: str
    specialist: str
    status: str  # "passed" | "failed_verification" | "timed_out" | "skipped"
    attempts: int
    verification_passed: bool
    verification_messages: list[str] = field(default_factory=list)
    output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0
    steps_consumed: int = 0
    llm_calls: int = 0
    tool_call_count: int = 0
    tool_error_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    parse_repairs: int = 0
    protocol_error_count: int = 0


@dataclass
class PipelineExecutionResult:
    pipeline_id: str
    title: str
    success: bool
    steps_total: int
    steps_passed: int
    step_telemetry: list[StepTelemetry] = field(default_factory=list)
    final_output: str = ""
    error: str | None = None
    elapsed_seconds: float = 0.0
    max_steps: int = 0
    steps_consumed: int = 0
    llm_calls: int = 0
    tool_call_count: int = 0
    tool_error_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    parse_repairs: int = 0
    protocol_error_count: int = 0
    termination_reason: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class StructuredPipelineRunner:
    """Executes structured multi-step pipelines as an isolated state machine.
    
    Enforces deterministic step-gating: Step (N+1) is blocked until Step (N)
    passes all acceptance verification criteria.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        workspace_dir: str | None = None,
        verbose: bool = True,
        knowledge_store=None,
        guardrails_enabled: bool = True,
        tal_mode: bool = True,
        use_slm_profile: bool = True,
        tool_registry=None,
        checkpoint_dir: str | None = None,
        repl_globals_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self.llm_client = llm_client
        self.workspace_dir = workspace_dir or tools.file_tools.WORKSPACE_DIR
        self.verbose = verbose
        self.knowledge_store = knowledge_store
        self.guardrails_enabled = guardrails_enabled
        self.tal_mode = tal_mode
        self.use_slm_profile = use_slm_profile
        self.tool_registry = tool_registry
        if repl_globals_provider is None:
            from tools.external_tools import get_repl_globals
            repl_globals_provider = get_repl_globals
        self._repl_globals_provider = repl_globals_provider
        self.checkpoint_dir = checkpoint_dir or os.path.join(self.workspace_dir, ".pipeline_checkpoints")
        self.event_log = EventLog()
        self.epistemic_store = EpistemicStore()
        self.artifact_catalog = ArtifactCatalog(self.workspace_dir)

    def _build_step_context(
        self,
        pipeline: StructuredPipeline,
        step: PipelineStep,
        step_results: dict[str, Any],
        remediation_diff: str = ""
    ) -> str:
        """Constructs a scoped, minimal prompt payload for a single pipeline step."""
        parts = [
            f"# Pipeline: {pipeline.title}",
            f"## Step [{step.step_id.upper()}]: {step.objective}"
        ]

        if pipeline.global_context:
            parts.append(f"### Global Environment Context:\n```json\n{json.dumps(pipeline.global_context, indent=2)}\n```")

        if step.inputs:
            parts.append(f"### Step Inputs:\n```json\n{json.dumps(step.inputs, indent=2)}\n```")

        upstream_steps = step.inputs_from_steps or ([step.inputs_from_step] if step.inputs_from_step else [])
        for upstream_step in upstream_steps:
            if upstream_step in step_results:
                upstream_data = step_results[upstream_step]
                parts.append(f"### Verified Data from [{upstream_step.upper()}]:\n{upstream_data}")

        if step.tool_allowlist:
            parts.append(f"### Authorized Tools for this step: [{', '.join(step.tool_allowlist)}]")

        if self.epistemic_store:
            verified_facts = self.epistemic_store.get_verified()
            if verified_facts:
                fact_lines = [f"- {f.claim}" for f in verified_facts]
                parts.append("### Established Verified Facts:\n" + "\n".join(fact_lines))

        if remediation_diff:
            parts.append(
                f"\n⚠️ **PREVIOUS ATTEMPT FAILED ACCEPTANCE GATES**\n"
                f"The previous output did not meet deterministic verification criteria:\n"
                f"{remediation_diff}\n\n"
                f"**ACTION REQUIRED**: Fix the specific issues identified above immediately."
            )

        return "\n\n".join(parts)

    def _clean_step_target_artifacts(self, step: PipelineStep) -> None:
        """Deprecated compatibility hook: pipeline execution never deletes user artifacts.

        Freshness is established by run-scoped workspaces and provenance, not by
        silently deleting a path selected by a pipeline definition.
        """
        return

    def _file_targets(self, step: PipelineStep) -> list[str]:
        return [
            str(criterion["path"])
            for criterion in step.verification_criteria
            if isinstance(criterion, dict)
            and criterion.get("type", "").lower() in {"file_exists", "ast_syntax", "json_schema", "file_json_schema"}
            and criterion.get("path")
        ]

    def _fingerprint_targets(self, targets: list[str]) -> dict[str, tuple | None]:
        result: dict[str, tuple | None] = {}
        for target in targets:
            try:
                stat = os.stat(resolve_workspace_path(self.workspace_dir, target))
                result[target] = (stat.st_mtime_ns, stat.st_size)
            except (OSError, ValueError):
                result[target] = None
        return result

    def _pipeline_fingerprint(self, pipeline: StructuredPipeline) -> str:
        canonical = json.dumps(asdict(pipeline), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _checkpoint_path(self, pipeline: StructuredPipeline) -> str:
        safe_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in pipeline.pipeline_id)
        return os.path.join(self.checkpoint_dir, f"{safe_id}.json")

    def _export_repl_state(self, steps: list[PipelineStep]) -> dict[str, Any]:
        requested = {name for step in steps for name in step.state_exports}
        repl_globals = self._repl_globals_provider()
        exports: dict[str, Any] = {}
        for name in requested:
            if name not in repl_globals:
                continue
            try:
                json.dumps(repl_globals[name])
            except (TypeError, ValueError):
                raise ValueError(f"Checkpoint export '{name}' is not JSON-serializable")
            exports[name] = repl_globals[name]
        return exports

    def _save_checkpoint(
        self,
        pipeline: StructuredPipeline,
        completed_steps: list[PipelineStep],
        telemetries: list[StepTelemetry],
        step_results: dict[str, Any],
        steps_consumed: int,
        remaining_time_seconds: float,
    ) -> str:
        completed_ids = {step.step_id for step in completed_steps}
        checkpoint = {
            "version": 1,
            "pipeline_id": pipeline.pipeline_id,
            "pipeline_fingerprint": self._pipeline_fingerprint(pipeline),
            "completed_steps": [
                {
                    "step_id": step.step_id,
                    "verification_criteria": step.verification_criteria,
                    "artifact_fingerprints": self._fingerprint_targets(self._file_targets(step)),
                    "telemetry": asdict(next(t for t in telemetries if t.step_id == step.step_id)),
                }
                for step in completed_steps
                if step.step_id in completed_ids
            ],
            "step_results": step_results,
            "repl_state": self._export_repl_state(completed_steps),
            "artifact_catalog": self.artifact_catalog.to_dict(),
            "steps_consumed": steps_consumed,
            "remaining_steps": max(0, pipeline.max_steps - steps_consumed),
            "remaining_time_seconds": max(0.0, remaining_time_seconds),
            "saved_at": time.time(),
        }
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        path = self._checkpoint_path(pipeline)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, sort_keys=True)
        os.replace(temp_path, path)
        self.event_log.append("checkpoint_saved", {"path": path, "completed_steps": [s.step_id for s in completed_steps]})
        return path

    def _load_checkpoint(self, pipeline: StructuredPipeline) -> dict[str, Any]:
        path = self._checkpoint_path(pipeline)
        if not os.path.exists(path):
            raise ValueError(f"No checkpoint exists for pipeline '{pipeline.pipeline_id}'")
        with open(path, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)
        if checkpoint.get("pipeline_fingerprint") != self._pipeline_fingerprint(pipeline):
            raise ValueError("Checkpoint does not match the current pipeline definition")
        self._repl_globals_provider().update(checkpoint.get("repl_state", {}))
        catalog_problems = self.artifact_catalog.verify(checkpoint.get("artifact_catalog", {}))
        if catalog_problems:
            raise ValueError("Checkpoint artifact catalog verification failed: " + "; ".join(catalog_problems))
        for item in checkpoint.get("completed_steps", []):
            passed, messages = run_verification(
                item.get("verification_criteria", []),
                workspace_dir=self.workspace_dir,
                repl_globals=self._repl_globals_provider(),
            )
            if not passed:
                raise ValueError(f"Checkpoint artifact verification failed for [{item.get('step_id')}]: {'; '.join(messages)}")
            for target, expected in item.get("artifact_fingerprints", {}).items():
                current = self._fingerprint_targets([target])[target]
                if expected is not None and tuple(expected) != current:
                    raise ValueError(f"Checkpoint artifact changed since save: {target}")
        self.event_log.append("checkpoint_loaded", {"path": path, "completed_steps": [s.get("step_id") for s in checkpoint.get("completed_steps", [])]})
        return checkpoint

    def run(
        self,
        pipeline: StructuredPipeline,
        on_thought: Callable[[str], None] | None = None,
        on_specialist_event: Callable[[str, str, Any], None] | None = None,
        approval_callback: Callable | None = None,
        resume: bool = False,
    ) -> PipelineExecutionResult:
        """Executes the pipeline sequentially with step-gating and remediation loops."""
        if on_thought:
            on_thought(f"Starting Structured Pipeline: '{pipeline.title}' ({len(pipeline.steps)} steps)")

        self.event_log.append("pipeline_start", {
            "pipeline_id": pipeline.pipeline_id,
            "title": pipeline.title,
            "max_steps": pipeline.max_steps,
            "max_time_seconds": pipeline.max_time_seconds,
        })

        step_results: dict[str, Any] = {}
        telemetries: list[StepTelemetry] = []
        pipeline_success = True
        overall_error = None
        deadline = ExecutionDeadline.start(pipeline.max_time_seconds)
        steps_consumed = 0
        llm_calls = 0
        tool_call_count = 0
        tool_error_count = 0
        tool_calls: list[dict[str, Any]] = []
        input_tokens = 0
        output_tokens = 0
        parse_repairs = 0
        protocol_error_count = 0
        completed_steps: list[PipelineStep] = []
        completed_step_ids: set[str] = set()

        if resume:
            checkpoint = self._load_checkpoint(pipeline)
            completed_step_ids = {str(item["step_id"]) for item in checkpoint.get("completed_steps", [])}
            completed_steps = [step for step in pipeline.steps if step.step_id in completed_step_ids]
            step_results = checkpoint.get("step_results", {})
            steps_consumed = int(checkpoint.get("steps_consumed", 0))
            for item in checkpoint.get("completed_steps", []):
                telemetry_data = item.get("telemetry", {})
                telemetry_data["status"] = "resumed"
                telemetries.append(StepTelemetry(**telemetry_data))
            llm_calls = sum(t.llm_calls for t in telemetries)
            tool_call_count = sum(t.tool_call_count for t in telemetries)
            tool_error_count = sum(t.tool_error_count for t in telemetries)
            input_tokens = sum(t.input_tokens for t in telemetries)
            output_tokens = sum(t.output_tokens for t in telemetries)
            parse_repairs = sum(t.parse_repairs for t in telemetries)
            protocol_error_count = sum(t.protocol_error_count for t in telemetries)
            self.event_log.append("pipeline_resumed", {"pipeline_id": pipeline.pipeline_id, "completed_steps": sorted(completed_step_ids)})

        for idx, step in enumerate(pipeline.steps, 1):
            if step.step_id in completed_step_ids:
                continue
            if deadline.expired:
                pipeline_success = False
                overall_error = "Pipeline time budget exhausted before the next step."
                break
            step_budget = step.max_steps if step.max_steps is not None else 10
            if steps_consumed >= pipeline.max_steps:
                pipeline_success = False
                overall_error = f"Pipeline step budget exhausted ({steps_consumed}/{pipeline.max_steps} steps used)."
                break
            step_header = f"=== Pipeline Step {idx}/{len(pipeline.steps)}: [{step.step_id}] ==="
            if on_thought:
                on_thought(step_header)
            logger.info(step_header)
            self.event_log.append("pipeline_step_started", {"step_id": step.step_id, "index": idx})

            # Do not erase existing workspace files.  Callers that require a
            # clean run must provide a dedicated, empty run workspace.
            target_fingerprints = self._fingerprint_targets(self._file_targets(step))

            attempts = 0
            max_attempts = 1 + step.max_retries
            step_passed = False
            remediation_feedback = ""
            last_output = ""
            last_verif_messages = []
            step_started_at = time.monotonic()
            step_steps_consumed = 0
            step_llm_calls = 0
            step_tool_calls = 0
            step_tool_errors = 0
            step_input_tokens = 0
            step_output_tokens = 0
            step_parse_repairs = 0
            step_protocol_error_count = 0
            failed_actions_from_attempts: set[tuple[str, str]] = set()
            specialist_events_seen = 0

            # --- Branch A: Zero-LLM Deterministic Harness Step ---
            if step.specialist.lower() in ("harness", "system", "deterministic"):
                attempts = 1
                if on_thought:
                    on_thought(f"⚙️ Executing deterministic harness step [{step.step_id}]...")

                if step.output_spec:
                    mat_ok, mat_msg, mat_data = OutputMaterializer.materialize_to_file(
                        spec=step.output_spec,
                        workspace_dir=self.workspace_dir,
                        repl_globals=self._repl_globals_provider(),
                    )
                    last_output = mat_msg
                    if not mat_ok:
                        step_passed = False
                        remediation_feedback = mat_msg
                        last_verif_messages = [mat_msg]
                    else:
                        if step.verification_criteria:
                            passed, messages = run_verification(
                                step.verification_criteria,
                                workspace_dir=self.workspace_dir,
                                repl_globals=self._repl_globals_provider(),
                            )
                            unchanged = [
                                name for name, before in target_fingerprints.items()
                                if self._fingerprint_targets([name])[name] == before
                            ]
                            if passed and unchanged:
                                passed = False
                                messages.append("No fresh artifact was produced for: " + ", ".join(unchanged))
                            step_passed = passed
                            last_verif_messages = messages
                            if not passed:
                                remediation_feedback = "\n".join(f"- {m}" for m in messages)
                        else:
                            step_passed = False
                            last_verif_messages = ["No independent acceptance criteria for materialized artifact"]
                            remediation_feedback = last_verif_messages[0]
                else:
                    step_passed = False
                    last_output = f"Harness step [{step.step_id}] executed without verifiable effects."
                    last_verif_messages = ["No independent acceptance criteria for harness step"]
                    remediation_feedback = last_verif_messages[0]

            # --- Branch B: Specialist LLM Agent Turn ---
            else:
                from agents.agent_registry import create_specialist
                specialist = create_specialist(
                    name=step.specialist,
                    llm_client=self.llm_client,
                    verbose=self.verbose,
                    knowledge_store=self.knowledge_store,
                    guardrails_enabled=self.guardrails_enabled,
                    tal_mode=self.tal_mode,
                    use_slm_profile=self.use_slm_profile,
                    tool_allowlist=step.tool_allowlist,
                    tool_registry=self.tool_registry,
                )
                # Step contexts are already deliberately scoped by
                # _build_step_context.  Do not spend an unbudgeted extra LLM
                # call summarizing a single pipeline instruction.
                if hasattr(specialist, "context_manager"):
                    specialist.context_manager.summary_threshold = 100_000

                if specialist and hasattr(specialist, "epistemic_store") and self.epistemic_store:
                    for fact in self.epistemic_store.get_all():
                        specialist.epistemic_store.add_fact(fact.claim, state=fact.state, source=fact.source)

                observed_input_tokens = 0
                observed_output_tokens = 0
                while attempts < max_attempts and not step_passed:
                    attempts += 1
                    if attempts > 1 and on_thought:
                        on_thought(f"🔄 Retrying [{step.step_id}] (Attempt {attempts}/{max_attempts}) with targeted remediation...")

                    instruction = self._build_step_context(
                        pipeline=pipeline,
                        step=step,
                        step_results=step_results,
                        remediation_diff=remediation_feedback
                    )

                    final_response = []
                    attempt_actions: set[tuple[str, str]] = set()
                    attempt_failed_actions: set[tuple[str, str]] = set()
                    attempt_tool_error_messages: list[str] = []
                    active_tool_call_index: int | None = None
                    llm_calls_before_attempt = getattr(specialist, "llm_call_count", 0)

                    def intercept(event_type, data):
                        nonlocal step_tool_calls, step_tool_errors, active_tool_call_index
                        if on_specialist_event:
                            on_specialist_event(step.specialist, event_type, data)
                        if event_type == "tool_start":
                            tool_name = str(data.get("name", ""))
                            tool_args = data.get("args", "")
                            action_signature = (tool_name, _normalize_tool_args(tool_args))
                            attempt_actions.add(action_signature)
                            active_tool_call_index = len(tool_calls)
                            tool_calls.append({
                                "tool": f"[{step.specialist.upper()}] {tool_name}",
                                "args": tool_args,
                                "result": "",
                            })
                            step_tool_calls += 1
                        elif event_type == "tool_result":
                            result = str(data.get("result", ""))
                            if active_tool_call_index is not None:
                                tool_calls[active_tool_call_index]["result"] = result
                            if _is_tool_error(result):
                                step_tool_errors += 1
                                attempt_tool_error_messages.append(result)
                                if active_tool_call_index is not None:
                                    tool_name = str(data.get("name", ""))
                                    tool_args = data.get("args", "")
                                    attempt_failed_actions.add(
                                        (tool_name, _normalize_tool_args(tool_args))
                                    )
                        if event_type in ("answer", "error"):
                            final_response.append(data.get("content", ""))

                    step_turn_budget = min(step_budget, pipeline.max_steps - steps_consumed)
                    specialist.run_turn_streaming(
                        instruction,
                        intercept,
                        max_steps=step_turn_budget,
                        approval_callback=approval_callback,
                        new_task=(attempts == 1),
                        deadline=deadline,
                        verification_criteria=[],
                        stop_after_tool=bool(step.verification_criteria),
                    )

                    if hasattr(specialist, "event_log"):
                        specialist_events = specialist.event_log.events
                        if len(specialist_events) < specialist_events_seen:
                            specialist_events_seen = 0
                        for event in specialist_events[specialist_events_seen:]:
                            self.event_log.append(
                                f"specialist_{event.event_type}",
                                {"specialist": step.specialist, **event.data},
                                timestamp=event.timestamp,
                            )
                            if event.event_type == "proposal_repaired":
                                step_parse_repairs += 1
                            elif event.event_type == "proposal_protocol_error":
                                step_protocol_error_count += 1
                        specialist_events_seen = len(specialist_events)

                    attempt_steps = getattr(getattr(specialist, "budget_tracker", None), "steps_used", 0)
                    step_steps_consumed += attempt_steps
                    steps_consumed += attempt_steps
                    attempt_llm_calls = max(
                        0,
                        getattr(specialist, "llm_call_count", 0) - llm_calls_before_attempt,
                    )
                    step_llm_calls += attempt_llm_calls
                    llm_calls += attempt_llm_calls
                    token_counter = getattr(specialist, "token_counter", None)
                    current_input_tokens = getattr(token_counter, "total_input_tokens", 0)
                    current_output_tokens = getattr(token_counter, "total_output_tokens", 0)
                    input_delta = max(0, current_input_tokens - observed_input_tokens)
                    output_delta = max(0, current_output_tokens - observed_output_tokens)
                    observed_input_tokens = current_input_tokens
                    observed_output_tokens = current_output_tokens
                    step_input_tokens += input_delta
                    step_output_tokens += output_delta
                    input_tokens += input_delta
                    output_tokens += output_delta

                    last_output = final_response[-1] if final_response else "No output produced."

                    repeated_failed_actions = sorted(
                        failed_actions_from_attempts & attempt_failed_actions
                    )
                    failed_actions_from_attempts.update(attempt_failed_actions)
                    repeat_feedback = ""
                    if repeated_failed_actions:
                        repeated_names = ", ".join(
                            f"{name}({args})" for name, args in repeated_failed_actions
                        )
                        repeat_feedback = (
                            "The exact same failing tool call was repeated across attempts: "
                            f"{repeated_names}. Change the action before retrying."
                        )

                    if deadline.expired:
                        remediation_feedback = "Pipeline deadline exhausted during specialist execution."
                        last_verif_messages = [remediation_feedback]
                        break

                    if attempt_tool_error_messages:
                        details = "\n".join(
                            f"- {message[:800]}" for message in attempt_tool_error_messages
                        )
                        remediation_feedback = (
                            "The previous tool action was rejected or failed. Correct the specific error "
                            f"and emit one changed action using only the authorized tools [{', '.join(step.tool_allowlist)}]:\n"
                            f"{details}"
                        )
                        last_verif_messages = [remediation_feedback]
                        continue

                    # A tool action can establish the required state even when
                    # the model's next response is malformed or empty.  Gates
                    # are authoritative, so evaluate them before treating a
                    # missing terminal envelope as a failed task attempt.
                    if (
                        attempt_actions
                        and not attempt_failed_actions
                        and step.verification_criteria
                        and not step.output_spec
                    ):
                        passed, messages = run_verification(
                            step.verification_criteria,
                            workspace_dir=self.workspace_dir,
                            repl_globals=self._repl_globals_provider(),
                        )
                        unchanged = [
                            name for name, before in target_fingerprints.items()
                            if self._fingerprint_targets([name])[name] == before
                        ]
                        if passed and unchanged:
                            passed = False
                            messages.append("No fresh artifact was produced for: " + ", ".join(unchanged))
                        if passed:
                            step_passed = True
                            last_verif_messages = messages
                            if (
                                not last_output.strip()
                                or last_output.strip() == "No output produced."
                                or last_output.lstrip().startswith("Escalation:")
                            ):
                                last_output = "Deterministic verification passed after a successful tool action."
                            if on_thought:
                                on_thought(
                                    f"✅ Step [{step.step_id}] PASSED deterministic verification after tool execution."
                                )
                            continue
                        last_verif_messages = messages
                        remediation_feedback = diagnose_verification_messages(messages).to_prompt()
                        repeated_verification_actions = sorted(
                            failed_actions_from_attempts & attempt_actions
                        )
                        failed_actions_from_attempts.update(attempt_actions)
                        if repeated_verification_actions:
                            repeated_names = ", ".join(
                                f"{name}({args})" for name, args in repeated_verification_actions
                            )
                            remediation_feedback += (
                                "\n- The exact same action failed verification on a previous attempt: "
                                f"{repeated_names}. Change the action before retrying."
                            )
                        if on_thought:
                            on_thought(
                                f"❌ Step [{step.step_id}] FAILED verification gate:\n{remediation_feedback}"
                            )
                        continue

                    if (
                        not last_output.strip()
                        or last_output.strip() == "No output produced."
                        or last_output.lstrip().startswith("Escalation:")
                    ):
                        remediation_feedback = (
                            "The specialist returned no actionable completion. "
                            "On the next attempt, emit exactly one corrective tool action "
                            "or a verified completion response."
                        )
                        if last_output.strip() and last_output.strip() != "No output produced.":
                            remediation_feedback = f"{last_output}\n{remediation_feedback}"
                        protocol_events = [
                            event for event in specialist.event_log.events
                            if event.event_type == "proposal_protocol_error"
                        ]
                        if protocol_events:
                            violation = protocol_events[-1].data.get("violation", "unknown protocol violation")
                            remediation_feedback = (
                                f"Your previous proposal violated the TAL schema: {violation}. "
                                "Return exactly one valid JSON proposal.\n"
                                f"{remediation_feedback}"
                            )
                        if repeat_feedback:
                            remediation_feedback += f"\n{repeat_feedback}"
                        last_verif_messages = [remediation_feedback]
                        continue

                    if last_output.lstrip().startswith("Error:"):
                        remediation_feedback = last_output
                        if repeat_feedback:
                            remediation_feedback += f"\n{repeat_feedback}"
                        last_verif_messages = [last_output]
                        continue

                    # Materialize declared output before evaluating gates, so a
                    # criterion can validate the actual deliverable.
                    if step.output_spec:
                        mat_ok, mat_msg, mat_data = OutputMaterializer.materialize_to_file(
                            spec=step.output_spec,
                            workspace_dir=self.workspace_dir,
                            repl_globals=self._repl_globals_provider(),
                        )
                        if not mat_ok:
                            remediation_feedback = f"Output materialization failed: {mat_msg}"
                            last_verif_messages = [mat_msg]
                            continue
                        last_output += f"\n\n[{mat_msg}]"

                    # Evaluate Deterministic Acceptance Gates
                    if step.verification_criteria:
                        passed, messages = run_verification(
                            step.verification_criteria,
                            workspace_dir=self.workspace_dir,
                            repl_globals=self._repl_globals_provider(),
                        )
                        unchanged = [
                            name for name, before in target_fingerprints.items()
                            if self._fingerprint_targets([name])[name] == before
                        ]
                        if passed and unchanged:
                            passed = False
                            messages.append("No fresh artifact was produced for: " + ", ".join(unchanged))
                        last_verif_messages = messages
                        if passed:
                            step_passed = True
                            if on_thought:
                                on_thought(f"✅ Step [{step.step_id}] PASSED all verification criteria:\n- " + "\n- ".join(messages))
                        else:
                            step_passed = False
                            remediation_feedback = diagnose_verification_messages(messages).to_prompt()
                            repeated_verification_actions = sorted(
                                failed_actions_from_attempts & attempt_actions
                            )
                            failed_actions_from_attempts.update(attempt_actions)
                            if repeated_verification_actions and not repeat_feedback:
                                repeated_names = ", ".join(
                                    f"{name}({args})"
                                    for name, args in repeated_verification_actions
                                )
                                repeat_feedback = (
                                    "The exact same action produced a failed verification "
                                    "on a previous attempt: "
                                    f"{repeated_names}. Change the action before retrying."
                                )
                            if repeat_feedback:
                                remediation_feedback += f"\n- {repeat_feedback}"
                            if on_thought:
                                on_thought(f"❌ Step [{step.step_id}] FAILED verification gate:\n{remediation_feedback}")
                    else:
                        step_passed = False
                        last_verif_messages = ["No independent acceptance criteria: completion unverified"]
                        remediation_feedback = last_verif_messages[0]
                        if on_thought:
                            on_thought(f"✅ Step [{step.step_id}] completed.")


            # Record telemetry for this step
            timed_out = deadline.expired or "deadline exhausted" in remediation_feedback.lower() or "time budget exhausted" in last_output.lower()
            status = "passed" if step_passed else ("timed_out" if timed_out else "failed_verification")
            tel = StepTelemetry(
                step_id=step.step_id,
                specialist=step.specialist,
                status=status,
                attempts=attempts,
                verification_passed=step_passed,
                verification_messages=last_verif_messages,
                output=last_output,
                error=remediation_feedback if not step_passed else None,
                duration_seconds=time.monotonic() - step_started_at,
                steps_consumed=step_steps_consumed,
                llm_calls=step_llm_calls,
                tool_call_count=step_tool_calls,
                tool_error_count=step_tool_errors,
                input_tokens=step_input_tokens,
                output_tokens=step_output_tokens,
                parse_repairs=step_parse_repairs,
                protocol_error_count=step_protocol_error_count,
            )
            telemetries.append(tel)
            tool_call_count += step_tool_calls
            tool_error_count += step_tool_errors
            parse_repairs += step_parse_repairs
            protocol_error_count += step_protocol_error_count

            # Record in event log
            self.event_log.append("pipeline_step_complete", {
                "step_id": step.step_id,
                "passed": step_passed,
                "status": status,
                "attempts": attempts,
                "messages": last_verif_messages,
                "duration_seconds": tel.duration_seconds,
                "steps_consumed": step_steps_consumed,
                "parse_repairs": step_parse_repairs,
                "protocol_error_count": step_protocol_error_count,
            })

            if step_passed:
                completed_steps.append(step)
                completed_step_ids.add(step.step_id)
                step_results[step.step_id] = last_output
                # If output_spec produced structured file, load content into context for downstream steps
                if step.output_spec:
                    try:
                        out_path = resolve_workspace_path(self.workspace_dir, step.output_spec.target_file)
                    except ValueError:
                        out_path = ""
                    if os.path.exists(out_path):
                        try:
                            with open(out_path, "r", encoding="utf-8") as f:
                                step_results[f"{step.step_id}:data"] = f.read()
                        except Exception:
                            pass
                self.artifact_catalog.record_many(self._file_targets(step), source_node=step.step_id)

                # Promote to epistemic verified store
                if step.verification_criteria:
                    self.epistemic_store.add_fact(
                        claim=f"Step [{step.step_id}] Verified Output: {last_output[:200]}...",
                        state=EpistemicState.VERIFIED,
                        source=f"pipeline:{step.step_id}"
                    )
                self._save_checkpoint(
                    pipeline=pipeline,
                    completed_steps=completed_steps,
                    telemetries=telemetries,
                    step_results=step_results,
                    steps_consumed=steps_consumed,
                    remaining_time_seconds=deadline.remaining_seconds,
                )
            else:
                # Anti-cascading barrier: halt pipeline execution immediately
                pipeline_success = False
                overall_error = f"Pipeline halted: Step [{step.step_id}] failed after {attempts} attempt(s):\n{remediation_feedback}"
                if on_thought:
                    on_thought(f"⛔ ANTI-CASCADING BARRIER: {overall_error}")
                break

        passed_count = sum(1 for t in telemetries if t.status in {"passed", "resumed"})
        final_summary = "\n\n".join(
            f"### Step [{t.step_id.upper()}] ({t.status.upper()} - {t.attempts} attempt(s)):\n{t.output}"
            for t in telemetries
        )
        self.event_log.append(
            "pipeline_completed" if pipeline_success else "pipeline_terminated",
            {
                "pipeline_id": pipeline.pipeline_id,
                "success": pipeline_success,
                "reason": overall_error,
                "elapsed_seconds": round(deadline.elapsed_seconds, 4),
                "steps_consumed": steps_consumed,
            },
        )

        return PipelineExecutionResult(
            pipeline_id=pipeline.pipeline_id,
            title=pipeline.title,
            success=pipeline_success,
            steps_total=len(pipeline.steps),
            steps_passed=passed_count,
            step_telemetry=telemetries,
            final_output=final_summary,
            error=overall_error,
            elapsed_seconds=deadline.elapsed_seconds,
            max_steps=pipeline.max_steps,
            steps_consumed=steps_consumed,
            llm_calls=llm_calls,
            tool_call_count=tool_call_count,
            tool_error_count=tool_error_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            parse_repairs=parse_repairs,
            protocol_error_count=protocol_error_count,
            termination_reason=overall_error,
            tool_calls=tool_calls,
        )
