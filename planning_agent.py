import logging
import json
import re

from agent import BasicAgent
from llm_client import LLMClient
from tal.context_packer import ExecutionPhase
from tal.manifest import TaskManifest
from tal.repair import repair_json_string
from tal.task_graph import TaskGraph, TaskGraphRunner, TaskGraphValidationError
from tal.verification import run_verification

logger = logging.getLogger("capybara.planning")

class PlanningAgent:
    def __init__(self, basic_agent: BasicAgent, llm_client: LLMClient, tal_mode: bool = False):
        self.basic_agent = basic_agent
        self.llm_client = llm_client
        self.tal_mode = tal_mode or getattr(basic_agent, "tal_mode", False)
        self.manifest: TaskManifest | None = None
        
        # We need a specific system prompt just for planning
        self.planner_prompt = (
            "You are a master planner. The user will give you a complex goal.\n"
            "Your job is to break it down into a numbered list of concrete steps that an agent can execute.\n"
            "Each step must be actionable and concise.\n"
            "Output your plan as a numbered list starting with 1. Do not include extra commentary.\n"
            "Example:\n"
            "1. Write the shopping list to shopping.txt\n"
            "2. Read shopping.txt to verify\n"
            "3. Count words in the text\n"
        )
        self.task_graph_prompt = (
            "You are an SLM task-graph planner. Break the goal into small, independently verifiable nodes. "
            "Output ONLY one JSON object using this closed schema:\n"
            '{"graph_id":"short_id","title":"short title","nodes":[{"node_id":"step_id","objective":"one narrow action",'
            '"dependencies":["prior_step_id"],"specialist":"general|coder|researcher","tool_allowlist":["tool"],'
            '"inputs":{},"verification_criteria":[],"state_exports":[],"subtasks":[],"max_retries":2,"max_steps":5}]}\n'
            "Every node must have a unique node_id and an objective. Use dependencies only for required upstream state. "
            "Keep each node small enough for one SLM-controlled action loop. If an objective has multiple transformations, put each one in subtasks so the runtime expands it into narrow nodes. Do not include markdown, explanations, or unknown keys."
        )
        
    def _parse_steps(self, response_text: str) -> list[str]:
        """Extracts numbered step list items from response text."""
        steps = []
        for line in response_text.split('\n'):
            line = line.strip()
            if re.match(r'^\d+\.\s+', line):
                step_text = re.sub(r'^\d+\.\s+', '', line)
                steps.append(step_text)
        return steps

    def plan(self, goal: str) -> list[str]:
        """Generates a numbered plan from the LLM based on the user's goal."""
        if self.tal_mode:
            from tal.verification import infer_verification_from_goal
            self.basic_agent.budget_tracker.reset()
            self.manifest = TaskManifest.compile(
                goal=goal,
                available_tools=self.basic_agent.tools,
                budget_limits=self.basic_agent.budget_limits,
                verification_criteria=[
                    {"type": "file_exists", "path": c.path, "min_size": c.min_size_bytes}
                    for c in infer_verification_from_goal(goal)
                ],
            )
            self.basic_agent.manifest = self.manifest
            self.basic_agent.current_phase = ExecutionPhase.PLANNING

        messages = [
            {"role": "system", "content": self.planner_prompt},
            {"role": "user", "content": f"Goal: {goal}"}
        ]
        
        response = self.llm_client.generate(messages)
        return self._parse_steps(response)

    def plan_task_graph(self, goal: str) -> TaskGraph:
        """Create and validate a closed-schema graph for TAL-mode execution."""
        if self.tal_mode:
            from tal.verification import infer_verification_from_goal
            self.basic_agent.budget_tracker.reset()
            self.manifest = TaskManifest.compile(
                goal=goal,
                available_tools=self.basic_agent.tools,
                budget_limits=self.basic_agent.budget_limits,
                verification_criteria=[
                    {"type": "file_exists", "path": criterion.path, "min_size": criterion.min_size_bytes}
                    for criterion in infer_verification_from_goal(goal)
                ],
            )
            self.basic_agent.manifest = self.manifest
            self.basic_agent.current_phase = ExecutionPhase.PLANNING

        messages = [
            {"role": "system", "content": self.task_graph_prompt},
            {"role": "user", "content": f"Goal: {goal}"},
        ]
        response = self.llm_client.generate(messages, json_mode=True)
        try:
            payload = json.loads(repair_json_string(response))
            return TaskGraph.from_dict(payload)
        except (json.JSONDecodeError, TaskGraphValidationError, ValueError, TypeError) as exc:
            raise TaskGraphValidationError(f"Planner did not emit a valid task graph: {exc}") from exc

    def execute_task_graph(self, graph: TaskGraph, approval_callback=None) -> str:
        """Execute a validated graph through the existing verified pipeline runner."""
        from tal.pipeline_runner import StructuredPipelineRunner
        from tools.file_tools import WORKSPACE_DIR

        pipeline_runner = StructuredPipelineRunner(
            llm_client=self.llm_client,
            workspace_dir=WORKSPACE_DIR,
            verbose=self.basic_agent.verbose,
            knowledge_store=self.basic_agent.knowledge_store,
            guardrails_enabled=self.basic_agent.guardrails_enabled,
            tal_mode=True,
            use_slm_profile=self.basic_agent.use_slm_profile,
            tool_registry=self.basic_agent.tools,
        )
        graph_result = TaskGraphRunner(pipeline_runner).run(graph, approval_callback=approval_callback)
        self.last_task_graph_result = graph_result
        for event in pipeline_runner.event_log.events:
            self.basic_agent.event_log.append(event.event_type, event.data, timestamp=event.timestamp)
        answer = graph_result.pipeline_result.final_output
        if graph_result.pipeline_result.error:
            answer += f"\n\nTask graph execution incomplete: {graph_result.pipeline_result.error}"
        return answer

    def re_plan(self, original_goal: str, completed: list[str], failed_step: str, remaining: list[str], error_context: str) -> list[str]:
        """Generates a new plan when a step fails."""
        if self.tal_mode:
            self.basic_agent.current_phase = ExecutionPhase.RECOVERY

        prompt = (
            "You are a master planner. A plan execution has failed.\n"
            f"Original Goal: {original_goal}\n"
            f"Completed Steps: {', '.join(completed) if completed else 'None'}\n"
            f"Failed Step: {failed_step}\n"
            f"Error/Result that caused failure: {error_context}\n\n"
            "Based on this failure, generate a NEW numbered list of steps to finish the original goal.\n"
            "Output ONLY the numbered list starting with 1."
        )
        
        messages = [
            {"role": "system", "content": self.planner_prompt},
            {"role": "user", "content": prompt}
        ]
        
        response = self.llm_client.generate(messages)
        return self._parse_steps(response)

    def execute_plan(self, goal: str, plan: list[str], approval_callback=None) -> str:
        """Executes the plan step-by-step using the basic agent."""
        if not plan:
            return "Could not generate a valid plan."
            
        logger.info("\n📋 Plan:")
        for i, step in enumerate(plan, 1):
            logger.info(f"  Step {i}: {step}")
            
        completed_steps = []
        completed_results = []
        remaining_steps = plan.copy()
        
        replan_attempts = 0
        max_replans = 2
        
        while remaining_steps:
            current_step = remaining_steps.pop(0)
            step_num = len(completed_steps) + 1
            
            logger.info(f"\n📌 Executing Step {step_num}: {current_step}")
            
            if self.tal_mode:
                self.basic_agent.current_phase = ExecutionPhase.EXECUTION

            # Formulate the instruction for the basic agent
            instruction = (
                f"You are executing step {step_num} of a larger plan.\n"
                f"Overall Goal: {goal}\n"
                f"Current Step: {current_step}\n"
                "Execute this step and provide a final answer when done."
            )
            
            # Use the basic agent's ReAct loop to execute this single step
            result = self.basic_agent.run_turn(
                instruction, max_steps=5, new_task=False, approval_callback=approval_callback
            )
            
            # Check if it hit the max steps error (indicating failure)
            if "Error: Agent reached maximum steps" in result or result.startswith("Error: ["):
                logger.warning(f"❌ Step failed: {result}")
                
                if replan_attempts < max_replans:
                    logger.warning("⚠️ Re-planning...")
                    import time
                    time.sleep(2 ** replan_attempts)
                    replan_attempts += 1
                    # Ask the LLM to generate a new plan from here
                    remaining_steps = self.re_plan(goal, completed_steps, current_step, remaining_steps, result)
                    if remaining_steps:
                         logger.info("\n📋 Revised Plan:")
                         for i, step in enumerate(remaining_steps, 1):
                              logger.info(f"  Step {i}: {step}")
                    else:
                         return "Failed to generate a revised plan."
                else:
                    return f"Execution aborted after {max_replans} re-planning attempts."
            else:
                # Step succeeded
                logger.info(f"✅ Step {step_num} complete. Result: {result}")
                completed_steps.append(current_step)
                completed_results.append((current_step, result))

        if self.tal_mode and self.manifest and self.manifest.verification_criteria:
            self.basic_agent.current_phase = ExecutionPhase.VERIFICATION
            from tools.file_tools import WORKSPACE_DIR
            passed, messages = run_verification(self.manifest.verification_criteria, workspace_dir=WORKSPACE_DIR)
            if not passed:
                return f"Plan executed but completion verification failed: {'; '.join(messages)}"
                
        summary = "\n\n".join(
            f"Step {index}: {step}\n{result}" for index, (step, result) in enumerate(completed_results, 1)
        )
        return summary or "All steps completed successfully."

    def run(self, goal: str, approval_callback=None) -> str:
        """Top-level entry point: Plan -> Execute"""
        if self.tal_mode:
            try:
                graph = self.plan_task_graph(goal)
            except TaskGraphValidationError as exc:
                return f"Could not generate a valid task graph: {exc}"
            return self.execute_task_graph(graph, approval_callback=approval_callback)
        logger.info("\n🤔 Thinking of a plan...")
        plan = self.plan(goal)
        return self.execute_plan(goal, plan, approval_callback=approval_callback)

    def run_with_trace(self, goal: str, approval_callback=None) -> dict:
        """Runs the planning agent and returns structured trace data for the web UI."""
        trace = {
            "response": "",
            "thoughts": [],
            "tools_used": []
        }
        
        trace["thoughts"].append("Thinking of a plan...")
        plan = self.plan(goal)
        
        if not plan:
             trace["response"] = "Could not generate a valid plan."
             return trace
             
        trace["thoughts"].append("Generated Plan:\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan)))
        
        result = self.execute_plan(goal, plan, approval_callback=approval_callback)
        trace["response"] = result
        return trace

    def run_streaming(self, goal: str, callback, approval_callback=None) -> None:
        """Runs the planning agent, emitting events via callback."""
        callback("thought", {"content": "Thinking of a plan..."})
        plan = self.plan(goal)
        
        if not plan:
             callback("error", {"content": "Could not generate a valid plan."})
             return
             
        plan_str = "Generated Plan:\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan))
        callback("thought", {"content": plan_str})
        
        context = ""
        step_results = []
        for i, step in enumerate(plan):
            callback("thought", {"content": f"Executing Step {i+1}: {step}"})
            
            instruction = f"Goal: {goal}\nCurrent Step: {step}"
            if context:
                instruction += f"\n\nContext from previous steps:\n{context}"
                
            final_outputs = []
            def intercept(event_type, data):
                if event_type in ("answer", "error"):
                    final_outputs.append(data.get("content", ""))
                callback(event_type, data)

            self.basic_agent.run_turn_streaming(instruction, intercept, max_steps=10, approval_callback=approval_callback, new_task=False)
            
            # Extract step output from basic_agent memory to build context for next steps
            if self.basic_agent.memory:
                last_msg = self.basic_agent.memory[-1]
                step_res = last_msg.get("content", "")
                context += f"Step {i+1} ({step}): {step_res[:300]}\n"
            if final_outputs:
                step_results.append((step, final_outputs[-1]))
            
        final_summary = "\n\n".join(
            f"Step {index}: {step}\n{result}" for index, (step, result) in enumerate(step_results, 1)
        )
        callback("answer", {"content": final_summary or f"Finished executing plan for goal: {goal}"})
