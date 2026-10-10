"""Typed task graphs for decomposing difficult SLM tasks into verified nodes."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .effect_classes import EffectClass, get_effect_class
from .pipeline_runner import PipelineExecutionResult, StructuredPipelineRunner
from .schemas import OutputSpec, PipelineStep, StructuredPipeline


class TaskGraphValidationError(ValueError):
    """Raised when a graph cannot be scheduled safely."""


@dataclass(frozen=True)
class TaskGraphNode:
    node_id: str
    objective: str
    dependencies: tuple[str, ...] = ()
    specialist: str = "general"
    tool_allowlist: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)
    verification_criteria: tuple[dict[str, Any], ...] = ()
    state_exports: tuple[str, ...] = ()
    output_spec: OutputSpec | None = None
    max_retries: int = 2
    max_steps: int | None = None
    subtasks: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskGraphNode":
        node_id = str(data.get("node_id") or data.get("step_id") or data.get("id") or "").strip()
        objective = str(data.get("objective") or data.get("task") or data.get("goal") or "").strip()
        if not node_id or not objective:
            raise TaskGraphValidationError("Task graph node requires node_id and objective")
        dependencies = data.get("dependencies") or data.get("depends_on") or []
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        if not isinstance(dependencies, list) or not all(isinstance(item, str) and item.strip() for item in dependencies):
            raise TaskGraphValidationError(f"Node '{node_id}' dependencies must be non-empty strings")
        tools = data.get("tool_allowlist") or data.get("tools") or []
        if isinstance(tools, str):
            tools = [item.strip() for item in tools.split(",") if item.strip()]
        if not isinstance(tools, list) or not all(isinstance(item, str) and item.strip() for item in tools):
            raise TaskGraphValidationError(f"Node '{node_id}' tools must be non-empty strings")
        inputs = data.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise TaskGraphValidationError(f"Node '{node_id}' inputs must be an object")
        criteria = data.get("verification_criteria") or data.get("verification") or []
        if isinstance(criteria, dict):
            criteria = [criteria]
        if not isinstance(criteria, list) or not all(isinstance(item, dict) for item in criteria):
            raise TaskGraphValidationError(f"Node '{node_id}' verification criteria must be objects")
        exports = data.get("state_exports") or []
        if isinstance(exports, str):
            exports = [item.strip() for item in exports.split(",") if item.strip()]
        if not isinstance(exports, list) or not all(isinstance(item, str) and item.isidentifier() for item in exports):
            raise TaskGraphValidationError(f"Node '{node_id}' state exports must be Python identifiers")
        raw_output = data.get("output_spec") or data.get("output")
        output_spec = OutputSpec.from_dict(raw_output) if isinstance(raw_output, dict) else None
        retries = int(data.get("max_retries", 2))
        steps = int(data["max_steps"]) if data.get("max_steps") is not None else None
        if not 0 <= retries <= 5:
            raise TaskGraphValidationError(f"Node '{node_id}' max_retries must be between 0 and 5")
        if steps is not None and not 1 <= steps <= 25:
            raise TaskGraphValidationError(f"Node '{node_id}' max_steps must be between 1 and 25")
        subtasks = data.get("subtasks") or []
        if isinstance(subtasks, str):
            subtasks = [subtasks]
        if not isinstance(subtasks, list) or not all(isinstance(item, str) and item.strip() for item in subtasks):
            raise TaskGraphValidationError(f"Node '{node_id}' subtasks must be non-empty strings")
        return cls(
            node_id=node_id,
            objective=objective,
            dependencies=tuple(dependencies),
            specialist=str(data.get("specialist") or "general"),
            tool_allowlist=tuple(tools),
            inputs=inputs,
            verification_criteria=tuple(criteria),
            state_exports=tuple(exports),
            output_spec=output_spec,
            max_retries=retries,
            max_steps=steps,
            subtasks=tuple(subtasks),
        )

    def to_pipeline_step(self) -> PipelineStep:
        return PipelineStep(
            step_id=self.node_id,
            objective=self.objective,
            specialist=self.specialist,
            tool_allowlist=list(self.tool_allowlist) or None,
            inputs=dict(self.inputs),
            inputs_from_steps=list(self.dependencies),
            verification_criteria=[dict(item) for item in self.verification_criteria],
            output_spec=self.output_spec,
            max_retries=self.max_retries,
            max_steps=self.max_steps,
            state_exports=list(self.state_exports),
        )


@dataclass(frozen=True)
class TaskGraph:
    graph_id: str
    title: str
    nodes: tuple[TaskGraphNode, ...]
    global_context: dict[str, Any] = field(default_factory=dict)
    max_steps: int = 50
    max_time_seconds: float = 900.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskGraph":
        graph_id = str(data.get("graph_id") or data.get("task_graph_id") or data.get("id") or "").strip()
        title = str(data.get("title") or data.get("name") or "").strip()
        raw_nodes = data.get("nodes")
        if not graph_id or not title:
            raise TaskGraphValidationError("Task graph requires graph_id and title")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise TaskGraphValidationError("Task graph requires a non-empty nodes list")
        nodes = tuple(TaskGraphNode.from_dict(item) for item in raw_nodes if isinstance(item, dict))
        if len(nodes) != len(raw_nodes):
            raise TaskGraphValidationError("Every task graph node must be an object")
        nodes = cls._expand_subtasks(nodes)
        ids = [node.node_id for node in nodes]
        if len(ids) != len(set(ids)):
            raise TaskGraphValidationError("Task graph node IDs must be unique")
        graph = cls(
            graph_id=graph_id,
            title=title,
            nodes=nodes,
            global_context=dict(data.get("global_context") or data.get("context") or {}),
            max_steps=int(data.get("max_steps", 50)),
            max_time_seconds=float(data.get("max_time_seconds", 900.0)),
        )
        graph.topological_order()
        return graph

    @staticmethod
    def _expand_subtasks(nodes: tuple[TaskGraphNode, ...]) -> tuple[TaskGraphNode, ...]:
        """Expand declared broad nodes into a deterministic narrow-node chain."""
        terminal_ids: dict[str, str] = {}
        for node in nodes:
            terminal_ids[node.node_id] = f"{node.node_id}__{len(node.subtasks)}" if node.subtasks else node.node_id

        expanded: list[TaskGraphNode] = []
        for node in nodes:
            dependencies = tuple(terminal_ids.get(dep, dep) for dep in node.dependencies)
            if not node.subtasks:
                expanded.append(replace(node, dependencies=dependencies))
                continue
            previous: str | None = None
            for index, objective in enumerate(node.subtasks, 1):
                child_id = f"{node.node_id}__{index}"
                child_dependencies = dependencies if previous is None else (previous,)
                is_terminal = index == len(node.subtasks)
                expanded.append(TaskGraphNode(
                    node_id=child_id,
                    objective=objective,
                    dependencies=child_dependencies,
                    specialist=node.specialist,
                    tool_allowlist=node.tool_allowlist,
                    inputs=node.inputs if index == 1 else {},
                    verification_criteria=node.verification_criteria if is_terminal else (),
                    state_exports=node.state_exports if is_terminal else (),
                    output_spec=node.output_spec if is_terminal else None,
                    max_retries=node.max_retries,
                    max_steps=node.max_steps,
                ))
                previous = child_id
        return tuple(expanded)

    def topological_order(self) -> list[TaskGraphNode]:
        """Return a stable dependency order or reject missing/cyclic dependencies."""
        by_id = {node.node_id: node for node in self.nodes}
        missing = sorted({dependency for node in self.nodes for dependency in node.dependencies if dependency not in by_id})
        if missing:
            raise TaskGraphValidationError(f"Task graph references unknown dependency nodes: {', '.join(missing)}")
        in_degree = {node.node_id: len(node.dependencies) for node in self.nodes}
        dependents: dict[str, list[str]] = {node.node_id: [] for node in self.nodes}
        for node in self.nodes:
            for dependency in node.dependencies:
                if dependency == node.node_id:
                    raise TaskGraphValidationError(f"Node '{node.node_id}' cannot depend on itself")
                dependents[dependency].append(node.node_id)
        ready = [node.node_id for node in self.nodes if in_degree[node.node_id] == 0]
        ordered: list[TaskGraphNode] = []
        while ready:
            current = ready.pop(0)
            ordered.append(by_id[current])
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)
        if len(ordered) != len(self.nodes):
            unresolved = sorted(node_id for node_id, degree in in_degree.items() if degree > 0)
            raise TaskGraphValidationError(f"Task graph contains a dependency cycle: {', '.join(unresolved)}")
        return ordered

    @staticmethod
    def _parallel_safe(node: TaskGraphNode) -> bool:
        """Only read-only nodes may share the current process concurrently."""
        return (
            bool(node.tool_allowlist)
            and not node.state_exports
            and node.output_spec is None
            and all(get_effect_class(tool) is EffectClass.READ for tool in node.tool_allowlist)
        )

    def parallel_batches(self, max_parallelism: int = 4) -> list[list[TaskGraphNode]]:
        """Return stable dependency batches, splitting any side-effecting node out.

        The current tool and REPL implementations share process state.  This
        deliberately limits concurrent execution to declared read-only nodes.
        """
        if not 1 <= max_parallelism <= 16:
            raise TaskGraphValidationError("max_parallelism must be between 1 and 16")
        pending = {node.node_id: node for node in self.nodes}
        completed: set[str] = set()
        batches: list[list[TaskGraphNode]] = []
        while pending:
            ready = [node for node in self.nodes if node.node_id in pending and set(node.dependencies).issubset(completed)]
            if not ready:  # topological_order already provides a precise error.
                raise TaskGraphValidationError("Task graph scheduler could not resolve dependencies")
            safe = [node for node in ready if self._parallel_safe(node)]
            batch = safe[:max_parallelism] if safe else [ready[0]]
            batches.append(batch)
            for node in batch:
                pending.pop(node.node_id)
                completed.add(node.node_id)
        return batches

    def to_pipeline(self) -> StructuredPipeline:
        """Compile a validated graph to the current sequential verified runner.

        Nodes are ordered only after all declared dependencies. Independent nodes
        retain no artificial handoff edge and can be scheduled in parallel by a
        later executor without changing the graph contract.
        """
        return StructuredPipeline(
            pipeline_id=self.graph_id,
            title=self.title,
            global_context=dict(self.global_context),
            steps=[node.to_pipeline_step() for node in self.topological_order()],
            max_steps=self.max_steps,
            max_time_seconds=self.max_time_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "title": self.title,
            "global_context": self.global_context,
            "max_steps": self.max_steps,
            "max_time_seconds": self.max_time_seconds,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "objective": node.objective,
                    "dependencies": list(node.dependencies),
                    "specialist": node.specialist,
                    "tool_allowlist": list(node.tool_allowlist),
                    "inputs": node.inputs,
                    "verification_criteria": list(node.verification_criteria),
                    "state_exports": list(node.state_exports),
                    "max_retries": node.max_retries,
                    "max_steps": node.max_steps,
                    "subtasks": list(node.subtasks),
                }
                for node in self.nodes
            ],
        }


@dataclass
class TaskGraphExecutionResult:
    graph_id: str
    execution_order: list[str]
    pipeline_result: PipelineExecutionResult

    @property
    def success(self) -> bool:
        return self.pipeline_result.success


class TaskGraphRunner:
    """Dependency-aware graph scheduler backed by verified pipeline execution."""

    def __init__(self, pipeline_runner: StructuredPipelineRunner):
        self.pipeline_runner = pipeline_runner

    def run(self, graph: TaskGraph, **kwargs: Any) -> TaskGraphExecutionResult:
        order = graph.topological_order()
        self.pipeline_runner.event_log.append(
            "task_graph_started",
            {"graph_id": graph.graph_id, "execution_order": [node.node_id for node in order]},
        )
        result = self.pipeline_runner.run(graph.to_pipeline(), **kwargs)
        self.pipeline_runner.event_log.append(
            "task_graph_completed" if result.success else "task_graph_terminated",
            {"graph_id": graph.graph_id, "success": result.success, "error": result.error},
        )
        return TaskGraphExecutionResult(
            graph_id=graph.graph_id,
            execution_order=[node.node_id for node in order],
            pipeline_result=result,
        )

    def run_read_only_parallel(
        self,
        graph: TaskGraph,
        node_runner: Any,
        max_parallelism: int = 4,
    ) -> dict[str, Any]:
        """Run an injected read-only worker in dependency-safe parallel batches.

        This is intentionally separate from the stateful pipeline runner: it
        provides real parallelism only where sharing the runtime cannot change
        task semantics.  Results retain graph order regardless of completion
        order.
        """
        batches = graph.parallel_batches(max_parallelism)
        results: dict[str, Any] = {}
        for batch in batches:
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = {node.node_id: executor.submit(node_runner, node) for node in batch}
                for node in batch:
                    results[node.node_id] = futures[node.node_id].result()
        self.pipeline_runner.event_log.append(
            "task_graph_read_only_parallel_completed",
            {"graph_id": graph.graph_id, "batches": [[node.node_id for node in batch] for batch in batches]},
        )
        return results
