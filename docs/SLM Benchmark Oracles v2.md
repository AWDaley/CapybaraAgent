# Observed-evidence benchmark suite v2

The original `benchmarks/slm_v1.json` remains immutable. The new
`benchmarks/slm_v2.json` adds typed independent success oracles for all four
cases, preserving versioned fingerprints and reproducibility.

Evidence collection is scoped to specific requested REPL variable names and
output artifact filenames and occurs **before the isolated trial workspace is
destroyed**. The trial uses request-scoped workspace context rather than
mutating the application-wide WORKSPACE_DIR. Concurrent benchmark trials
serialize access to the legacy REPL global state; use isolated worker
processes before supporting untrusted parallel model runs. The capture rejects arbitrary Python objects, large values,
NaN/Infinity, and oversized artifact files. Artifacts include captured
UTF-8 content, size, and SHA-256 for replayable offline scoring. Do not use
real customer files in benchmark runs; scorecards include bounded captured
synthetic data.

Cases:
1. Calculator: exact final answer and actual calculator result.
2. Squares: exact observed `benchmark_numbers` variable and final-answer values.
3. Diagnostic: exact observed `benchmark_summary` dictionary for [2,4,6,8].
4. Distributed saga: recompute all 26 SHA-256 ledger links and independently
   check order, compensation, duplicate suppression, export manifest, and
   report cross-references from three captured artifacts.

The `distributed_saga_v1` oracle is deterministic and does not execute
Python scripts, model text, or arbitrary assertions. An agent claiming
success with no independently observed state or files scores **failure**
rather than success. A case is scorable because its oracle is defined, but
a positive score still requires the appropriate execution backend and tools.
For stateful REPL, do not enable `CAPYBARA_UNSAFE_LOCAL_EXEC` for untrusted
prompts; use a reviewed isolated backend. The default safe mode disables
the model-directed in-process REPL.

**Important**: The saga prompt in the plain ReAct benchmark does not
automatically load the eight-stage `data/distributed_saga_recovery_pipeline.json`.
A meaningful long-horizon comparison requires a dedicated pipeline-capable
runner for both baseline and TAL. The v2 oracle provides reproducible scoring
for its artifacts but is not evidence that a standalone model can execute the
pipeline. Complete execution-mode parity and actual repeated model trials
before reporting capability improvements.
