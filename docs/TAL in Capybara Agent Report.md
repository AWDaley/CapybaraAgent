# TAL in the Greater Context of Capybara Agent

**Repository report — 28 August 2026**

## Executive summary

TAL (Task Abstraction Language) is Capybara’s execution-contract and enforcement
layer. It does not replace the language model, provider adapters, tools, ReAct
loop, planner, or orchestrator. Instead, it surrounds those components with
deterministic rules for what the model may propose, what the runtime may execute,
how progress is bounded, what counts as evidence, and when Capybara may claim
completion.

The central relationship is:

```text
User goal
  -> Capybara architecture selection
  -> TAL task contract and phase context
  -> model proposal
  -> schema/capability/effect/safety/approval gate
  -> tool or specialist execution
  -> structured observation and epistemic evidence
  -> declarative verification
  -> event log, checkpoint, feedback, and final response
```

This makes TAL especially important to Capybara’s SLM-first objective. The model
still supplies local judgment—choosing a tool, writing a bounded action, or
deciding that a task is complete—while Capybara supplies durable state,
permissions, budgets, scheduling, recovery, and evidence. The model is therefore
one participant in a controlled task system rather than the sole source of task
state or authority.

## 1. Capybara without and with TAL

Capybara’s base architecture is organized around several layers:

- `llm_client.py` and `providers/` abstract calls to Ollama, OpenAI, and Gemini.
- `tools/` exposes calculations, memory, file operations, web access, command
  execution, and the stateful Python REPL through `TOOL_REGISTRY`.
- `agent.py` implements the core `BasicAgent` ReAct loop.
- `planning_agent.py` adds plan/execute behavior.
- `agents/orchestrator.py` adds specialist delegation and synthesis.
- `memory/`, `context_manager.py`, and the web/CLI entry points provide
  conversation continuity and interfaces.

`BasicAgent` receives a `tal_mode` flag. When it is false, Capybara retains the
legacy ReAct behavior and legacy guardrail tiers. When it is true, the agent
initializes a TAL state bundle: an epistemic store, phase, event log, action
gate, capability envelope, budget tracker, context packer, and task manifest.
See [`agent.py`](../agent.py), especially the constructor and task-loop setup.

The web UI defaults `tal_mode` to true for every new browser session. The CLI
asks whether TAL should be enabled and defaults to yes. Thus, TAL is an optional
compatibility layer in the codebase but the normal web execution path.

## 2. TAL’s core contract

At task intake, TAL compiles the user goal into an immutable `TaskManifest`.
The manifest contains:

- the normalized goal;
- the effective capabilities, computed from requested tools, available tools,
  and policy denials;
- a bounded budget for steps, time, tool errors, and repair attempts; and
- declarative verification criteria.

The manifest is serialized canonically and signed with a SHA-256 content hash.
Run metadata such as the timestamp and generated manifest ID is excluded from the
hash, so the hash represents the task contract itself. Before a direct gated
action, the agent checks that the manifest hash still matches. This prevents
mutable caller state from silently widening or changing the contract during a
run. See [`tal/manifest.py`](../tal/manifest.py) and
[`tal/capability.py`](../tal/capability.py).

Verification criteria can be supplied explicitly or inferred from common output
filenames in the goal. This is a useful bridge from Capybara’s conversational
interface to deterministic acceptance: a request to create `report.md` can
acquire a file-existence/non-empty acceptance gate without requiring the model to
remember to verify it.

## 3. The model/runtime boundary

In TAL mode, the model’s response is interpreted as one of four proposal types:

1. `action` — call one named tool with typed arguments;
2. `complete` — propose a final answer;
3. `query` — ask the user for missing information; or
4. `escalate` — report that the runtime cannot safely or successfully continue.

The preferred protocol is strict JSON with a closed set of fields. Capybara
performs bounded deterministic JSON repair for common formatting defects; an
unrepairable strict proposal becomes an escalation rather than being passed to a
tool. The more permissive parser remains for non-TAL compatibility and migration
tests. See [`tal/proposal_types.py`](../tal/proposal_types.py),
[`tal/repair.py`](../tal/repair.py), and the TAL branch of
[`agent.py`](../agent.py).

This boundary embodies TAL’s most important design rule: the model proposes, but
the runtime decides. Free-form model text cannot itself authorize a tool, change
the task budget, establish a verified fact, or declare successful completion.

## 4. Phase-specific context and SLM adaptation

TAL divides execution into discovery, planning, execution, verification, and
recovery phases. `ContextPacker` builds a small prompt for the active phase,
including only the relevant tool subset, active step, latest observation,
selected evidence, and remaining budget.

The phase boundary is enforced in two ways:

- the context tells the model which tools are relevant; and
- the action gate rejects a tool that is not allowed for the current phase.

For example, planning has no external tools, discovery is restricted to
read/search operations, and verification excludes normal write/network tools.
Observations and stored evidence are explicitly marked as untrusted data so that
instructions embedded in tool output, web pages, or remembered content do not
become runtime policy.

The SLM profile further compresses the model-facing protocol and recognizes
compact model names such as Qwen, Gemma, Phi, Mini, or parameter sizes up to
14B. It uses a shorter JSON prompt and longer default runtime budgets for local
inference. The goal is not to make the SLM responsible for more hidden state;
the goal is to give it one narrow, well-scoped decision at a time. See
[`tal/context_packer.py`](../tal/context_packer.py) and
[`tal/slm_profile.py`](../tal/slm_profile.py).

## 5. The action gate and tool safety

Every TAL action passes a deterministic five-stage gate:

1. **Schema conformance:** tool arguments must match a closed parameter schema.
2. **Capability clearance:** the tool must be in the manifest’s effective
   capability set.
3. **Effect boundary:** the tool must be legal in the current TAL phase.
4. **Parameter sanitization:** workspace paths, shell syntax, and Python REPL
   code are checked before execution.
5. **Approval determination:** the effect policy decides whether human approval
   is required.

Effect classes are read, write, execution, network, and destructive. Reads run
   automatically; network operations are logged; writes and execution require
   confirmation; unknown tools default to destructive treatment. In the web
   streaming path, confirmation is represented as an approval event and the
   request waits for the UI. The synchronous web path uses a default-deny
   callback for dangerous operations.

TAL complements, rather than replaces, the protections in `tools/`. File tools
   constrain access to `workspace/`, command execution uses an allowlist and
   rejects shell metacharacters, and Python code is syntax/safety checked. The
   gate catches a proposal before it reaches those tools; the tools retain their
   own defensive checks at the execution boundary. See
   [`tal/action_gate.py`](../tal/action_gate.py),
   [`tal/effect_classes.py`](../tal/effect_classes.py),
   [`guardrails.py`](../guardrails.py), and
   [`tools/file_tools.py`](../tools/file_tools.py).

## 6. Execution, budgets, and evidence

When an action passes the gate, `BasicAgent` executes the registered tool in a
bounded worker and converts the result into a typed `ToolResult`. TAL records
successes, failures, duration, arguments, and a capped result excerpt. It also
records the tool result as `OBSERVED` evidence, explicitly distinguishing direct
observations from model `INFERRED` thoughts and user `REPORTED` claims.

The budget tracker limits steps, elapsed time, consecutive tool errors, and
repair attempts. Pipelines additionally share one monotonic deadline across
specialists and retries, so a handoff cannot reset the overall time budget.
Timeouts, provider failures, invalid proposals, policy blocks, and tool failures
are represented as different execution conditions for recovery and telemetry.

Completion is independently checked. If the model emits a final answer while
declared criteria are still failing, the result is fed back into the loop as a
verification failure rather than accepted. Supported criteria include file
existence, JSON shape/count checks, AST syntax, regex/non-empty output, read-only
REPL state, exact REPL graphs, and cross-entity consistency. Exit-code checks are
deliberately disabled as an alternate command-execution channel; commands must
go through the normal gated tool path. See [`tal/verification.py`](../tal/verification.py).

## 7. Epistemic state and event sourcing

TAL maintains a separate epistemic store with the states `REPORTED`, `OBSERVED`,
`INFERRED`, `ASSUMED`, `CONFLICTED`, and `VERIFIED`. This gives Capybara a
provenance model for task facts:

- user goals enter as reported claims;
- model reasoning is inferred;
- tool output is observed and untrusted;
- acceptance checks create verified evidence;
- conflicting claims can be retained instead of silently overwritten.

The append-only `EventLog` records input, proposals, repairs, gate outcomes,
tool executions, verification runs, checkpoints, completions, waits, and
escalations. `state_reducer` can replay the log into a task state, making the log
the audit source rather than treating the final answer as the source of truth.
The CLI’s session persistence path writes the event log alongside conversation
memory; the current web chat auto-save path writes memory metadata but does not
pass the event log to `SessionManager.auto_save`, so web event durability is
currently process/session-state dependent. See [`tal/epistemic.py`](../tal/epistemic.py),
[`tal/event_store.py`](../tal/event_store.py), [`memory/session_manager.py`](../memory/session_manager.py),
and [`web.py`](../web.py).

## 8. How TAL changes each Capybara architecture

### ReAct / `BasicAgent`

This is TAL’s most direct integration. A new task resets task-scoped state,
compiles a manifest, records the user input, packs phase-specific context, gets a
proposal, gates each action, records observations, and verifies the terminal
answer. The existing conversation memory remains useful for user-facing
continuity, but TAL state carries the operational facts and controls.

### Planning mode / `PlanningAgent`

In TAL mode, planning first compiles a manifest and asks the model for a closed
JSON task graph. The graph validator checks IDs, dependencies, cycles, tool
allowlists, output contracts, state exports, retries, and step limits. Subtasks
can be expanded into narrow nodes. The validated graph is converted to a
`StructuredPipeline` and executed by the verified pipeline runner.

The non-TAL path remains a numbered-list planner with legacy re-planning. This
preserves compatibility but means that the strongest typed decomposition
guarantees are available only when TAL is enabled.

### Multi-agent / `OrchestratorAgent`

TAL is propagated into specialists created by the orchestrator. Domain packs
define each specialist’s permitted tools and effect envelope; a pipeline
allowlist can narrow a pack but cannot grant it additional tools. The orchestrator
shares relevant epistemic facts with specialists and merges specialist events and
facts back into the parent log.

There are two distinct multi-agent paths:

- typed `StructuredPipeline` and `TaskGraph` inputs use the TAL scheduler;
- ordinary conversational delegation still asks for and parses
  `DELEGATE: specialist: instruction` lines, then runs each specialist through
  TAL.

Consequently, TAL fully governs specialist tool use in the legacy delegation
path, but the delegation plan and final synthesis are still comparatively
free-form. The typed graph/pipeline path is the stronger long-horizon contract.

## 9. Structured pipelines and long-horizon work

`StructuredPipelineRunner` is the main TAL execution engine for multi-step work.
It provides:

- sequential step gating: step N+1 cannot run until step N passes;
- specialist or zero-LLM deterministic harness steps;
- per-step retries and targeted verification feedback;
- output materialization from REPL state/templates before verification;
- freshness checks so a stale existing file cannot satisfy a new step;
- artifact hashes and provenance through `ArtifactCatalog`;
- atomic checkpoints containing verified steps, results, selected REPL state,
  telemetry, and remaining budgets;
- resume-time verification of the pipeline fingerprint and artifact contents; and
- an anti-cascading barrier that halts the pipeline at the first failed step.

`TaskGraph` adds dependency validation, deterministic subtask expansion, stable
topological ordering, and a read-only parallel scheduling helper. The standard
pipeline runner remains sequential because the REPL and tool implementations
share process state; only explicitly safe read-only nodes are eligible for
parallel batches.

This is where TAL changes Capybara from a chat loop into a bounded workflow
engine: intermediate work is a verified state transition with a checkpoint, not
just prose handed from one model turn to the next. See
[`tal/pipeline_runner.py`](../tal/pipeline_runner.py),
[`tal/task_graph.py`](../tal/task_graph.py),
[`tal/materializer.py`](../tal/materializer.py), and
[`tal/artifact_catalog.py`](../tal/artifact_catalog.py).

## 10. Evaluation and improvement loop

TAL also defines how Capybara measures itself. `TALTestRunner` runs prompts in
baseline and TAL modes for A/B comparison across ReAct, planning, and
multi-agent architectures. A result is successful only when the verified task
outcome passes—not merely when the model returns plausible text.

The benchmark layer supports versioned suites, repeated trials, deterministic
trial ordering, SLM-only enforcement, and machine-readable scorecards. Feedback
reports aggregate steps, tokens, tool errors, gate blocks, epistemic facts,
verification, events, and recommendations. `TraceDataset` can accept only
verified-success, non-benchmark traces and sanitizes likely credentials before
offline SLM improvement work.

Some supporting capabilities are present as reusable TAL modules but are not yet
the default end-to-end path: `RepositoryIndex` provides AST-based symbol lookup,
`BoundedSearch` provides fixed-size candidate evaluation, and `TraceDataset`
provides trace ingestion. The roadmap identifies selective context, bounded
search, richer recovery, and deeper typed decomposition as ongoing SLM
improvement work rather than assuming those facilities are already fully wired
into every agent turn.

## 11. Current assessment

The implementation is coherent and well covered: the repository’s test suite
currently reports **252 passed**. TAL’s strongest, most mature guarantees are:

- closed tool schemas and proposal types;
- capability/effect/approval gating;
- workspace and execution safety checks;
- explicit epistemic provenance;
- independent declarative verification;
- pipeline retries, checkpoints, artifact freshness, and anti-cascading; and
- replayable telemetry and verified-outcome benchmarking.

The main architectural boundaries are:

1. TAL can be disabled, in which case Capybara intentionally falls back to the
   legacy free-form paths.
2. Ordinary orchestrator delegation still uses legacy `DELEGATE:` text parsing,
   even though specialist actions are TAL-gated.
3. The strongest manifest integrity checks live in direct `BasicAgent` action
   execution; typed pipelines rely primarily on their own validated pipeline,
   graph, scheduler, artifact, and verification contracts.
4. Web memory auto-save does not currently persist the event log through the
   `SessionManager` call, limiting replay durability across a process restart.
5. Several roadmap components—especially repository-aware context, bounded
   search, and failure-specific recovery—exist in modular form but are not yet
   universal parts of the normal loop.

Overall, TAL’s role is to make Capybara’s existing agent architectures
trustworthy at system level. It supplies the missing control plane around an
SLM: authority is explicit, state is typed, actions are bounded, artifacts are
checked, failures are visible, and completion is an evidence-backed runtime
decision.

## Repository references

- [`docs/TAL Specification.md`](TAL%20Specification.md)
- [`docs/SLM Capability Roadmap.md`](SLM%20Capability%20Roadmap.md)
- [`agent.py`](../agent.py)
- [`planning_agent.py`](../planning_agent.py)
- [`agents/orchestrator.py`](../agents/orchestrator.py)
- [`tal/`](../tal/)
- [`tests/`](../tests/)
