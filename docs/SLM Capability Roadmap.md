# Capybara SLM Capability Roadmap

**Status:** Proposed implementation plan  
**Revision date:** 2026-08-28  
**Scope:** Increase the difficulty, duration, and reliability of tasks Capybara can complete while remaining an SLM-first agent.

## 1. Mission

Capybara exists to push the practical boundaries of small language models. Its purpose is not to hide difficult tasks behind an automatic fallback to a frontier model. Its purpose is to discover how far an SLM can go when the surrounding agent system supplies the structure that the model lacks.

The central design thesis is:

> The SLM supplies local judgment and intent. Capybara supplies task structure, durable state, computation, verification, recovery, and bounded search.

Production benchmark runs must therefore remain SLM-only. A larger model may optionally be used offline to generate training examples, label traces, or propose benchmark cases, but it must not participate in the execution being scored.

## 2. Desired outcome

Capybara should be able to complete long, difficult tasks by converting them into a sequence or graph of small decisions that an SLM can make reliably. It should preserve useful work across failures, diagnose errors precisely, choose a different tactic when needed, and never claim success without evidence.

The target agent should:

- Sustain tens or hundreds of verified actions without losing task state.
- Decompose difficult goals into independently verifiable microtasks.
- Keep model-facing context small, relevant, and phase-specific.
- Prevent malformed output from reaching a tool.
- Recover from syntax errors, failed tests, empty responses, timeouts, and interruptions.
- Use deterministic tools for work that does not require model judgment.
- Explore a small number of alternatives when the first approach is uncertain.
- Measure capability gains with the SLM and task suite held constant.

## 3. Current baseline

Capybara already contains several strong foundations:

- TAL manifests, capability envelopes, action gates, and effect policies.
- Declarative acceptance verification.
- Stateful Python execution.
- Append-only execution events and feedback reports.
- Pipeline checkpoints and declared state exports.
- Planning, orchestration, and specialist roles.
- A broad unit-test suite and clean Ruff results.

The 2026-08-28 distributed-saga run demonstrates the present limit:

- Model: `qwen3.5:4b` through Ollama.
- Result: critical failure, health score 15/100.
- Progress: one of eight pipeline stages completed.
- Cost: 40,935 tokens across seven model calls.
- Reliability: three of four tool calls failed or were blocked.
- Runtime: 7,718 seconds against a configured 3,600-second pipeline deadline.
- Immediate failure: two malformed Python actions, followed by deadline exhaustion.

This is a useful baseline because the task was logically within the system's tool capabilities. The limiting factors were decomposition, action reliability, recovery, context cost, and runtime control—not missing domain knowledge.

## 4. Design principles

### 4.1 One narrow decision per model turn

An SLM should normally choose one action, answer one bounded question, or repair one known defect. It should not be asked to plan, implement, verify, and summarize a large step in one response.

### 4.2 Models propose; the runtime decides

The model may propose an action or completion. Capybara validates the proposal, executes permitted effects, records observations, runs acceptance checks, and decides whether the state transition is valid.

### 4.3 Externalize cognition

Plans, facts, artifacts, failures, budgets, and open questions belong in typed stores. They should not depend on the model reconstructing them from a long conversation transcript.

### 4.4 Determinism before generation

If parsing, hashing, counting, serialization, syntax checking, dependency analysis, or file comparison can be performed deterministically, the runtime should perform it. Model tokens should be reserved for ambiguity and judgment.

### 4.5 Preserve verified work

Recovery should restart at the smallest failed unit. A timeout or malformed action must not erase previously verified state.

### 4.6 Evidence controls completion

The final answer is a view over verified task state. It is not the source of truth and cannot convert incomplete work into success.

## 5. Target architecture

```text
User goal
  -> deterministic intake and capability discovery
  -> SLM task decomposition
  -> task-graph validation and normalization
  -> dependency-aware scheduler
  -> phase-specific SLM specialist
  -> proposal schema validation and preflight
  -> gated deterministic tool execution
  -> structured observation and evidence store
  -> acceptance verification
  -> checkpoint or targeted recovery
  -> verified artifact set and final response
```

The same SLM can operate as planner, coder, researcher, repairer, or critic. Each role receives a compact prompt, a restricted tool set, a relevant state packet, and a closed output schema.

## 6. Workstreams

### Workstream A: Reliable SLM protocol

Replace loosely parsed model text with a minimal closed protocol for four proposal types:

- `action`
- `complete`
- `query`
- `escalate`

Actions must use schema-valid arguments. Where supported, use grammar-constrained or schema-constrained generation. Otherwise, parse into a candidate object and run one bounded deterministic repair pass. A malformed proposal that cannot be repaired must produce a typed failure and a smaller follow-up request.

Required changes:

- Define a versioned proposal envelope with stable error codes.
- Remove fuzzy extraction as the normal execution path.
- Validate action arguments before an attempt is charged.
- Separate model-format errors from tool, policy, and verification failures.
- Add an explicit confidence or uncertainty signal for routing bounded search.

Acceptance gate:

- At least 99.5% valid proposals on the protocol conformance suite.
- No malformed Python, shell, or file payload reaches execution.
- Format repair consumes no more than one additional model turn.

### Workstream B: Typed task compiler and execution graph

Replace numbered plans and `DELEGATE:` lines with a typed task graph. Every node must declare:

- Stable step ID and objective.
- Dependencies and preconditions.
- Required capabilities and allowed tools.
- Input facts or artifacts.
- Expected output state or artifacts.
- Verification criteria.
- State exports.
- Step, token, retry, and time budgets.
- Recovery policy and allowed fallback tactics.

The compiler should detect oversized nodes and split them before execution. A node is oversized when it combines multiple artifacts, several independent transformations, or more than one verification domain.

For example, the saga simulation should compile into separate nodes for order data, event construction, event validation, hash-chain construction, invariant checks, recovery simulation, and artifact materialization.

Acceptance gate:

- Every executable node has at least one explicit postcondition.
- Independent nodes can run without receiving unrelated context.
- The distributed-saga benchmark reaches artifact verification without a monolithic code-generation step.

### Workstream C: Hard runtime control and trustworthy telemetry

Enforce deadlines around active provider calls rather than checking only between turns. A provider that ignores a timeout must not be able to hold the pipeline indefinitely.

Required changes:

- Add hard per-request and per-tool cancellation boundaries.
- Reserve time for checkpointing and cleanup before the pipeline deadline.
- Make timeout, cancellation, and provider-unavailable states distinct.
- Preserve original event timestamps when logs are merged.
- Record queue time, generation time, parsing time, tool time, verification time, and recovery time separately.
- Replace string-based error inference with typed execution results.

Acceptance gate:

- Observed runtime stays within 5% of the configured hard deadline.
- Event timelines remain monotonic and preserve source timestamps.
- Every failed action has one stable failure category.

### Workstream D: Error-specific repair and recovery

Create a recovery policy keyed by failure type:

| Failure | Recovery behavior |
|---|---|
| Syntax error | Parse the diagnostic, isolate the failing fragment, and request only a corrected fragment. |
| Schema error | Return invalid fields and expected types; repair those fields only. |
| Test failure | Retrieve the failing assertion, affected symbols, and latest diff. |
| Verification mismatch | Produce an expected-versus-actual state delta. |
| Empty response | Retry with a shorter prompt and stricter grammar. |
| Repeated action | Block the action signature and require a different tactic. |
| Timeout | Checkpoint, shrink the node, and resume with the remaining budget. |
| Context overflow | Rebuild the context packet from typed state instead of summarizing the entire transcript. |

Preflight generated code before execution. Python should pass AST parsing; structured data should pass schema validation; patches should apply cleanly; commands should pass policy validation.

Acceptance gate:

- At least 80% of syntax and schema defects are caught before tool execution.
- At least 60% of initially failed benchmark tasks recover without user intervention.
- No retry repeats an identical failed action unless the external state changed.

### Workstream E: External state and selective context

Divide runtime information into distinct stores:

- Task graph and scheduler state.
- Verified and unverified facts.
- Decisions and rationale.
- Artifact catalog with hashes and provenance.
- Failure history and blocked action signatures.
- Open questions and assumptions.
- Repository symbol and dependency index.
- Conversation history for user-facing continuity.

Build each model context packet from the active node rather than from a broad transcript. Include only the current objective, relevant verified facts, required artifact excerpts, latest diagnostic, authorized tools, and remaining budget.

Acceptance gate:

- Median model-facing context is reduced by at least 40% on long-task benchmarks.
- A resumed task behaves equivalently after the original conversation transcript is removed.
- Downstream nodes consume typed state or artifact references instead of prose handoffs.

### Workstream F: Tools as cognitive extensions

Add or strengthen deterministic tools that reduce the amount of reasoning the SLM must perform manually:

- Repository tree, symbol, and reference search.
- Minimal patch application and diff inspection.
- Syntax, type, and schema checks.
- Targeted test selection and execution.
- Artifact hashing, comparison, and reconciliation.
- Structured data transforms and templated materialization.
- Dependency-graph and task-graph operations.
- Read-only execution-state inspection.

All tools should return a common structured result containing success, error code, standard output, standard error, duration, changed artifacts, and retry safety.

Acceptance gate:

- Coding benchmarks use patch-based edits rather than full-file regeneration by default.
- Deterministic transforms require zero LLM calls.
- Tool observations can be consumed without brittle string matching.

### Workstream G: Bounded search and self-correction

When uncertainty is high, let the SLM propose a small number of alternatives. Capybara should score alternatives using deterministic evidence before asking an SLM critic.

Candidate scoring order:

1. Schema and syntax validity.
2. Policy compliance.
3. Static checks.
4. Targeted tests.
5. Acceptance criteria.
6. Compact SLM critique only when evidence cannot distinguish candidates.

Search must be budgeted. Default execution remains single-path; branching is enabled only for high-impact decisions or after a recoverable failure. Each branch starts from a checkpoint and cannot mutate another branch's state.

Acceptance gate:

- Bounded search improves verified success on hard tasks without more than doubling median generated tokens.
- Failed branches leave no untracked workspace changes.

### Workstream H: Trace-driven SLM improvement

Use Capybara's execution traces to improve the SLM-facing protocol and, later, the model itself.

Capture training-ready records containing:

- Active microtask and context packet.
- Proposed action.
- Validation result.
- Tool observation.
- Verification result.
- Recovery action.
- Final verified outcome.

Derive datasets for proposal formatting, tool selection, decomposition, diagnostic repair, and completion judgment. Keep benchmark tasks and near-duplicates out of training data. Lightweight adapters or LoRA training should be evaluated only after the runtime protocol and benchmark suite are stable.

Acceptance gate:

- Every benchmark run produces a replayable, privacy-reviewed trace.
- Fine-tuned variants are compared against the same base SLM and runtime configuration.
- Reported gains include both model-only and system-level ablations.

## 7. Delivery milestones

### Milestone 0: Reproducible baseline

**Goal:** Establish a trustworthy measure of current SLM capability.

Deliverables:

- Versioned `benchmarks/` task suite.
- Fixed model, decoding, machine, seed, and budget metadata.
- Repeated trials for easy, medium, hard, and endurance tasks.
- Machine-readable scorecards and saved traces.
- The distributed-saga task preserved as a regression case.

Exit criteria:

- A clean baseline can be reproduced within an agreed tolerance.
- A run is successful only when deterministic acceptance checks pass.

### Milestone 1: Reliable single-node execution

**Goal:** Make one SLM-controlled action loop highly dependable.

Deliverables:

- Closed proposal protocol.
- Typed tool results and failure codes.
- Syntax and schema preflight.
- Hard provider and tool deadlines.
- Accurate event timing.

Exit criteria:

- Protocol conformance exceeds 99.5%.
- No test can exceed its hard execution deadline.
- Malformed-action tool errors approach zero.

### Milestone 2: Decomposed difficult tasks

**Goal:** Complete difficult tasks through verified microtasks.

Deliverables:

- Typed task graph.
- Oversized-step detector and splitter.
- Dependency-aware sequential scheduler.
- Typed artifact handoffs.
- Per-node checkpoints and acceptance gates.

Exit criteria:

- At least 50% verified completion on the initial hard-task suite.
- The saga pipeline completes without a monolithic REPL generation.

### Milestone 3: Long-horizon recovery

**Goal:** Sustain progress across failures and interruptions.

Deliverables:

- Failure classifier and recovery policy.
- Automatic checkpoint resume.
- Selective context reconstruction.
- Repository and artifact indexes.
- Failure-aware replanning.

Exit criteria:

- At least 95% checkpoint-resume success.
- At least 60% recovery after an initial action failure.
- At least 70% verified completion on hard tasks.

### Milestone 4: Efficient search and parallelism

**Goal:** Improve solution quality without abandoning SLM-scale economics.

Deliverables:

- Confidence-triggered candidate generation.
- Deterministic candidate scoring.
- Isolated branch state and rollback.
- Parallel scheduling for independent graph nodes.

Exit criteria:

- Higher hard-task success with less than 2x median generation tokens.
- Parallel runs produce the same verified artifacts as equivalent sequential runs.

### Milestone 5: Trace-trained specialization

**Goal:** Improve the SLM using Capybara's own verified experience.

Deliverables:

- Curated action, planning, and recovery datasets.
- Benchmark contamination checks.
- Adapter or LoRA experiments.
- Runtime-versus-model ablation reports.

Exit criteria:

- A trained SLM variant improves verified completion at equal or lower inference cost.
- Gains persist on held-out difficult tasks.

## 8. Evaluation framework

### Benchmark categories

- Multi-file feature implementation.
- Debugging with misleading symptoms.
- Repository-wide refactoring.
- Data analysis with multiple artifacts.
- Research followed by implementation.
- Long pipelines with dependent state.
- Partial failure and idempotent recovery.
- Provider timeout and process interruption.
- Conflicting constraints and clarification decisions.
- Endurance tasks requiring at least 50 verified actions.

### Primary metrics

- Verified task completion rate.
- Success per billion model parameters.
- Success per 10,000 generated tokens.
- Median and p95 wall-clock time.
- Valid proposal rate.
- Tool-error rate.
- Recovery rate after first failure.
- Checkpoint-resume success.
- Human-intervention rate.
- Context tokens per verified step.
- Longest verified action sequence before failure.
- Percentage of work completed deterministically.

### Required ablations

Every major capability claim should compare:

- Base SLM with basic ReAct.
- Base SLM with TAL enforcement.
- Base SLM with typed task graphs.
- Base SLM with recovery enabled.
- Base SLM with bounded search enabled.
- Fine-tuned SLM with the same runtime.

This separates improvements caused by the model from improvements caused by the agent system.

## 9. Initial implementation backlog

The first development cycle should complete these items in order:

1. Add a hard-deadline test using a provider that ignores its requested timeout.
2. Enforce an outer cancellation boundary around model generation.
3. Preserve source timestamps when merging event logs.
4. Define typed tool results and stable failure codes.
5. Add AST preflight for Python proposals.
6. Replace the planner's numbered-list output with a task-graph schema.
7. Replace orchestrator `DELEGATE:` parsing with typed delegation nodes.
8. Add node-size heuristics and deterministic step splitting.
9. Checkpoint after each verified graph node and make resume a first-class run mode.
10. Build expected-versus-actual verification deltas for recovery prompts.
11. Add selective context construction from task, fact, artifact, and failure stores.
12. Convert the distributed-saga pipeline into the first hard-task regression benchmark.

## 10. Risks and controls

| Risk | Control |
|---|---|
| Scaffolding becomes more complex than the model | Keep the model protocol minimal and move complexity into tested runtime modules. |
| Excessive decomposition increases latency | Measure task-graph overhead and merge nodes whose deterministic interfaces are stable. |
| Bounded search multiplies token cost | Trigger it only from uncertainty or failure and enforce a strict branch budget. |
| Verification overfits known tasks | Maintain held-out tasks and vary data, filenames, ordering, and failure injection. |
| Trace training contaminates benchmarks | Hash and quarantine benchmark prompts and derived variants. |
| Deterministic tools hide model weakness | Report model-only and full-system ablations; Capybara's primary product metric remains full-system verified success. |
| Long tasks corrupt shared state | Use isolated run scopes, artifact hashes, atomic checkpoints, and branch-local mutations. |

## 11. Definition of done

This roadmap reaches its first major objective when the same production SLM that failed the current saga benchmark can reliably complete a suite of difficult, multi-stage tasks without a larger-model fallback, while:

- Staying within hard time and token budgets.
- Producing schema-valid actions.
- Preserving and resuming verified state.
- Recovering from common model and tool failures.
- Passing deterministic artifact and behavior checks.
- Producing replayable evidence for every completion claim.

At that point, Capybara will not merely wrap an SLM in a chat loop. It will be an execution system designed specifically to turn small, local decisions into long-horizon, verifiable accomplishment.
