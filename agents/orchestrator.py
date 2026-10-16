import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from agents.agent_registry import AGENT_REGISTRY, create_specialist
from llm_client import LLMClient
from tal.domain_packs import GLOBAL_DOMAIN_REGISTRY
from tal.epistemic import EpistemicState, EpistemicStore
from tal.event_store import EventLog

logger = logging.getLogger("capybara.orchestrator")


@dataclass
class ExecutionRun:
    """Turn-scoped execution state used for reporting and session telemetry."""

    run_id: str
    prompt: str
    execution_type: str
    started_at: float
    pipeline_result: Any | None = None
    final_answer: str = ""


class OrchestratorAgent:
    def __init__(self, llm_client: LLMClient, verbose: bool = True, knowledge_store=None, guardrails_enabled: bool = True, reflection_enabled: bool = False, tal_mode: bool = False, use_slm_profile: bool = False, tool_registry=None):
        self.llm_client = llm_client
        self.verbose = verbose
        self.knowledge_store = knowledge_store
        self.guardrails_enabled = guardrails_enabled
        self.reflection_enabled = reflection_enabled
        self.tal_mode = tal_mode
        self.use_slm_profile = use_slm_profile
        self.tool_registry = tool_registry
        self.event_log = EventLog()
        self.epistemic_store = EpistemicStore()
        self.memory: list[dict[str, str]] = []
        self.last_pipeline_result = None
        self.last_task_graph_result = None
        self.last_execution: ExecutionRun | None = None
        self.pending_interaction: dict[str, str] | None = None
        
        # Build prompt describing available specialists / domain packs
        specialist_desc = ""
        if self.tal_mode:
            for name in GLOBAL_DOMAIN_REGISTRY.list_packs():
                pack = GLOBAL_DOMAIN_REGISTRY.get(name)
                if pack:
                    specialist_desc += f"- {pack.name}: {pack.description}\n"
        else:
            for name, config in AGENT_REGISTRY.items():
                specialist_desc += f"- {name}: {config['description']}\n"
            
        self.orchestrator_prompt = (
            "You are an Orchestrator Agent. The user will give you a complex goal.\n"
            "Your job is to delegate tasks to specialized sub-agents.\n\n"
            "Available specialists:\n"
            f"{specialist_desc}\n"
            "Based on the goal, output a numbered list of delegations.\n"
            "Format each delegation exactly like this:\n"
            "DELEGATE: <specialist_name>: <detailed task instruction>\n\n"
            "Example:\n"
            "DELEGATE: researcher: Find the weather in Tokyo\n"
            "DELEGATE: coder: Write a Python script to print the weather\n"
            "If the goal is simple and only needs one specialist, just output one DELEGATE line.\n"
        )

    def _start_execution(self, prompt: Any, execution_type: str) -> ExecutionRun:
        """Start a fresh telemetry scope without discarding chat memory."""
        run = ExecutionRun(
            run_id=uuid.uuid4().hex,
            prompt=str(getattr(prompt, "title", prompt)),
            execution_type=execution_type,
            started_at=time.monotonic(),
        )
        self.event_log = EventLog()
        self.epistemic_store = EpistemicStore()
        self.last_pipeline_result = None
        self.last_task_graph_result = None
        self.last_execution = run
        if self.tal_mode:
            self.event_log.append("execution_started", {
                "run_id": run.run_id,
                "execution_type": execution_type,
                "prompt": run.prompt,
            })
        return run

    @staticmethod
    def _is_yes_no_reply(value: str) -> bool:
        return value.strip().lower() in {"y", "yes", "n", "no"}

    def _handle_ambiguous_follow_up(self, user_input: Any) -> str | None:
        """Keep terse confirmations from becoming unrelated delegated work."""
        if not isinstance(user_input, str) or not self._is_yes_no_reply(user_input):
            return None

        if self.pending_interaction:
            kind = self.pending_interaction.get("kind", "")
            if kind == "confirmation":
                # Confirmation routing is owned by the caller that created the
                # pending action.  Keep the state visible instead of inventing
                # an unrelated task here.
                return "I received your confirmation. Please repeat the action you want me to continue with."
            return "I still need the task or question you want help with."

        self.pending_interaction = {"kind": "clarification"}
        return "What would you like me to do? Please describe the task."
        
    def delegate(self, goal: str) -> list[tuple[str, str]]:
        """Ask the LLM to generate a delegation plan."""
        if self.tal_mode:
            self.event_log.append("user_input", {"content": goal})
            self.epistemic_store.add_fact(goal, state=EpistemicState.REPORTED, source="user:goal")

        messages = [
            {"role": "system", "content": self.orchestrator_prompt},
            *self.memory[-8:],
            {"role": "user", "content": f"Goal: {goal}"}
        ]
        
        response = self.llm_client.generate(messages)
        
        delegations = []
        lines = response.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            match = re.search(r'DELEGATE:\s*([\w-]+):\s*(.*)', line, re.IGNORECASE)
            if match:
                specialist_name = match.group(1).lower().strip()
                task_lines = [match.group(2).strip()]
                # Collect continuation lines (non-DELEGATE, non-empty lines)
                i += 1
                while i < len(lines):
                    next_line = lines[i].strip()
                    if not next_line or re.search(r'DELEGATE:', next_line, re.IGNORECASE):
                        break
                    task_lines.append(next_line)
                    i += 1
                delegations.append((specialist_name, ' '.join(task_lines)))
            else:
                i += 1
                
        return delegations
        
    def _run_delegations(self, user_input: Any, on_thought=None, on_specialist_event=None, on_answer=None, approval_callback=None):
        from tal.schemas import StructuredPipeline
        from tal.task_graph import TaskGraph
        if isinstance(user_input, TaskGraph) or (isinstance(user_input, dict) and "graph_id" in user_input and "nodes" in user_input):
            return self.run_task_graph(user_input, on_thought=on_thought, on_specialist_event=on_specialist_event, on_answer=on_answer, approval_callback=approval_callback)
        if isinstance(user_input, StructuredPipeline) or (isinstance(user_input, dict) and ("pipeline" in user_input or "steps" in user_input)):
            return self.run_pipeline(user_input, on_thought=on_thought, on_specialist_event=on_specialist_event, on_answer=on_answer, approval_callback=approval_callback)

        ambiguous_reply = self._handle_ambiguous_follow_up(user_input)
        if ambiguous_reply:
            self.event_log.append("task_waiting_for_user", {"question": ambiguous_reply})
            self.memory.append({"role": "user", "content": str(user_input)})
            self.memory.append({"role": "agent", "content": ambiguous_reply})
            if self.last_execution:
                self.last_execution.final_answer = ambiguous_reply
            if on_answer:
                on_answer(ambiguous_reply)
            return ambiguous_reply

        if on_thought: on_thought("Orchestrator is analyzing the goal...")
        self.pending_interaction = None
        self.memory.append({"role": "user", "content": str(user_input)})
        delegations = self.delegate(str(user_input))
        
        if not delegations:
             if on_thought: on_thought("Orchestrator decided to handle this generally.")
             delegations = [("general", user_input)]
             
        plan_str = "Delegation Plan:\n" + "\n".join(f"[{s.upper()}] -> {t}" for s, t in delegations)
        if on_thought: on_thought(plan_str)
        
        context = ""
        for spec_name, task in delegations:
            if on_thought: on_thought(f"Handoff to {spec_name.upper()}...")
            
            specialist = create_specialist(
                name=spec_name,
                llm_client=self.llm_client,
                verbose=self.verbose,
                knowledge_store=self.knowledge_store,
                guardrails_enabled=self.guardrails_enabled,
                reflection_enabled=self.reflection_enabled,
                tal_mode=self.tal_mode,
                use_slm_profile=self.use_slm_profile,
                tool_registry=self.tool_registry,
            )

            # Reset consecutive error counter and start fresh time tracking for this specialist
            if self.tal_mode and hasattr(specialist, "budget_tracker") and specialist.budget_tracker:
                specialist.budget_tracker.consecutive_errors = 0
                specialist.budget_tracker.start()

            # Link knowledge & epistemic facts
            if self.tal_mode:
                for fid, f in self.epistemic_store.facts.items():
                    specialist.epistemic_store.facts[fid] = f
            
            instruction = f"Task: {task}"
            if context:
                instruction += f"\n\nContext from previous steps:\n{context}"
                
            final_response = []
            
            def intercept(event_type, data):
                if on_specialist_event:
                    on_specialist_event(spec_name, event_type, data)
                if event_type in ("answer", "error"):
                    final_response.append(data.get("content", ""))
                    
            specialist.run_turn_streaming(instruction, intercept, max_steps=8, approval_callback=approval_callback)
            result = final_response[-1] if final_response else "No result."

            context += f"Result from {spec_name}:\n{result}\n"

            # Merge specialist events and facts back into orchestrator
            if self.tal_mode:
                for evt in specialist.event_log.events:
                    self.event_log.append(
                        f"specialist_{evt.event_type}",
                        {"specialist": spec_name, **evt.data},
                        timestamp=evt.timestamp,
                    )
                for fid, fact in specialist.epistemic_store.facts.items():
                    self.epistemic_store.facts[fid] = fact

        if on_thought: on_thought("Orchestrator is synthesizing the final answer...")
        
        messages = [
            {"role": "system", "content": "You are the Orchestrator. You delegated tasks to specialists. Now synthesize their results into a final answer for the user."},
            {"role": "user", "content": f"User's Goal: {user_input}\n\nSpecialist Results:\n{context}\n\nPlease provide a final, comprehensive answer."}
        ]
        
        final_answer = ""
        try:
            final_answer = self.llm_client.generate(messages)
        except Exception:
            final_answer = ""

        # Compact retry if response was empty or whitespace
        if not final_answer or not str(final_answer).strip():
            retry_messages = [
                {"role": "system", "content": "Summarize the findings and results for the user. Be direct and comprehensive."},
                {"role": "user", "content": f"Goal: {user_input}\nResults:\n{context}\n\nProvide the final answer now:"}
            ]
            try:
                final_answer = self.llm_client.generate(retry_messages)
            except Exception:
                final_answer = ""

        # Deterministic fallback summary if model still returned empty
        if not final_answer or not str(final_answer).strip():
            summary_lines = [f"### Summary of Task: '{user_input}'"]
            if context.strip():
                summary_lines.append(context.strip())
            else:
                summary_lines.append("The specialists completed their delegation steps.")
            final_answer = "\n\n".join(summary_lines)
        
        if self.tal_mode:
            from tal.verification import infer_verification_from_goal, run_verification
            criteria = infer_verification_from_goal(user_input)
            if criteria:
                import tools.file_tools
                ws_dir = getattr(tools.file_tools, "WORKSPACE_DIR", "")
                passed, msgs = run_verification(criteria, workspace_dir=ws_dir)
                self.event_log.append("verification_run", {"passed": passed, "messages": msgs})
                if not passed:
                    final_answer += "\n\nTask incomplete: " + "; ".join(msgs)
                    self.event_log.append("task_escalated", {"reason": "Completion verification failed"})
                else:
                    self.event_log.append("task_completed", {"answer": final_answer})
            else:
                self.event_log.append("task_completed", {"answer": final_answer})

        self.memory.append({"role": "agent", "content": final_answer})
        if self.last_execution:
            self.last_execution.final_answer = final_answer
        if on_answer: on_answer(final_answer)
        return final_answer

    def run_pipeline(
        self,
        pipeline: Any,
        on_thought=None,
        on_specialist_event=None,
        on_answer=None,
        approval_callback=None,
        resume: bool = False,
    ) -> str:
        """Executes a StructuredPipeline using the StructuredPipelineRunner."""
        from tal.pipeline_runner import StructuredPipelineRunner
        from tal.schemas import StructuredPipeline

        if isinstance(pipeline, dict):
            pipeline_obj = StructuredPipeline.from_dict(pipeline)
        elif isinstance(pipeline, StructuredPipeline):
            pipeline_obj = pipeline
        else:
            raise ValueError(f"Expected StructuredPipeline or dict, got {type(pipeline).__name__}")

        run = self._start_execution(pipeline_obj, "pipeline")

        pipeline_memory_entry = f"Execute Structured Pipeline '{pipeline_obj.title}'"
        self.memory.append({"role": "user", "content": pipeline_memory_entry})
        if self.tal_mode:
            self.event_log.append("user_input", {"content": pipeline_memory_entry})

        runner = StructuredPipelineRunner(
            llm_client=self.llm_client,
            verbose=self.verbose,
            knowledge_store=self.knowledge_store,
            guardrails_enabled=self.guardrails_enabled,
            tal_mode=self.tal_mode,
            use_slm_profile=self.use_slm_profile,
            tool_registry=self.tool_registry,
            repl_globals_provider=getattr(self, "repl_globals_provider", None),
        )

        def handle_specialist_event(spec, evt_type, data):
            if evt_type == "thought":
                self.event_log.append("specialist_thought", {"specialist": spec, "content": data.get("content", "")})

            if on_specialist_event:
                on_specialist_event(spec, evt_type, data)

        res = runner.run(
            pipeline=pipeline_obj,
            on_thought=on_thought,
            on_specialist_event=handle_specialist_event,
            approval_callback=approval_callback,
            resume=resume,
        )
        self.last_pipeline_result = res
        run.pipeline_result = res

        # Merge event log & epistemic facts from runner into orchestrator
        for evt in runner.event_log.events:
            self.event_log.append(evt.event_type, evt.data, timestamp=evt.timestamp)
        for fid, fact in runner.epistemic_store.facts.items():
            self.epistemic_store.facts[fid] = fact

        final_answer = res.final_output
        if res.error:
            final_answer += f"\n\n⚠️ **Pipeline Execution Incomplete**: {res.error}"

        self.memory.append({"role": "agent", "content": final_answer})
        run.final_answer = final_answer

        if on_answer:
            on_answer(final_answer)
        return final_answer

    def run_task_graph(
        self,
        graph: Any,
        on_thought=None,
        on_specialist_event=None,
        on_answer=None,
        approval_callback=None,
    ) -> str:
        """Execute a typed dependency graph through the verified TAL scheduler."""
        from tal.pipeline_runner import StructuredPipelineRunner
        from tal.task_graph import TaskGraph, TaskGraphRunner

        graph_obj = TaskGraph.from_dict(graph) if isinstance(graph, dict) else graph
        if not isinstance(graph_obj, TaskGraph):
            raise ValueError(f"Expected TaskGraph or dict, got {type(graph).__name__}")
        run = self._start_execution(graph_obj, "task_graph")
        self.memory.append({"role": "user", "content": f"Execute Task Graph '{graph_obj.title}'"})
        if self.tal_mode:
            self.event_log.append("user_input", {"content": self.memory[-1]["content"]})

        pipeline_runner = StructuredPipelineRunner(
            llm_client=self.llm_client,
            verbose=self.verbose,
            knowledge_store=self.knowledge_store,
            guardrails_enabled=self.guardrails_enabled,
            tal_mode=self.tal_mode,
            use_slm_profile=self.use_slm_profile,
            tool_registry=self.tool_registry,
            repl_globals_provider=getattr(self, "repl_globals_provider", None),
        )

        def handle_specialist_event(spec, evt_type, data):
            if evt_type == "thought":
                self.event_log.append("specialist_thought", {"specialist": spec, "content": data.get("content", "")})
            if on_specialist_event:
                on_specialist_event(spec, evt_type, data)

        result = TaskGraphRunner(pipeline_runner).run(
            graph_obj,
            on_thought=on_thought,
            on_specialist_event=handle_specialist_event,
            approval_callback=approval_callback,
        )
        self.last_task_graph_result = result
        run.pipeline_result = result.pipeline_result
        for event in pipeline_runner.event_log.events:
            self.event_log.append(event.event_type, event.data, timestamp=event.timestamp)
        final_answer = result.pipeline_result.final_output
        if result.pipeline_result.error:
            final_answer += f"\n\n⚠️ **Task Graph Execution Incomplete**: {result.pipeline_result.error}"
        self.memory.append({"role": "agent", "content": final_answer})
        run.final_answer = final_answer
        if on_answer:
            on_answer(final_answer)
        return final_answer

    def run(self, user_input: Any) -> str:
        """Main entry point. Delegates and coordinates."""
        from tal.schemas import StructuredPipeline
        if isinstance(user_input, StructuredPipeline) or (isinstance(user_input, dict) and user_input.get("is_pipeline")):
            pipeline_obj = user_input.get("pipeline") if isinstance(user_input, dict) else user_input
            return self.run_pipeline(pipeline_obj)

        self._start_execution(user_input, "delegation")

        def _safe_print(msg: str):
            try:
                print(msg)
            except UnicodeEncodeError:
                print(msg.encode("ascii", "replace").decode("ascii"))

        def handle_event(s, t, d):
            if not self.verbose: return
            if t == "thought": _safe_print(f"[{s.upper()}] 💭 {d.get('content', '')}")
            elif t == "tool_start": _safe_print(f"[{s.upper()}] 🔧 {d.get('name', '')}('{d.get('args', '')}')")
            elif t == "tool_result": _safe_print(f"[{s.upper()}] 👁 {d.get('result', '')}")
            
        return self._run_delegations(
            user_input,
            on_thought=lambda t: _safe_print(f"🎩 {t}") if self.verbose else None,
            on_specialist_event=handle_event
        )

    def run_with_trace(self, user_input: Any, approval_callback=None) -> dict:
        """Runs the orchestrator and returns structured trace data for the web UI."""
        trace = {"response": "", "thoughts": [], "tools_used": []}
        
        def handle_event(s, t, d):
            if t == "thought": trace["thoughts"].append(f"[{s.upper()}] {d['content']}")
            elif t == "tool_start":
                trace["tools_used"].append({"name": f"[{s.upper()}] {d['name']}", "args": d.get("args", ""), "result": ""})
            elif t == "tool_result":
                for tool in reversed(trace["tools_used"]):
                    if tool["name"] == f"[{s.upper()}] {d['name']}":
                        tool["result"] = d.get("result", "")
                        break
                        
        from tal.schemas import StructuredPipeline
        if isinstance(user_input, StructuredPipeline) or (isinstance(user_input, dict) and user_input.get("is_pipeline")):
            pipeline_obj = user_input.get("pipeline") if isinstance(user_input, dict) else user_input
            trace["response"] = self.run_pipeline(
                pipeline_obj,
                on_thought=lambda t: trace["thoughts"].append(t),
                on_specialist_event=handle_event,
                approval_callback=approval_callback,
            )
        else:
            self._start_execution(user_input, "delegation")
            trace["response"] = self._run_delegations(
                user_input,
                on_thought=lambda t: trace["thoughts"].append(t),
                on_specialist_event=handle_event,
                approval_callback=approval_callback,
            )
        return trace

    def run_streaming(self, user_input: Any, callback, approval_callback=None) -> None:
        """Runs the orchestrator and sub-agents, emitting events via callback."""
        def handle_event(s, t, d):
            if t in ("thought", "answer"): d["content"] = f"[{s.upper()}] {d.get('content', '')}"
            elif t in ("tool_start", "tool_result"): d["name"] = f"[{s.upper()}] {d.get('name', '')}"
            callback(t, d)

        from tal.schemas import StructuredPipeline
        if isinstance(user_input, StructuredPipeline) or (isinstance(user_input, dict) and user_input.get("is_pipeline")):
            pipeline_obj = user_input.get("pipeline") if isinstance(user_input, dict) else user_input
            self.run_pipeline(
                pipeline_obj,
                on_thought=lambda t: callback("thought", {"content": t}),
                on_specialist_event=handle_event,
                on_answer=lambda a: callback("answer", {"content": a}),
                approval_callback=approval_callback
            )
        else:
            self._start_execution(user_input, "delegation")
            self._run_delegations(
                user_input,
                on_thought=lambda t: callback("thought", {"content": t}),
                on_specialist_event=handle_event,
                on_answer=lambda a: callback("answer", {"content": a}),
                approval_callback=approval_callback
            )

    def generate_feedback_report(self, user_input: Any, final_answer: str, duration_seconds: float = 0.0, error: str | None = None) -> Any:
        """Generates a structured TALFeedbackReport consolidating orchestrator and specialist telemetry."""
        import tools.file_tools
        from tal.feedback_report import TALFeedbackReport, compute_health_score
        from tal.verification import infer_verification_from_goal, run_verification
        
        prompt_str = str(getattr(user_input, "title", user_input)) if not isinstance(user_input, str) else user_input

        # Extract verification metrics
        v_passed = None
        v_messages = []
        criteria = infer_verification_from_goal(prompt_str)
        if criteria:
            ws_dir = getattr(tools.file_tools, "WORKSPACE_DIR", "")
            v_passed, v_messages = run_verification(criteria, workspace_dir=ws_dir)
            
        tool_calls = []
        thoughts = []
        gate_blocks = 0
        gate_block_details = []
        tool_error_count = 0
        pipeline_metrics = None
        
        if self.tal_mode and self.event_log:
            for evt in self.event_log.events:
                if evt.event_type in ("tool_executed", "specialist_tool_executed"):
                    spec = evt.data.get("specialist", "")
                    prefix = f"[{spec.upper()}] " if spec else ""
                    t_name = prefix + (evt.data.get("tool") or evt.data.get("name", ""))
                    t_result = str(evt.data.get("result", "ok"))
                    tool_calls.append({"tool": t_name, "args": evt.data.get("args", ""), "result": t_result})
                    if t_result.strip().lower().startswith("error:") or "syntaxerror" in t_result.lower():
                        tool_error_count += 1
                elif evt.event_type in ("action_blocked", "action_gate_block", "specialist_action_gate_block", "specialist_action_blocked"):
                    gate_blocks += 1
                    gate_block_details.append(evt.data)
                elif evt.event_type in ("thought", "specialist_thought", "proposal", "specialist_proposal"):
                    th = evt.data.get("thought") or evt.data.get("content", "")
                    if th:
                        thoughts.append(str(th))

        execution = self.last_execution
        # The fallback keeps externally-constructed report fixtures compatible.
        # Live executions always have ``last_execution`` and therefore cannot
        # accidentally reuse a result from an earlier turn.
        if execution is not None and execution.pipeline_result is not None:
            pipeline_res = execution.pipeline_result
        elif execution is None and getattr(self, "last_pipeline_result", None) is not None:
            pipeline_res = self.last_pipeline_result
        else:
            pipeline_res = None
        if pipeline_res is not None:
            pipeline_metrics = pipeline_res
            # PipelineExecutionResult carries the canonical invocation trace.
            # Do not rebuild it from the orchestrator event log: the live
            # callback and runner merge represent the same tool result.
            tool_calls = [dict(call) for call in getattr(pipeline_res, "tool_calls", [])]
            tool_error_count = pipeline_res.tool_error_count
            if not pipeline_res.success:
                error = pipeline_res.error or "Pipeline halted: Step verification failed."
                v_passed = False
                v_messages = [t.error for t in pipeline_res.step_telemetry if t.error]
            else:
                v_passed = True
                v_messages = [f"Step [{t.step_id}] passed" for t in pipeline_res.step_telemetry]

        model_name = getattr(self.llm_client, "model", "unknown") if self.llm_client else "unknown"
        provider_name = getattr(self.llm_client, "provider", "unknown") if self.llm_client else "unknown"

        report = TALFeedbackReport(
            prompt=prompt_str,
            mode="multi-agent",
            model=model_name,
            provider=provider_name,
            final_answer=final_answer,
            success=(error is None),
            error=error,
            duration_seconds=round(pipeline_metrics.elapsed_seconds if pipeline_metrics else duration_seconds, 2),
            steps_taken=pipeline_metrics.steps_consumed if pipeline_metrics else len(thoughts) + len(tool_calls),
            max_steps=pipeline_metrics.max_steps if pipeline_metrics else getattr(getattr(self, "budget_limits", None), "max_steps", 15),
            llm_calls=pipeline_metrics.llm_calls if pipeline_metrics else len([e for e in self.event_log.events if e.event_type in ("proposal", "specialist_proposal")]),
            input_tokens=pipeline_metrics.input_tokens if pipeline_metrics else len(prompt_str) // 4,
            output_tokens=pipeline_metrics.output_tokens if pipeline_metrics else len(final_answer) // 4,
            total_tokens=(pipeline_metrics.input_tokens + pipeline_metrics.output_tokens) if pipeline_metrics else (len(prompt_str) + len(final_answer)) // 4,
            tool_calls=tool_calls,
            tool_call_count=len(tool_calls),
            tool_error_count=tool_error_count,
            thoughts=thoughts,
            parse_repairs=(
                getattr(pipeline_metrics, "parse_repairs", sum(getattr(step, "parse_repairs", 0) for step in pipeline_metrics.step_telemetry))
                if pipeline_metrics else
                sum(1 for evt in self.event_log.events if evt.event_type in ("proposal_repaired", "specialist_proposal_repaired"))
            ),
            protocol_error_count=(
                getattr(pipeline_metrics, "protocol_error_count", 0)
                if pipeline_metrics else
                sum(1 for evt in self.event_log.events if evt.event_type in ("proposal_protocol_error", "specialist_proposal_protocol_error"))
            ),
            gate_blocks=gate_blocks,
            gate_block_details=gate_block_details,
            epistemic_fact_count=len(self.epistemic_store.facts) if self.tal_mode else 0,
            epistemic_facts=[f.to_dict() for f in self.epistemic_store.facts.values()] if self.tal_mode else [],
            verification_passed=v_passed,
            verification_messages=v_messages,
            events_count=len(self.event_log.events) if self.tal_mode else 0,
        )

        score, rating, recs = compute_health_score(report)
        report.health_score = score
        report.health_rating = rating
        report.recommendations = recs
        return report
