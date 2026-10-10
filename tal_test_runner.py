import contextlib
import logging
import random
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from agent import BasicAgent
from agents.orchestrator import OrchestratorAgent
from llm_client import LLMClient
from planning_agent import PlanningAgent
from tal.slm_profile import is_slm_model
from tal_test_report import (
    RunMetrics,
    TALTestResult,
    save_batch_result,
    save_test_result,
)

logger = logging.getLogger("capybara.tal_test")


class TrackingLLMClient(LLMClient):
    """
    LLMClient proxy that wraps an existing LLMClient to accurately
    measure total LLM calls, input tokens, output tokens, and message history.
    """
    def __init__(self, underlying_client: LLMClient):
        super().__init__(
            model=getattr(underlying_client, "model", "unknown-model"),
            api_key=getattr(underlying_client, "api_key", None)
        )
        self.underlying = underlying_client
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.history: list[dict[str, Any]] = []

    def _estimate_tokens(self, messages: list[dict[str, Any]], response_text: str) -> tuple[int, int]:
        inp = sum(len(str(m.get("content") or "")) for m in messages) // 4
        out = len(str(response_text or "")) // 4
        return inp, out

    def generate(self, messages: list[dict[str, str]], json_mode: bool = False, timeout_seconds: float | None = None) -> str:
        import inspect
        kwargs = {"json_mode": json_mode}
        if timeout_seconds is not None and "timeout_seconds" in inspect.signature(self.underlying.generate).parameters:
            kwargs["timeout_seconds"] = timeout_seconds
        response = self.underlying.generate(messages, **kwargs)
        inp, out = self._estimate_tokens(messages, response)
        self.llm_calls += 1
        self.input_tokens += inp
        self.output_tokens += out
        self.total_tokens += (inp + out)
        self.history.append({"messages": messages, "response": response, "inp": inp, "out": out})
        return response

    def generate_with_retry(self, messages: list[dict[str, str]], json_mode: bool = False, max_retries: int = 3, callback: Callable | None = None, deadline=None) -> str:
        if hasattr(self.underlying, "generate_with_retry"):
            import inspect
            # We want to track the final output tokens and input tokens
            kwargs = {"json_mode": json_mode, "max_retries": max_retries, "callback": callback}
            if deadline is not None and "deadline" in inspect.signature(self.underlying.generate_with_retry).parameters:
                kwargs["deadline"] = deadline
            response = self.underlying.generate_with_retry(messages, **kwargs)
            inp, out = self._estimate_tokens(messages, response)
            self.llm_calls += 1
            self.input_tokens += inp
            self.output_tokens += out
            self.total_tokens += (inp + out)
            self.history.append({"messages": messages, "response": response, "inp": inp, "out": out})
            return response
        else:
            return self.generate(messages, json_mode=json_mode)

    @classmethod
    def list_models(cls) -> list[str]:
        return []


@contextlib.contextmanager
def sandbox_workspace():
    """Provides a temporary, isolated workspace directory to prevent run interference."""
    temp_dir = tempfile.mkdtemp(prefix="capy_tal_test_")
    import tools.file_tools
    old_workspace = getattr(tools.file_tools, "WORKSPACE_DIR", None)
    tools.file_tools.WORKSPACE_DIR = os.path.realpath(temp_dir)
    from tools.external_tools import reset_repl_globals
    reset_repl_globals()
    try:
        yield temp_dir
    finally:
        reset_repl_globals()
        if old_workspace is not None:
            tools.file_tools.WORKSPACE_DIR = old_workspace
        shutil.rmtree(temp_dir, ignore_errors=True)


class TALTestRunner:
    """
    Executes prompts twice (once baseline without TAL, once with TAL),
    capturing telemetry and generating comparative metrics.
    """
    def __init__(
        self,
        llm_client: LLMClient,
        mode: str = "react",                  # react (1) | planning (2) | multi-agent (3)
        max_steps: int = 5,
        verbose: bool = False,
        guardrails_enabled: bool = True,
        reflection_enabled: bool = False,
        use_slm_profile: bool = False,
        knowledge_store: Any | None = None,
        storage_dir: str | None = None
    ):
        self.llm_client = llm_client
        self.mode = self._normalize_mode(mode)
        self.max_steps = max_steps
        self.verbose = verbose
        self.guardrails_enabled = guardrails_enabled
        self.reflection_enabled = reflection_enabled
        model_str = getattr(llm_client, "model", "")
        self.use_slm_profile = use_slm_profile or is_slm_model(model_str)
        self.knowledge_store = knowledge_store
        self.storage_dir = storage_dir

    def _normalize_mode(self, mode: str) -> str:
        m = str(mode).strip().lower()
        if m in ("1", "react"):
            return "react"
        elif m in ("2", "plan", "planning"):
            return "planning"
        elif m in ("3", "multi", "multi-agent", "orchestrator"):
            return "multi-agent"
        return "react"

    def _run_single_agent(self, prompt: str, tal_mode: bool) -> RunMetrics:
        """Runs the configured agent architecture in a sandboxed workspace and gathers metrics."""
        tracking_llm = TrackingLLMClient(self.llm_client)
        start_time = time.time()

        # Telemetry accumulators
        thoughts: list[str] = []
        tools_called: list[dict[str, Any]] = []
        final_answer: str = ""
        error_msg: str | None = None
        success: bool = True

        def streaming_callback(event_type: str, data: dict[str, Any]):
            nonlocal final_answer, error_msg, success
            if event_type == "thought":
                thoughts.append(data.get("content", ""))
            elif event_type == "tool_start":
                tools_called.append({
                    "tool": data.get("name", ""),
                    "args": data.get("args", ""),
                    "result": ""
                })
            elif event_type == "tool_result":
                tool_name = data.get("name", "")
                result_str = str(data.get("result", ""))
                # Update the matching tool call in our list
                for item in reversed(tools_called):
                    if item["tool"] == tool_name and not item["result"]:
                        item["result"] = result_str[:300]
                        break
                else:
                    tools_called.append({
                        "tool": tool_name,
                        "args": "",
                        "result": result_str[:300]
                    })
            elif event_type == "answer":
                final_answer = data.get("content", "")
            elif event_type == "error":
                error_msg = data.get("content", "")
                success = False

        # Benchmark runs never grant destructive capabilities implicitly.
        def auto_approve_callback(tool_name: str, args: str) -> bool:
            return False

        with sandbox_workspace():
            agent_instance = None
            try:
                if self.mode == "react":
                    agent_instance = BasicAgent(
                        llm_client=tracking_llm,
                        system_prompt="You are a helpful AI assistant. You have access to tools. If the user asks you to do something that requires a tool, use it! Otherwise, just chat with them normally.",
                        verbose=self.verbose,
                        knowledge_store=self.knowledge_store,
                        guardrails_enabled=self.guardrails_enabled,
                        reflection_enabled=self.reflection_enabled,
                        tal_mode=tal_mode,
                        use_slm_profile=self.use_slm_profile
                    )
                    agent_instance.run_turn_streaming(
                        prompt,
                        callback=streaming_callback,
                        max_steps=self.max_steps,
                        approval_callback=auto_approve_callback
                    )

                elif self.mode == "planning":
                    basic = BasicAgent(
                        llm_client=tracking_llm,
                        system_prompt="You are a helpful AI assistant. You have access to tools. If the user asks you to do something that requires a tool, use it! Otherwise, just chat with them normally.",
                        verbose=self.verbose,
                        knowledge_store=self.knowledge_store,
                        guardrails_enabled=self.guardrails_enabled,
                        reflection_enabled=self.reflection_enabled,
                        tal_mode=tal_mode,
                        use_slm_profile=self.use_slm_profile
                    )
                    planner = PlanningAgent(basic_agent=basic, llm_client=tracking_llm, tal_mode=tal_mode)
                    agent_instance = basic
                    planner.run_streaming(
                        prompt,
                        callback=streaming_callback,
                        approval_callback=auto_approve_callback
                    )

                elif self.mode == "multi-agent":
                    orchestrator = OrchestratorAgent(
                        llm_client=tracking_llm,
                        verbose=self.verbose,
                        knowledge_store=self.knowledge_store,
                        guardrails_enabled=self.guardrails_enabled,
                        reflection_enabled=self.reflection_enabled,
                        tal_mode=tal_mode,
                        use_slm_profile=self.use_slm_profile
                    )
                    agent_instance = orchestrator
                    orchestrator.run_streaming(
                        prompt,
                        callback=streaming_callback,
                        approval_callback=auto_approve_callback
                    )

            except Exception as e:
                error_msg = f"Exception during execution: {e}"
                success = False

        duration = time.time() - start_time

        # If final_answer wasn't set by streaming callback (e.g. error), extract from memory
        if not final_answer and agent_instance and hasattr(agent_instance, "memory") and agent_instance.memory:
            for msg in reversed(agent_instance.memory):
                if msg.get("role") == "agent":
                    final_answer = msg.get("content", "")
                    break

        # Calculate tool errors
        tool_errors = 0
        for tc in tools_called:
            res = str(tc.get("result", ""))
            if res.startswith("Error") or "Error:" in res or "DENIED" in res:
                tool_errors += 1

        # Extract TAL specific metrics
        gate_blocks = 0
        gate_block_details = []
        parse_repairs = 0
        epistemic_facts = []
        verification_passed = None
        verification_messages = []
        events_count = 0
        steps_taken = tracking_llm.llm_calls

        if agent_instance:
            if hasattr(agent_instance, "budget_tracker"):
                steps_taken = max(steps_taken, agent_instance.budget_tracker.steps_used)
                parse_repairs = agent_instance.budget_tracker.repair_attempts

            if hasattr(agent_instance, "event_log") and agent_instance.event_log:
                events_count = len(agent_instance.event_log.events)
                for evt in agent_instance.event_log.events:
                    if evt.event_type == "action_blocked":
                        gate_blocks += 1
                        gate_block_details.append(evt.data)
                    elif evt.event_type == "verification_run":
                        verification_passed = evt.data.get("passed")
                        verification_messages = evt.data.get("messages", [])

            if hasattr(agent_instance, "epistemic_store") and agent_instance.epistemic_store:
                epistemic_facts = [
                    f.to_dict() if hasattr(f, "to_dict") else asdict(f)
                    for f in agent_instance.epistemic_store.facts.values()
                ]

        # A benchmark completion is an outcome, not merely non-error text.
        # Artifact-oriented goals must have an observed acceptance-gate result.
        from tal.verification import infer_verification_from_goal
        requires_verification = bool(infer_verification_from_goal(prompt))
        outcome_success = bool(final_answer.strip()) and error_msg is None
        if requires_verification:
            outcome_success = outcome_success and verification_passed is True

        return RunMetrics(
            mode=self.mode,
            tal_enabled=tal_mode,
            final_answer=final_answer,
            success=success and outcome_success,
            error=error_msg,
            steps_taken=steps_taken,
            wall_clock_time=duration,
            llm_calls=tracking_llm.llm_calls,
            input_tokens=tracking_llm.input_tokens,
            output_tokens=tracking_llm.output_tokens,
            total_tokens=tracking_llm.total_tokens,
            tools_called=tools_called,
            tool_call_count=len(tools_called),
            tool_error_count=tool_errors,
            thoughts=thoughts,
            parse_repairs=parse_repairs,
            gate_blocks=gate_blocks,
            gate_block_details=gate_block_details,
            epistemic_fact_count=len(epistemic_facts),
            epistemic_facts=epistemic_facts,
            verification_passed=verification_passed,
            verification_messages=verification_messages,
            events_count=events_count,
        )

    def run_single_test(self, prompt: str, seed: int | None = None) -> TALTestResult:
        """Runs the prompt with baseline (No TAL) and with TAL, returning the paired comparison."""
        modes = [False, True]
        if seed is not None:
            random.Random(seed).shuffle(modes)
        metrics: dict[bool, RunMetrics] = {}
        for tal_mode in modes:
            if self.verbose:
                print(f"\n[TAL Test Mode] Running {'TAL' if tal_mode else 'Baseline'} mode...")
            metrics[tal_mode] = self._run_single_agent(prompt, tal_mode=tal_mode)
        baseline_metrics = metrics[False]
        tal_metrics = metrics[True]

        model_name = getattr(self.llm_client, "model", "unknown")
        provider_name = self.llm_client.__class__.__name__.replace("Provider", "").replace("Client", "").lower()

        result = TALTestResult(
            prompt=prompt,
            mode=self.mode,
            model=model_name,
            provider=provider_name,
            baseline=baseline_metrics,
            tal=tal_metrics,
        )

        # Save to disk
        save_test_result(result, storage_dir=self.storage_dir)

        return result

    def run_batch_test(
        self,
        prompts: list[str],
        on_progress: Callable[[int, int, TALTestResult], None] | None = None,
        repetitions: int = 1,
        seed: int | None = None,
    ) -> list[TALTestResult]:
        """Run randomized paired trials; repetitions control variance, not scope."""
        if repetitions < 1:
            raise ValueError("repetitions must be at least one")
        results: list[TALTestResult] = []
        trials = [(prompt, trial) for trial in range(repetitions) for prompt in prompts]
        rng = random.Random(seed)
        if seed is not None:
            rng.shuffle(trials)
        total = len(trials)

        for i, (prompt, _trial) in enumerate(trials, 1):
            run_seed = rng.randrange(2**32) if seed is not None else None
            res = self.run_single_test(prompt, seed=run_seed)
            results.append(res)
            if on_progress:
                on_progress(i, total, res)

        save_batch_result(results, storage_dir=self.storage_dir)
        return results
